#!/usr/bin/env python3
"""
AIEngram - Cross-Platform Markdown Search & Memory CLI

Usage:
    aiengram "your query"                     # BM25 keyword search (default)
    aiengram "your query" -s                  # Semantic search (meaning-based)
    aiengram "your query" --hybrid            # Combined BM25 + semantic
    aiengram "your query" -n 5               # Limit to 5 results
    aiengram "your query" -f posts           # Filter: posts, outlines, prompts, kb, all
    aiengram --list                           # List all indexed files
    aiengram --stats                          # Show collection stats
    aiengram --build-index                    # Pre-build semantic index

Memory commands:
    aiengram --remember "Chose MIT license" -c decision -t license,legal
    aiengram --recall "architecture decisions"
    aiengram --memories                       # List all memories
    aiengram --memories -c decision           # Filter by category
    aiengram --forget m_20250617_a3f2         # Delete a memory by ID
    aiengram --memory-stats                   # Show memory statistics

Watch mode:
    aiengram --watch                          # Auto-reindex on file/memory changes
"""

import os
import re
import sys
import json
import time
import argparse
import math
import pickle
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter, defaultdict

# ─── Configuration ───────────────────────────────────────────────────────────

WORKSPACE_ROOT = Path(os.environ.get("AIENGRAM_ROOT", Path(__file__).parent))
EXTENSIONS = {".md"}
CACHE_FILE = WORKSPACE_ROOT / ".aiengram_cache.pkl"
MEMORY_FILE = WORKSPACE_ROOT / ".aiengram_memory.jsonl"
MEMORY_CACHE_FILE = WORKSPACE_ROOT / ".aiengram_memory_cache.pkl"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
CHUNK_SIZE = 500
MEMORY_CATEGORIES = {"decision", "insight", "context", "preference", "task", "note"}
FOLDERS = {
    "posts": "Blog Posts",
    "outlines": "Post Outlines",
    "prompts": None,  # root-level Prompt files
    "kb": None,       # root-level KB files
    "all": None,
}

# ─── Helpers ─────────────────────────────────────────────────────────────────

def get_files(filter_key="all"):
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
        # Also grab any other root-level .md files
        for f in WORKSPACE_ROOT.glob("*.md"):
            if f not in files:
                files.append(f)

    return sorted(set(files))


def read_file(path):
    """Read file content safely."""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def extract_title(content):
    """Extract the first heading from markdown content."""
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return None


def tokenize(text):
    """Simple tokenizer: lowercase, split on non-alphanumeric."""
    return re.findall(r"[a-z0-9]+", text.lower())


# ─── BM25 Search Engine ─────────────────────────────────────────────────────

class BM25:
    """Simple BM25 search implementation."""

    def __init__(self, k1=1.5, b=0.75):
        self.k1 = k1
        self.b = b
        self.docs = {}         # path -> content
        self.doc_tokens = {}   # path -> token list
        self.doc_lengths = {}  # path -> token count
        self.avg_dl = 0
        self.df = Counter()    # term -> doc frequency
        self.N = 0

    def index(self, files):
        """Index a list of files."""
        for f in files:
            content = read_file(f)
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

    def search(self, query, n=10):
        """Search indexed documents. Returns list of (path, score, snippet)."""
        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        scores = {}
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
            snippet = get_snippet(self.docs[path], query_tokens)
            results.append((path, score, snippet))

        return results


def get_snippet(content, query_tokens, context_chars=120):
    """Extract the most relevant snippet from content."""
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
        # Fall back to first non-empty, non-heading line
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and len(stripped) > 10:
                best_line = stripped
                break

    if len(best_line) > context_chars * 2:
        # Try to center on first match
        for token in query_tokens:
            idx = best_line.lower().find(token)
            if idx >= 0:
                start = max(0, idx - context_chars)
                end = min(len(best_line), idx + context_chars)
                return ("..." if start > 0 else "") + best_line[start:end] + ("..." if end < len(best_line) else "")
        best_line = best_line[:context_chars * 2] + "..."

    return best_line


# ─── Display ─────────────────────────────────────────────────────────────────

def relative_path(path):
    """Get path relative to workspace root."""
    try:
        return path.relative_to(WORKSPACE_ROOT)
    except ValueError:
        return path


