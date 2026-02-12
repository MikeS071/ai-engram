#!/usr/bin/env python3
"""
AIEngram MCP Server
Exposes semantic search, memory, and file tools via the Model Context Protocol.
Allows AI assistants (GitHub Copilot, Claude, etc.) to search your markdown content.
"""

import re
import os
import sys
import json
import math
import time
import pickle
import hashlib
import threading
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter

# Pre-import heavy libraries BEFORE MCP starts.
# Suppress library stdout/stderr noise that would corrupt the MCP JSON-RPC
# stdio transport.  Must happen before any heavy imports.
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TQDM_DISABLE", "1")

# Pre-import heavy libraries BEFORE the MCP event loop starts.
# numpy and sentence-transformers can write to stdout during first import,
# which would corrupt the JSON-RPC stream.  Redirect stdout→stderr briefly.
_real_stdout = sys.stdout
sys.stdout = sys.stderr
try:
    import numpy as np
    from sentence_transformers import SentenceTransformer
finally:
    sys.stdout = _real_stdout

import anyio
from mcp.server.fastmcp import FastMCP

# ─── Configuration ───────────────────────────────────────────────────────────

WORKSPACE_ROOT = Path(os.environ.get("AIENGRAM_ROOT", Path(__file__).parent))
CACHE_FILE = WORKSPACE_ROOT / ".aiengram_cache.pkl"
MEMORY_FILE = WORKSPACE_ROOT / ".aiengram_memory.jsonl"
MEMORY_CACHE_FILE = WORKSPACE_ROOT / ".aiengram_memory_cache.pkl"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
CHUNK_SIZE = 500
MEMORY_CATEGORIES = {"decision", "insight", "context", "preference", "task", "note"}

# ─── Initialize MCP Server ──────────────────────────────────────────────────

mcp = FastMCP(
    "AIEngram",
    instructions=(
        "Search, browse, and read markdown content from the user's workspace. "
        "Use 'search' for keyword queries, 'list_files' to browse collections, "
        "'stats' for an overview, and 'read_file' to read full file contents."
    ),
)

# ─── Helpers ─────────────────────────────────────────────────────────────────

def get_files(filter_key: str = "all") -> list[Path]:
    """Collect markdown files based on filter."""
    files = []

    if filter_key in ("posts", "all"):
        posts_dir = WORKSPACE_ROOT / "Blog Posts"
        if posts_dir.exists():
            files.extend(posts_dir.glob("*.md"))

    if filter_key in ("outlines", "all"):
        outlines_dir = WORKSPACE_ROOT / "Post Outlines"
        if outlines_dir.exists():
            files.extend(outlines_dir.glob("*.md"))

    if filter_key in ("prompts", "all"):
        files.extend(f for f in WORKSPACE_ROOT.glob("Prompt*.md"))

    if filter_key in ("kb", "all"):
        files.extend(f for f in WORKSPACE_ROOT.glob("KB*.md"))

    if filter_key == "all":
        for f in WORKSPACE_ROOT.glob("*.md"):
            if f not in files:
                files.append(f)

    return sorted(set(files))


def read_file_content(path: Path) -> str:
    """Read file content safely."""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def extract_title(content: str) -> str | None:
    """Extract the first heading from markdown content."""
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return None


def tokenize(text: str) -> list[str]:
    """Simple tokenizer: lowercase, split on non-alphanumeric."""
    return re.findall(r"[a-z0-9]+", text.lower())


def relative_path(path: Path) -> str:
    """Get path relative to workspace root."""
    try:
        return str(path.relative_to(WORKSPACE_ROOT))
    except ValueError:
        return str(path)


# ─── BM25 Search Engine ─────────────────────────────────────────────────────