def display_results(results, query):
    """Pretty-print search results."""
    if not results:
        print(f"\n  No results found for '{query}'\n")
        return

    print(f"\n  Found {len(results)} result(s) for '{query}':\n")
    print("  " + "─" * 70)

    for i, (path, score, snippet) in enumerate(results, 1):
        content = read_file(path)
        title = extract_title(content) or path.stem
        rel = relative_path(path)

        print(f"  {i}. {title}")
        print(f"     📄 {rel}")
        print(f"     Score: {score:.2f}")
        if snippet:
            # Highlight query terms
            highlighted = snippet
            for token in tokenize(query):
                pattern = re.compile(re.escape(token), re.IGNORECASE)
                highlighted = pattern.sub(lambda m: f"[{m.group()}]", highlighted)
            print(f"     ➤ {highlighted}")
        print()


def list_files(filter_key="all"):
    """List all indexed files."""
    files = get_files(filter_key)
    print(f"\n  📚 {len(files)} markdown file(s) in '{filter_key}':\n")
    for f in files:
        content = read_file(f)
        title = extract_title(content) or f.stem
        rel = relative_path(f)
        print(f"  • {title}")
        print(f"    {rel}")
    print()


def show_stats():
    """Show workspace statistics."""
    all_files = get_files("all")
    posts = get_files("posts")
    outlines = get_files("outlines")
    prompts = get_files("prompts")
    kb = get_files("kb")

    total_words = 0
    for f in all_files:
        content = read_file(f)
        total_words += len(content.split())

    print(f"\n  📊 AIEngram Workspace Stats")
    print(f"  " + "─" * 40)
    print(f"  Total files:    {len(all_files)}")
    print(f"  Blog posts:     {len(posts)}")
    print(f"  Post outlines:  {len(outlines)}")
    print(f"  Prompts:        {len(prompts)}")
    print(f"  Knowledge base: {len(kb)}")
    print(f"  Total words:    ~{total_words:,}")
    print()


# ─── Semantic Search Engine ──────────────────────────────────────────────────

class SemanticEngine:
    """Sentence-transformer semantic search with lazy model loading and disk cache."""

    def __init__(self):
        self._model = None
        self.chunks = []
        self.embeddings = None
        self.file_mtimes = {}
        self._loaded = False

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(EMBEDDING_MODEL)
        return self._model

    def _chunk_text(self, content, path):
        title = extract_title(content) or path.stem
        sections = re.split(r"(?m)^(#{1,3}\s+.+)$", content)
        raw_blocks = []
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

    def _load_cache(self):
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
        data = {
            "chunks": self.chunks,
            "embeddings": self.embeddings,
            "file_mtimes": self.file_mtimes,
        }
        with open(CACHE_FILE, "wb") as f:
            pickle.dump(data, f)

    def _get_stale_files(self, files):
        stale, fresh = [], []
        for f in files:
            key = str(f)
            current_mtime = f.stat().st_mtime
            if key in self.file_mtimes and self.file_mtimes[key] == current_mtime:
                fresh.append(f)
            else:
                stale.append(f)
        return stale, fresh

    def build_index(self, files, force=False):
        import numpy as np

        if not force:
            self._load_cache()

        stale, fresh = self._get_stale_files(files)
        current_paths = {str(f) for f in files}
        removed_paths = {c["path"] for c in self.chunks} - current_paths

        if not stale and not removed_paths:
            self._loaded = True
            return f"Index up to date. {len(self.chunks)} chunks across {len(files)} files."

        keep_chunks, keep_embeddings = [], []
        if self.embeddings is not None and self.chunks:
            for i, chunk in enumerate(self.chunks):
                if chunk["path"] not in {str(s) for s in stale} and chunk["path"] not in removed_paths:
                    keep_chunks.append(chunk)
                    keep_embeddings.append(self.embeddings[i])

        new_chunks = []
        new_mtimes = {}
        for f in stale:
            content = read_file(f)
            if content:
                new_chunks.extend(self._chunk_text(content, f))
                new_mtimes[str(f)] = f.stat().st_mtime

        new_embeddings = None
        if new_chunks:
            texts = [c["text"] for c in new_chunks]
            new_embeddings = self.model.encode(texts, show_progress_bar=True, convert_to_numpy=True)

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

    def search(self, query, files, n=10):
        import numpy as np

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

        seen_files = {}
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


def display_semantic_results(results, query):
    """Pretty-print semantic search results."""
    if not results:
        print(f"\n  No semantic results found for '{query}'\n")
        return

    print(f"\n  Found {len(results)} semantic result(s) for '{query}':\n")
    print("  " + "─" * 70)

    for i, r in enumerate(results, 1):
        rel = relative_path(r["path"])
        print(f"  {i}. {r['title']}")
        print(f"     📄 {rel}")
        print(f"     Similarity: {r['score']:.4f}")
        snippet = r["snippet"].replace("\n", " ").strip()
        if snippet:
            print(f"     ➤ {snippet[:240]}{'...' if len(snippet) > 240 else ''}")
        print()


def display_hybrid_results(bm25_results, semantic_results, query):
    """Merge BM25 and semantic results with reciprocal rank fusion."""
    RRF_K = 60  # standard RRF constant

    # Build score maps by file path
    rrf_scores = {}
    titles = {}
    snippets = {}

    for rank, (path, score, snippet) in enumerate(bm25_results, 1):
        key = str(path)
        rrf_scores[key] = rrf_scores.get(key, 0) + 1.0 / (RRF_K + rank)
        titles[key] = extract_title(read_file(path)) or path.stem
        snippets[key] = snippet

    for rank, r in enumerate(semantic_results, 1):
        key = str(r["path"])
        rrf_scores[key] = rrf_scores.get(key, 0) + 1.0 / (RRF_K + rank)
        if key not in titles:
            titles[key] = r["title"]
        if key not in snippets:
            snippets[key] = r["snippet"]

    ranked = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)

    if not ranked:
        print(f"\n  No results found for '{query}'\n")
        return

    print(f"\n  Found {len(ranked)} hybrid result(s) for '{query}' (BM25 + Semantic):\n")
    print("  " + "─" * 70)

    for i, (path_str, rrf_score) in enumerate(ranked[:10], 1):
        p = Path(path_str)
        rel = relative_path(p)
        title = titles.get(path_str, p.stem)
        snippet = snippets.get(path_str, "")
        # Check which engines found it
        in_bm25 = any(str(r[0]) == path_str for r in bm25_results)
        in_sem = any(str(r["path"]) == path_str for r in semantic_results)
        source = "🔤+🧠" if (in_bm25 and in_sem) else ("🔤" if in_bm25 else "🧠")

        print(f"  {i}. {title}  {source}")
        print(f"     📄 {rel}")
        print(f"     RRF Score: {rrf_score:.4f}")
        if snippet:
            snip = snippet.replace("\n", " ").strip()[:240]
            print(f"     ➤ {snip}{'...' if len(snippet) > 240 else ''}")
        print()


# ─── Context Memory Store ────────────────────────────────────────────────────