class BM25:
    """Simple BM25 search implementation."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.docs: dict[Path, str] = {}
        self.doc_tokens: dict[Path, list[str]] = {}
        self.doc_lengths: dict[Path, int] = {}
        self.avg_dl: float = 0
        self.df: Counter = Counter()
        self.N: int = 0

    def index(self, files: list[Path]):
        for f in files:
            content = read_file_content(f)
            if content:
                tokens = tokenize(content)
                self.docs[f] = content
                self.doc_tokens[f] = tokens
                self.doc_lengths[f] = len(tokens)
                for term in set(tokens):
                    self.df[term] += 1
        self.N = len(self.docs)
        if self.N > 0:
            self.avg_dl = sum(self.doc_lengths.values()) / self.N

    def search(self, query: str, n: int = 10) -> list[tuple[Path, float, str]]:
        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        scores: dict[Path, float] = {}
        for path, tokens in self.doc_tokens.items():
            tf_map = Counter(tokens)
            score = 0.0
            for term in query_tokens:
                if term not in tf_map:
                    continue
                tf = tf_map[term]
                df = self.df.get(term, 0)
                idf = math.log((self.N - df + 0.5) / (df + 0.5) + 1)
                dl = self.doc_lengths[path]
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * (1 - self.b + self.b * dl / max(self.avg_dl, 1))
                score += idf * numerator / denominator
            if score > 0:
                scores[path] = score

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:n]

        results = []
        for path, score in ranked:
            snippet = self._get_snippet(self.docs[path], query_tokens)
            results.append((path, score, snippet))
        return results

    @staticmethod
    def _get_snippet(content: str, query_tokens: list[str], context_chars: int = 200) -> str:
        lines = content.split("\n")
        best_line = ""
        best_score = 0
        for line in lines:
            line_lower = line.lower()
            score = sum(1 for t in query_tokens if t in line_lower)
            if score > best_score and len(line.strip()) > 10:
                best_score = score
                best_line = line.strip()
        if not best_line:
            for line in lines:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and len(stripped) > 10:
                    best_line = stripped
                    break
        if len(best_line) > context_chars * 2:
            for token in query_tokens:
                idx = best_line.lower().find(token)
                if idx >= 0:
                    start = max(0, idx - context_chars)
                    end = min(len(best_line), idx + context_chars)
                    return ("..." if start > 0 else "") + best_line[start:end] + ("..." if end < len(best_line) else "")
            best_line = best_line[: context_chars * 2] + "..."
        return best_line


# ─── Semantic Search Engine ──────────────────────────────────────────────────

class SemanticEngine:
    """Sentence-transformer semantic search with lazy model loading and disk cache."""

    def __init__(self):
        self._model = None
        self.chunks: list[dict] = []
        self.embeddings = None
        self.file_mtimes: dict[str, float] = {}
        self._loaded = False

    @property
    def model(self):
        """Lazy-load the sentence-transformer model on first use.

        Model loading happens inside anyio.to_thread.run_sync via the async
        tool wrappers, so it won't block the MCP event loop.  Library noise is
        suppressed by the TRANSFORMERS_VERBOSITY / HF env vars set at startup.
        """
        if self._model is None:
            self._model = SentenceTransformer(EMBEDDING_MODEL)
        return self._model

    def _chunk_text(self, content: str, path: Path) -> list[dict]:
        """Split content into chunks on headings and paragraphs (~CHUNK_SIZE chars)."""
        title = extract_title(content) or path.stem

        sections = re.split(r"(?m)^(#{1,3}\s+.+)$", content)

        raw_blocks: list[str] = []
        current = ""
        for part in sections:
            part = part.strip()
            if not part:
                continue
            if re.match(r"^#{1,3}\s+", part):
                if current.strip():
                    raw_blocks.append(current.strip())
                current = part + "\n"
            else:
                current += part + "\n"
        if current.strip():
            raw_blocks.append(current.strip())

        chunks = []
        for block in raw_blocks:
            if len(block) <= CHUNK_SIZE * 1.5:
                chunks.append(block)
            else:
                paragraphs = re.split(r"\n\s*\n", block)
                acc = ""
                for para in paragraphs:
                    if len(acc) + len(para) > CHUNK_SIZE and acc:
                        chunks.append(acc.strip())
                        acc = para + "\n\n"
                    else:
                        acc += para + "\n\n"
                if acc.strip():
                    chunks.append(acc.strip())

        return [
            {"path": str(path), "title": title, "text": c, "start_idx": i}
            for i, c in enumerate(chunks)
            if len(c.strip()) > 20
        ]

    def _load_cache(self) -> bool:
        """Load cached embeddings from disk."""
        if CACHE_FILE.exists():
            try:
                with open(CACHE_FILE, "rb") as f:
                    data = pickle.load(f)
                self.chunks = data["chunks"]
                self.embeddings = data["embeddings"]
                self.file_mtimes = data["file_mtimes"]
                return True
            except Exception:
                return False
        return False

    def _save_cache(self):
        """Persist embeddings to disk."""
        data = {
            "chunks": self.chunks,
            "embeddings": self.embeddings,
            "file_mtimes": self.file_mtimes,
        }
        with open(CACHE_FILE, "wb") as f:
            pickle.dump(data, f)

    def _get_stale_files(self, files: list[Path]) -> tuple[list[Path], list[Path]]:
        """Return (files_needing_reindex, unchanged_files)."""
        stale = []
        fresh = []
        for f in files:
            key = str(f)
            current_mtime = f.stat().st_mtime
            if key in self.file_mtimes and self.file_mtimes[key] == current_mtime:
                fresh.append(f)
            else:
                stale.append(f)
        return stale, fresh

    def build_index(self, files: list[Path], force: bool = False) -> str:
        """Build or incrementally update the semantic index."""
        if not force:
            self._load_cache()

        stale, fresh = self._get_stale_files(files)

        current_paths = {str(f) for f in files}
        removed_paths = {c["path"] for c in self.chunks} - current_paths

        if not stale and not removed_paths:
            self._loaded = True
            return f"Index up to date. {len(self.chunks)} chunks across {len(files)} files."

        keep_chunks = []
        keep_embeddings = []
        if self.embeddings is not None and self.chunks:
            for i, chunk in enumerate(self.chunks):
                if chunk["path"] not in {str(s) for s in stale} and chunk["path"] not in removed_paths:
                    keep_chunks.append(chunk)
                    keep_embeddings.append(self.embeddings[i])

        new_chunks = []
        new_mtimes = {}
        for f in stale:
            content = read_file_content(f)
            if content:
                new_chunks.extend(self._chunk_text(content, f))
                new_mtimes[str(f)] = f.stat().st_mtime

        new_embeddings = None
        if new_chunks:
            texts = [c["text"] for c in new_chunks]
            new_embeddings = self.model.encode(texts, show_progress_bar=False, convert_to_numpy=True)

        self.chunks = keep_chunks + new_chunks
        if keep_embeddings and new_embeddings is not None:
            self.embeddings = np.vstack([np.array(keep_embeddings), new_embeddings])
        elif new_embeddings is not None:
            self.embeddings = new_embeddings
        elif keep_embeddings:
            self.embeddings = np.array(keep_embeddings)
        else:
            self.embeddings = np.array([])

        self.file_mtimes = {str(f): f.stat().st_mtime for f in files if f.exists()}
        self._loaded = True
        self._save_cache()

        return (
            f"Indexed {len(stale)} changed file(s), "
            f"kept {len(fresh)} cached. "
            f"Total: {len(self.chunks)} chunks across {len(files)} files."
        )

    def search(self, query: str, files: list[Path], n: int = 10) -> list[dict]:
        """Semantic search. Auto-builds index if needed."""
        if not self._loaded:
            self.build_index(files)

        if self.embeddings is None or len(self.embeddings) == 0:
            return []

        query_emb = self.model.encode([query], show_progress_bar=False, convert_to_numpy=True)[0]

        norms = np.linalg.norm(self.embeddings, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        normed = self.embeddings / norms
        q_norm = query_emb / max(np.linalg.norm(query_emb), 1e-10)
        scores = normed @ q_norm

        valid_paths = {str(f) for f in files}
        indexed = [(i, scores[i]) for i in range(len(scores)) if self.chunks[i]["path"] in valid_paths]
        indexed.sort(key=lambda x: x[1], reverse=True)

        seen_files: dict[str, int] = {}
        results = []
        for idx, score in indexed:
            chunk = self.chunks[idx]
            fpath = chunk["path"]
            seen_files[fpath] = seen_files.get(fpath, 0) + 1
            if seen_files[fpath] <= 2:
                results.append({
                    "path": Path(fpath),
                    "title": chunk["title"],
                    "score": float(score),
                    "snippet": chunk["text"][:300],
                })
            if len(results) >= n:
                break

        return results


# Module-level singleton (lazy, no model loaded until first search)
_semantic_engine = SemanticEngine()


# ─── Context Memory Store ───────────────────────────────────────────────────

class MemoryStore:
    """Persistent conversation memory with semantic recall.

    Stores memories as JSON-Lines (.aiengram_memory.jsonl) and maintains
    a separate embedding cache (.aiengram_memory_cache.pkl) for semantic search.
    Reuses the shared SemanticEngine model singleton for embeddings.
    """

    VALID_CATEGORIES = MEMORY_CATEGORIES

    def __init__(self, memory_file: Path = MEMORY_FILE, cache_file: Path = MEMORY_CACHE_FILE):
        self.memory_file = memory_file
        self.cache_file = cache_file
        self.memories: list[dict] = []
        self.embeddings = None
        self._loaded = False

    def _generate_id(self) -> str:
        """Generate a short unique memory ID."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        h = hashlib.md5(f"{ts}{len(self.memories)}".encode()).hexdigest()[:4]
        return f"m_{ts}_{h}"

    def _load(self):
        """Load memories from JSONL file and embedding cache."""
        if self._loaded:
            return

        self.memories = []
        if self.memory_file.exists():
            for line in self.memory_file.read_text(encoding="utf-8").strip().split("\n"):
                line = line.strip()
                if line:
                    try:
                        self.memories.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        if self.cache_file.exists():
            try:
                with open(self.cache_file, "rb") as f:
                    data = pickle.load(f)
                self.embeddings = data.get("embeddings")
            except Exception:
                self.embeddings = None

        if self.embeddings is not None and len(self.embeddings) != len(self.memories):
            self.embeddings = None

        self._loaded = True

    def _save_memory(self, entry: dict):
        """Append a single memory entry to the JSONL file."""
        with open(self.memory_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _save_cache(self):
        """Persist memory embeddings to disk."""
        data = {"embeddings": self.embeddings}
        with open(self.cache_file, "wb") as f:
            pickle.dump(data, f)

    def _rewrite_jsonl(self):
        """Rewrite the full JSONL file (used after delete)."""
        with open(self.memory_file, "w", encoding="utf-8") as f:
            for m in self.memories:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")

    def _rebuild_embeddings(self):
        """Rebuild all memory embeddings from scratch."""
        if not self.memories:
            self.embeddings = np.array([])
            self._save_cache()
            return
        texts = [m["content"] for m in self.memories]
        self.embeddings = _semantic_engine.model.encode(
            texts, show_progress_bar=False, convert_to_numpy=True
        )
        self._save_cache()

    def remember(self, content: str, category: str = "note", tags: list[str] | None = None) -> dict:
        """Store a new memory. Returns the created entry."""
        self._load()

        if category not in self.VALID_CATEGORIES:
            category = "note"

        entry = {
            "id": self._generate_id(),
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "category": category,
            "content": content,
            "tags": tags or [],
            "source": "conversation",
        }

        self.memories.append(entry)
        self._save_memory(entry)

        new_emb = _semantic_engine.model.encode(
            [content], show_progress_bar=False, convert_to_numpy=True
        )
        if self.embeddings is not None and len(self.embeddings) > 0:
            self.embeddings = np.vstack([self.embeddings, new_emb])
        else:
            self.embeddings = new_emb
        self._save_cache()

        return entry

    def recall(self, query: str, n: int = 5, category: str | None = None) -> list[dict]:
        """Semantic search over memories. Returns top-N matches."""
        self._load()

        if not self.memories:
            return []

        if self.embeddings is None or len(self.embeddings) != len(self.memories):
            self._rebuild_embeddings()

        if self.embeddings is None or len(self.embeddings) == 0:
            return []

        query_emb = _semantic_engine.model.encode(
            [query], show_progress_bar=False, convert_to_numpy=True
        )[0]

        norms = np.linalg.norm(self.embeddings, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        normed = self.embeddings / norms
        q_norm = query_emb / max(np.linalg.norm(query_emb), 1e-10)
        scores = normed @ q_norm

        indexed = []
        for i, score in enumerate(scores):
            if category and self.memories[i].get("category") != category:
                continue
            indexed.append((i, float(score)))
        indexed.sort(key=lambda x: x[1], reverse=True)

        results = []
        for idx, score in indexed[:n]:
            mem = dict(self.memories[idx])
            mem["similarity"] = score
            results.append(mem)
        return results

    def recall_with_blog(self, query: str, n: int = 10, category: str | None = None,
                         collection: str = "all") -> dict:
        """Cross-search: recall from both memory and blog content, fused with RRF."""
        mem_results = self.recall(query, n=n, category=category)

        files = get_files(collection)
        blog_results = _semantic_engine.search(query, files, n=n) if files else []

        RRF_K = 60
        rrf_scores: dict[str, float] = {}
        rrf_items: dict[str, dict] = {}

        for rank, m in enumerate(mem_results, 1):
            key = f"memory:{m['id']}"
            rrf_scores[key] = 1.0 / (RRF_K + rank)
            rrf_items[key] = {
                "type": "memory",
                "id": m["id"],
                "content": m["content"][:200],
                "category": m.get("category", "note"),
                "similarity": m["similarity"],
                "timestamp": m.get("timestamp", ""),
            }

        for rank, b in enumerate(blog_results, 1):
            key = f"blog:{b['path']}"
            rrf_scores[key] = rrf_scores.get(key, 0) + 1.0 / (RRF_K + rank)
            if key not in rrf_items:
                rrf_items[key] = {
                    "type": "blog",
                    "title": b["title"],
                    "path": relative_path(b["path"]),
                    "similarity": b["score"],
                    "snippet": b["snippet"][:200],
                }

        combined = sorted(
            [(k, rrf_scores[k], rrf_items[k]) for k in rrf_scores],
            key=lambda x: x[1], reverse=True,
        )[:n]

        return {
            "memory_results": mem_results,
            "blog_results": blog_results,
            "combined": [
                {**item, "rrf_score": score} for _, score, item in combined
            ],
        }

    def list_memories(self, category: str | None = None, limit: int = 20) -> list[dict]:
        """List recent memories, optionally filtered by category."""
        self._load()
        filtered = self.memories
        if category:
            filtered = [m for m in filtered if m.get("category") == category]
        return list(reversed(filtered[-limit:]))

    def forget(self, memory_id: str) -> bool:
        """Delete a memory by ID. Returns True if found and deleted."""
        self._load()

        idx = None
        for i, m in enumerate(self.memories):
            if m["id"] == memory_id:
                idx = i
                break

        if idx is None:
            return False

        self.memories.pop(idx)
        if self.embeddings is not None and len(self.embeddings) > idx:
            self.embeddings = np.delete(self.embeddings, idx, axis=0)
            self._save_cache()

        self._rewrite_jsonl()
        return True

    def stats(self) -> dict:
        """Return memory statistics."""
        self._load()
        by_cat: dict[str, int] = {}
        for m in self.memories:
            cat = m.get("category", "note")
            by_cat[cat] = by_cat.get(cat, 0) + 1

        size_bytes = self.memory_file.stat().st_size if self.memory_file.exists() else 0

        return {
            "total_memories": len(self.memories),
            "by_category": by_cat,
            "storage_bytes": size_bytes,
            "storage_human": f"{size_bytes / 1024:.1f} KB" if size_bytes >= 1024 else f"{size_bytes} bytes",
            "cache_exists": self.cache_file.exists(),
        }


# Module-level memory singleton
_memory_store = MemoryStore()


# ─── File Watcher ────────────────────────────────────────────────────────────

class FileWatcher:
    """Polls for markdown and memory file changes, triggers re-indexing."""

    def __init__(self, interval: float = 5.0):
        self.interval = interval
        self._snapshot: dict[str, float] = {}
        self._memory_mtime: float = 0.0

    def _scan(self) -> dict[str, float]:
        """Return {path: mtime} for all current markdown files."""
        return {str(f): f.stat().st_mtime for f in get_files("all") if f.exists()}

    def _check_memory(self) -> bool:
        """Return True if the memory file changed since last check."""
        if not MEMORY_FILE.exists():
            return False
        mtime = MEMORY_FILE.stat().st_mtime
        if mtime != self._memory_mtime:
            self._memory_mtime = mtime
            return True
        return False

    def poll_once(self) -> None:
        """Single poll cycle: detect changes and re-index as needed."""
        current = self._scan()

        if current != self._snapshot:
            self._snapshot = current
            files = get_files("all")
            if files:
                _semantic_engine.build_index(files)

        if self._check_memory():
            _memory_store._loaded = False

    def run_forever(self) -> None:
        """Blocking loop — call from a daemon thread."""
        self._snapshot = self._scan()
        self._memory_mtime = MEMORY_FILE.stat().st_mtime if MEMORY_FILE.exists() else 0.0
        while True:
            time.sleep(self.interval)
            try:
                self.poll_once()
            except Exception:
                pass


def _start_watcher() -> None:
    """Launch the file watcher as a daemon thread."""
    watcher = FileWatcher()
    t = threading.Thread(target=watcher.run_forever, daemon=True)
    t.start()


_start_watcher()


# ─── MCP Tools ───────────────────────────────────────────────────────────────

@mcp.tool()
def search_blog(query: str, collection: str = "all", max_results: int = 10) -> str:
    """Search blog markdown files using BM25 relevance ranking.

    Args:
        query: The search query (keywords or phrases)
        collection: Filter by collection - "all", "posts", "outlines", "prompts", or "kb"
        max_results: Maximum number of results to return (default 10)

    Returns:
        Ranked search results with titles, file paths, relevance scores, and snippets
    """
    valid = {"all", "posts", "outlines", "prompts", "kb"}
    if collection not in valid:
        return f"Invalid collection '{collection}'. Choose from: {', '.join(sorted(valid))}"

    files = get_files(collection)
    if not files:
        return f"No markdown files found in collection '{collection}'."

    engine = BM25()
    engine.index(files)
    results = engine.search(query, n=max_results)

    if not results:
        return f"No results found for '{query}' in '{collection}'."

    lines = [f"Found {len(results)} result(s) for '{query}' in '{collection}':\n"]
    for i, (path, score, snippet) in enumerate(results, 1):
        content = read_file_content(path)
        title = extract_title(content) or path.stem
        rel = relative_path(path)
        lines.append(f"{i}. **{title}**")
        lines.append(f"   File: {rel}")
        lines.append(f"   Score: {score:.2f}")
        if snippet:
            lines.append(f"   Snippet: {snippet}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def list_blog_files(collection: str = "all") -> str:
    """List all markdown files in the blog workspace.

    Args:
        collection: Filter by collection - "all", "posts", "outlines", "prompts", or "kb"

    Returns:
        List of all files with their titles
    """
    valid = {"all", "posts", "outlines", "prompts", "kb"}
    if collection not in valid:
        return f"Invalid collection '{collection}'. Choose from: {', '.join(sorted(valid))}"

    files = get_files(collection)
    if not files:
        return f"No markdown files found in collection '{collection}'."

    lines = [f"{len(files)} file(s) in '{collection}':\n"]
    for f in files:
        content = read_file_content(f)
        title = extract_title(content) or f.stem
        rel = relative_path(f)
        lines.append(f"- **{title}** — {rel}")

    return "\n".join(lines)


@mcp.tool()
def blog_stats() -> str:
    """Show statistics about the blog workspace.

    Returns:
        Summary of file counts and word totals across all collections
    """
    all_files = get_files("all")
    posts = get_files("posts")
    outlines = get_files("outlines")
    prompts = get_files("prompts")
    kb = get_files("kb")

    total_words = 0
    for f in all_files:
        content = read_file_content(f)
        total_words += len(content.split())

    lines = [
        "Workspace Stats:",
        f"- Total files: {len(all_files)}",
        f"- Blog posts: {len(posts)}",
        f"- Post outlines: {len(outlines)}",
        f"- Prompts: {len(prompts)}",
        f"- Knowledge base: {len(kb)}",
        f"- Total words: ~{total_words:,}",
    ]
    return "\n".join(lines)


@mcp.tool()
def read_blog_file(file_path: str) -> str:
    """Read the full content of a markdown file from the blog workspace.

    Args:
        file_path: Relative path to the file (e.g. "Blog Posts/02 - blog - Vision Forms In Isolation.md")

    Returns:
        The full markdown content of the file
    """
    full_path = WORKSPACE_ROOT / file_path
    if not full_path.exists():
        for f in get_files("all"):
            if file_path.lower() in str(f).lower():
                full_path = f
                break
        else:
            return f"File not found: {file_path}"

    if not str(full_path.resolve()).startswith(str(WORKSPACE_ROOT.resolve())):
        return "Access denied: file is outside the workspace."

    content = read_file_content(full_path)
    if not content:
        return f"File is empty or could not be read: {file_path}"

    return content


@mcp.tool()
async def semantic_search_blog(query: str, collection: str = "all", max_results: int = 10) -> str:
    """Search blog files using semantic similarity (meaning-based, not just keywords).

    Uses sentence-transformers to find content that is conceptually similar to your query,
    even if the exact words don't appear. Great for finding thematically related posts.

    Args:
        query: Natural language query describing what you're looking for
        collection: Filter by collection - "all", "posts", "outlines", "prompts", or "kb"
        max_results: Maximum number of results to return (default 10)

    Returns:
        Ranked results with titles, file paths, similarity scores, and text snippets
    """
    valid = {"all", "posts", "outlines", "prompts", "kb"}
    if collection not in valid:
        return f"Invalid collection '{collection}'. Choose from: {', '.join(sorted(valid))}"

    files = get_files(collection)
    if not files:
        return f"No markdown files found in collection '{collection}'."

    results = await anyio.to_thread.run_sync(
        lambda: _semantic_engine.search(query, files, n=max_results)
    )

    if not results:
        return f"No semantic results found for '{query}' in '{collection}'."

    lines = [f"Found {len(results)} semantic result(s) for '{query}' in '{collection}':\n"]
    for i, r in enumerate(results, 1):
        rel = relative_path(r["path"])
        lines.append(f"{i}. **{r['title']}**")
        lines.append(f"   File: {rel}")
        lines.append(f"   Similarity: {r['score']:.4f}")
        snippet = r["snippet"].replace("\n", " ").strip()
        if snippet:
            lines.append(f"   Snippet: {snippet}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
async def build_index(collection: str = "all", force: bool = False) -> str:
    """Build or refresh the semantic search index.

    Call this to pre-build the embedding cache so semantic searches are instant.
    The index auto-builds on first semantic search, but this lets you control when.

    Args:
        collection: Which collection to index - "all", "posts", "outlines", "prompts", or "kb"
        force: If True, rebuild from scratch ignoring cache (default False)

    Returns:
        Summary of indexing results
    """
    valid = {"all", "posts", "outlines", "prompts", "kb"}
    if collection not in valid:
        return f"Invalid collection '{collection}'. Choose from: {', '.join(sorted(valid))}"

    files = get_files(collection)
    if not files:
        return f"No markdown files found in collection '{collection}'."

    return await anyio.to_thread.run_sync(
        lambda: _semantic_engine.build_index(files, force=force)
    )


# ─── Context Memory Tools ───────────────────────────────────────────────────

@mcp.tool()
async def remember(content: str, category: str = "note", tags: list[str] | None = None) -> str:
    """Store a memory — a decision, insight, preference, task, or any notable context.

    Call this whenever the user makes a decision, states a preference, completes a task,
    or shares important context that should persist across conversations.

    Args:
        content: The memory content to store (be specific and concise)
        category: One of: decision, insight, context, preference, task, note
        tags: Optional list of short keyword tags for organization

    Returns:
        Confirmation with the stored memory ID
    """
    valid = MEMORY_CATEGORIES
    if category not in valid:
        return f"Invalid category '{category}'. Choose from: {', '.join(sorted(valid))}"

    entry = await anyio.to_thread.run_sync(
        lambda: _memory_store.remember(content, category=category, tags=tags)
    )
    return (
        f"✅ Memory stored.\n"
        f"  ID: {entry['id']}\n"
        f"  Category: {entry['category']}\n"
        f"  Tags: {', '.join(entry['tags']) if entry['tags'] else '—'}\n"
        f"  Content: {entry['content'][:150]}{'...' if len(entry['content']) > 150 else ''}"
    )


@mcp.tool()
async def recall(query: str, max_results: int = 5, category: str | None = None) -> str:
    """Search conversation memory using semantic similarity.

    Use this at the start of a conversation or task to retrieve relevant context
    from past interactions — decisions made, preferences stated, tasks completed, etc.

    Args:
        query: Natural language description of what you're looking for
        max_results: Maximum memories to return (default 5)
        category: Optional filter — decision, insight, context, preference, task, note

    Returns:
        Ranked memories with similarity scores
    """
    if category and category not in MEMORY_CATEGORIES:
        return f"Invalid category '{category}'. Choose from: {', '.join(sorted(MEMORY_CATEGORIES))}"

    results = await anyio.to_thread.run_sync(
        lambda: _memory_store.recall(query, n=max_results, category=category)
    )

    if not results:
        return f"No memories found for '{query}'."

    lines = [f"Found {len(results)} memory(ies) for '{query}':\n"]
    for i, m in enumerate(results, 1):
        lines.append(f"{i}. [{m['category']}] {m['content'][:200]}")
        lines.append(f"   ID: {m['id']}  |  Similarity: {m['similarity']:.4f}  |  {m.get('timestamp', '')}")
        if m.get("tags"):
            lines.append(f"   Tags: {', '.join(m['tags'])}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
async def recall_all(query: str, max_results: int = 10, category: str | None = None,
                     collection: str = "all") -> str:
    """Cross-search: recall from BOTH conversation memory AND blog content.

    Combines memory recall with blog semantic search using reciprocal rank fusion.
    Use this for comprehensive context gathering — finds relevant memories AND blog posts.

    Args:
        query: Natural language description of what you're looking for
        max_results: Maximum total results to return (default 10)
        category: Optional memory category filter — decision, insight, context, preference, task, note
        collection: Blog collection filter — all, posts, outlines, prompts, kb

    Returns:
        Combined ranked results from memory and blog content
    """
    valid_collections = {"all", "posts", "outlines", "prompts", "kb"}
    if collection not in valid_collections:
        return f"Invalid collection '{collection}'. Choose from: {', '.join(sorted(valid_collections))}"
    if category and category not in MEMORY_CATEGORIES:
        return f"Invalid category '{category}'. Choose from: {', '.join(sorted(MEMORY_CATEGORIES))}"

    data = await anyio.to_thread.run_sync(
        lambda: _memory_store.recall_with_blog(
            query, n=max_results, category=category, collection=collection
        )
    )

    if not data["combined"]:
        return f"No results found for '{query}'."

    lines = [f"Found {len(data['combined'])} result(s) for '{query}' (memory + blog):\n"]
    for i, item in enumerate(data["combined"], 1):
        if item["type"] == "memory":
            lines.append(f"{i}. 🧠 [Memory / {item['category']}] {item['content']}")
            lines.append(f"   ID: {item['id']}  |  Similarity: {item['similarity']:.4f}  |  {item.get('timestamp', '')}")
        else:
            lines.append(f"{i}. 📄 [Blog] **{item['title']}**")
            lines.append(f"   File: {item['path']}  |  Similarity: {item['similarity']:.4f}")
            snippet = item.get("snippet", "").replace("\n", " ").strip()
            if snippet:
                lines.append(f"   Snippet: {snippet}")
        lines.append(f"   RRF Score: {item['rrf_score']:.4f}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def list_memories(category: str | None = None, limit: int = 20) -> str:
    """Browse stored memories, most recent first.

    Args:
        category: Optional filter — decision, insight, context, preference, task, note
        limit: Maximum number of memories to show (default 20)

    Returns:
        List of memories with IDs, categories, and content
    """
    if category and category not in MEMORY_CATEGORIES:
        return f"Invalid category '{category}'. Choose from: {', '.join(sorted(MEMORY_CATEGORIES))}"

    memories = _memory_store.list_memories(category=category, limit=limit)

    if not memories:
        cat_msg = f" in category '{category}'" if category else ""
        return f"No memories stored{cat_msg}."

    lines = [f"Showing {len(memories)} memory(ies){f' in {category}' if category else ''} (newest first):\n"]
    for i, m in enumerate(memories, 1):
        lines.append(f"{i}. [{m['category']}] {m['content'][:200]}")
        lines.append(f"   ID: {m['id']}  |  {m.get('timestamp', '')}")
        if m.get("tags"):
            lines.append(f"   Tags: {', '.join(m['tags'])}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def forget(memory_id: str) -> str:
    """Delete a specific memory by its ID.

    Args:
        memory_id: The memory ID to delete (e.g. "m_20250617_a3f2")

    Returns:
        Confirmation or error message
    """
    if _memory_store.forget(memory_id):
        return f"✅ Memory '{memory_id}' deleted."
    return f"❌ Memory '{memory_id}' not found."


@mcp.tool()
def memory_stats() -> str:
    """Show statistics about stored conversation memories.

    Returns:
        Summary of memory counts by category and storage size
    """
    stats = _memory_store.stats()

    lines = [
        "Memory Stats:",
        f"- Total memories: {stats['total_memories']}",
    ]
    if stats["by_category"]:
        for cat, count in sorted(stats["by_category"].items()):
            lines.append(f"  • {cat}: {count}")
    lines.append(f"- Storage: {stats['storage_human']}")
    lines.append(f"- Embedding cache: {'✅' if stats['cache_exists'] else '❌ not built'}")

    return "\n".join(lines)


# ─── System Prompt / Memory Baseline ────────────────────────────────────────

SYSTEM_INSTRUCTION = """## Context Memory Protocol

You have access to a persistent conversation memory system through MCP tools.

**AT THE START OF EVERY NEW CONVERSATION:**
1. Call `recall_all` with a query relevant to the user's first message to load context
2. Review any returned memories for relevant decisions, preferences, and prior context
3. Acknowledge relevant memories naturally (e.g., "Based on our previous discussions...")

**DURING CONVERSATION:**
- When the user makes a **decision** → call `remember` with category="decision"
- When the user states a **preference** → call `remember` with category="preference"
- When a **task is completed** → call `remember` with category="task"
- When important **context** is shared → call `remember` with category="context"
- When a key **insight** emerges → call `remember` with category="insight"
- For anything else notable → call `remember` with category="note"

**BEST PRACTICES:**
- Be concise in memory content — store the essential fact, not the full conversation
- Use descriptive tags for easy filtering later
- Don't store trivial or transient information
- When in doubt about relevance, store it — memory is unlimited
- Use `recall` for memory-only search, `recall_all` for memory + blog content
"""


@mcp.tool()
def get_system_prompt() -> str:
    """Get the system instruction for context memory protocol.

    Call this at the start of a new conversation to load the memory protocol
    instructions and establish a baseline context.

    Returns:
        System instruction text for context memory behavior
    """
    stats = _memory_store.stats()
    summary = (
        f"\n\n---\nMemory state: {stats['total_memories']} memories stored"
    )
    if stats["by_category"]:
        cats = ", ".join(f"{cat}: {n}" for cat, n in sorted(stats["by_category"].items()))
        summary += f" ({cats})"

    return SYSTEM_INSTRUCTION + summary


# ─── Run Server ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="stdio")