class MemoryStore:
    """Persistent conversation memory with semantic recall (CLI version)."""

    VALID_CATEGORIES = MEMORY_CATEGORIES

    def __init__(self, memory_file=MEMORY_FILE, cache_file=MEMORY_CACHE_FILE):
        self.memory_file = memory_file
        self.cache_file = cache_file
        self.memories = []
        self.embeddings = None
        self._loaded = False

    def _generate_id(self):
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        h = hashlib.md5(f"{ts}{len(self.memories)}".encode()).hexdigest()[:4]
        return f"m_{ts}_{h}"

    def _load(self):
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

    def _save_memory(self, entry):
        with open(self.memory_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _save_cache(self):
        data = {"embeddings": self.embeddings}
        with open(self.cache_file, "wb") as f:
            pickle.dump(data, f)

    def _rewrite_jsonl(self):
        with open(self.memory_file, "w", encoding="utf-8") as f:
            for m in self.memories:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")

    def _rebuild_embeddings(self, engine):
        import numpy as np
        if not self.memories:
            self.embeddings = np.array([])
            self._save_cache()
            return
        texts = [m["content"] for m in self.memories]
        self.embeddings = engine.model.encode(texts, show_progress_bar=True, convert_to_numpy=True)
        self._save_cache()

    def remember(self, content, category="note", tags=None, engine=None):
        import numpy as np
        self._load()
        if category not in self.VALID_CATEGORIES:
            category = "note"
        entry = {
            "id": self._generate_id(),
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "category": category,
            "content": content,
            "tags": tags or [],
            "source": "cli",
        }
        self.memories.append(entry)
        self._save_memory(entry)
        if engine:
            new_emb = engine.model.encode([content], show_progress_bar=False, convert_to_numpy=True)
            if self.embeddings is not None and len(self.embeddings) > 0:
                self.embeddings = np.vstack([self.embeddings, new_emb])
            else:
                self.embeddings = new_emb
            self._save_cache()
        return entry

    def recall(self, query, engine, n=5, category=None):
        import numpy as np
        self._load()
        if not self.memories:
            return []
        if self.embeddings is None or len(self.embeddings) != len(self.memories):
            self._rebuild_embeddings(engine)
        if self.embeddings is None or len(self.embeddings) == 0:
            return []
        query_emb = engine.model.encode([query], show_progress_bar=False, convert_to_numpy=True)[0]
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

    def list_memories(self, category=None, limit=20):
        self._load()
        filtered = self.memories
        if category:
            filtered = [m for m in filtered if m.get("category") == category]
        return list(reversed(filtered[-limit:]))

    def forget(self, memory_id):
        import numpy as np
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

    def stats(self):
        self._load()
        by_cat = {}
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


# ─── File Watcher ────────────────────────────────────────────────────────────

class FileWatcher:
    """Polls for markdown and memory file changes, triggers re-indexing."""

    def __init__(self, interval: float = 5.0):
        self.interval = interval
        self._snapshot: dict[str, float] = {}  # path -> mtime
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

    def run(self) -> None:
        """Blocking watch loop with console output."""
        engine = SemanticEngine()
        files = get_files("all")
        print("\n  🔨 Building initial index...")
        engine.build_index(files, force=True)

        self._snapshot = self._scan()
        self._memory_mtime = MEMORY_FILE.stat().st_mtime if MEMORY_FILE.exists() else 0.0

        print(f"  👀 Watching {len(self._snapshot)} files (poll every {self.interval}s)")
        print("  Press Ctrl+C to stop.\n")

        try:
            while True:
                time.sleep(self.interval)
                current = self._scan()

                if current != self._snapshot:
                    added = set(current) - set(self._snapshot)
                    removed = set(self._snapshot) - set(current)
                    changed = {p for p in current if p in self._snapshot and current[p] != self._snapshot[p]}
                    self._snapshot = current

                    parts = []
                    if added:
                        parts.append(f"{len(added)} added")
                    if removed:
                        parts.append(f"{len(removed)} removed")
                    if changed:
                        parts.append(f"{len(changed)} modified")
                    print(f"  📄 Changes detected: {', '.join(parts)}. Re-indexing...")

                    files = get_files("all")
                    result = engine.build_index(files)
                    print(f"  ✅ {result}")

                if self._check_memory():
                    print("  🧠 Memory file changed. Will reload on next access.")
        except KeyboardInterrupt:
            print("\n  ⏹  Watcher stopped.\n")


def display_memories(memories, label="memories"):
    """Pretty-print a list of memories."""
    if not memories:
        print(f"\n  No {label} found.\n")
        return
    print(f"\n  📝 {len(memories)} {label} (newest first):\n")
    print("  " + "─" * 70)
    for i, m in enumerate(memories, 1):
        content = m["content"][:200] + ("..." if len(m["content"]) > 200 else "")
        print(f"  {i}. [{m.get('category', 'note')}] {content}")
        print(f"     ID: {m['id']}  |  {m.get('timestamp', '')}")
        if m.get("tags"):
            print(f"     Tags: {', '.join(m['tags'])}")
        if "similarity" in m:
            print(f"     Similarity: {m['similarity']:.4f}")
        print()


def display_recall_results(results, query):
    """Pretty-print semantic memory recall results."""
    if not results:
        print(f"\n  No memories found for '{query}'\n")
        return
    print(f"\n  🧠 Found {len(results)} memory(ies) for '{query}':\n")
    print("  " + "─" * 70)
    for i, m in enumerate(results, 1):
        content = m["content"][:200] + ("..." if len(m["content"]) > 200 else "")
        print(f"  {i}. [{m.get('category', 'note')}] {content}")
        print(f"     ID: {m['id']}  |  Similarity: {m['similarity']:.4f}  |  {m.get('timestamp', '')}")
        if m.get("tags"):
            print(f"     Tags: {', '.join(m['tags'])}")
        print()


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="AIEngram - Cross-Platform Markdown Search & Memory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  aiengram "deep work"              BM25 keyword search (default)
  aiengram "deep work" -s           Semantic search (meaning-based)
  aiengram "deep work" --hybrid     Combined BM25 + semantic
  aiengram "paradox" -f posts       Search blog posts only
  aiengram "AI expertise" -n 3      Top 3 results
  aiengram --list                   List all files
  aiengram --list -f posts          List blog posts
  aiengram --stats                  Show stats
  aiengram --build-index            Pre-build semantic cache

Memory commands:
  aiengram --remember "Chose MIT license" -c decision -t license,legal
  aiengram --recall "architecture decisions"
  aiengram --memories                List all memories
  aiengram --memories -c decision    List memories by category
  aiengram --forget m_20250617_a3f2  Delete a memory by ID
  aiengram --memory-stats            Show memory statistics
        """
    )
    parser.add_argument("query", nargs="?", help="Search query")
    parser.add_argument("-n", "--num", type=int, default=10, help="Number of results (default: 10)")
    parser.add_argument("-f", "--filter", choices=["posts", "outlines", "prompts", "kb", "all"],
                        default="all", help="Filter by collection (default: all)")
    parser.add_argument("-s", "--semantic", action="store_true", help="Use semantic search (meaning-based)")
    parser.add_argument("--hybrid", action="store_true", help="Combine BM25 + semantic search")
    parser.add_argument("--list", action="store_true", help="List all indexed files")
    parser.add_argument("--stats", action="store_true", help="Show workspace statistics")
    parser.add_argument("--build-index", action="store_true", help="Pre-build semantic search index")
    # Memory commands
    parser.add_argument("--remember", metavar="TEXT", help="Store a new memory")
    parser.add_argument("-c", "--category", choices=sorted(MEMORY_CATEGORIES),
                        default="note", help="Memory category (default: note)")
    parser.add_argument("-t", "--tags", help="Comma-separated tags for the memory")
    parser.add_argument("--recall", metavar="QUERY", help="Semantic search over memories")
    parser.add_argument("--memories", action="store_true", help="List stored memories")
    parser.add_argument("--forget", metavar="ID", help="Delete a memory by ID")
    parser.add_argument("--memory-stats", action="store_true", help="Show memory statistics")
    # Watch mode
    parser.add_argument("--watch", action="store_true", help="Watch for file changes and auto-reindex")

    args = parser.parse_args()

    if args.watch:
        watcher = FileWatcher()
        watcher.run()
        return

    if args.stats:
        show_stats()
        return

    if args.list:
        list_files(args.filter)
        return

    if args.build_index:
        print("\n  🔨 Building semantic index...")
        engine = SemanticEngine()
        files = get_files(args.filter)
        result = engine.build_index(files, force=True)
        print(f"  ✅ {result}\n")
        return

    # ─── Memory commands ─────────────────────────────────────────────────
    mem = MemoryStore()

    if args.memory_stats:
        stats = mem.stats()
        print(f"\n  📝 Memory Stats")
        print(f"  " + "─" * 40)
        print(f"  Total memories: {stats['total_memories']}")
        if stats['by_category']:
            for cat, count in sorted(stats['by_category'].items()):
                print(f"    • {cat}: {count}")
        print(f"  Storage: {stats['storage_human']}")
        print(f"  Embedding cache: {'✅' if stats['cache_exists'] else '❌ not built'}")
        print()
        return

    if args.memories:
        memories = mem.list_memories(category=args.category if args.category != "note" else None, limit=args.num)
        label = f"memories in '{args.category}'" if args.category != "note" else "memories"
        display_memories(memories, label=label)
        return

    if args.remember:
        tags = [t.strip() for t in args.tags.split(",")] if args.tags else []
        engine = SemanticEngine()
        entry = mem.remember(args.remember, category=args.category, tags=tags, engine=engine)
        print(f"\n  ✅ Memory stored.")
        print(f"     ID: {entry['id']}")
        print(f"     Category: {entry['category']}")
        if entry['tags']:
            print(f"     Tags: {', '.join(entry['tags'])}")
        print(f"     Content: {entry['content'][:150]}{'...' if len(entry['content']) > 150 else ''}")
        print()
        return

    if args.recall:
        print("\n  🧠 Searching memories...")
        engine = SemanticEngine()
        cat = args.category if args.category != "note" else None
        results = mem.recall(args.recall, engine=engine, n=args.num, category=cat)
        display_recall_results(results, args.recall)
        return

    if args.forget:
        if mem.forget(args.forget):
            print(f"\n  ✅ Memory '{args.forget}' deleted.\n")
        else:
            print(f"\n  ❌ Memory '{args.forget}' not found.\n")
        return

    if not args.query:
        parser.print_help()
        return

    files = get_files(args.filter)

    if args.semantic:
        # Semantic-only search
        print("\n  🧠 Semantic search...")
        engine = SemanticEngine()
        results = engine.search(args.query, files, n=args.num)
        display_semantic_results(results, args.query)

    elif args.hybrid:
        # Hybrid: BM25 + Semantic with reciprocal rank fusion
        print("\n  🔤+🧠 Hybrid search...")
        bm25 = BM25()
        bm25.index(files)
        bm25_results = bm25.search(args.query, n=args.num)

        sem = SemanticEngine()
        sem_results = sem.search(args.query, files, n=args.num)

        display_hybrid_results(bm25_results, sem_results, args.query)

    else:
        # Default BM25 keyword search
        engine = BM25()
        engine.index(files)
        results = engine.search(args.query, n=args.num)
        display_results(results, args.query)


if __name__ == "__main__":
    main()
