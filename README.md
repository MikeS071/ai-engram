# AI Engram

Semantic search and persistent conversation memory for markdown workspaces — built as an [MCP](https://modelcontextprotocol.io/) server.

AI Engram gives your AI assistant long-term memory and deep search over your markdown content. It combines BM25 keyword search with sentence-transformer semantic search, plus a persistent memory system that stores decisions, preferences, and context across conversations.

---

## Features

- **BM25 keyword search** — fast, TF-IDF style ranking with configurable `k1`/`b` parameters
- **Semantic search** — meaning-based retrieval using `all-MiniLM-L6-v2` sentence-transformers
- **Hybrid search** — reciprocal rank fusion (RRF) combining BM25 + semantic results
- **Persistent conversation memory** — stores decisions, preferences, insights, tasks, context, notes across sessions
- **Semantic memory recall** — find relevant memories by meaning, not just keywords
- **Cross-search** — query both memory and blog content in a single RRF-fused call
- **File watcher** — daemon thread polls for markdown changes every 5 seconds, auto-reindexes
- **Collection filtering** — scope searches to posts, outlines, prompts, or knowledge base
- **Disk-cached embeddings** — pickle-based cache avoids recomputing embeddings on restart
- **Standalone CLI** — full-featured command-line interface independent of MCP
- **Social Scheduler (new)** — automated LinkedIn/X scheduling and publishing with Telegram-first approvals, safety gates, and JSONL storage

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    MCP Client                       │
│            (VS Code, Claude Desktop, etc.)          │
└──────────────────────┬──────────────────────────────┘
                       │ stdio (JSON-RPC)
┌──────────────────────▼──────────────────────────────┐
│               aiengram_mcp.py                       │
│                                                     │
│  ┌─────────────┐  ┌────────────────┐  ┌──────────┐ │
│  │    BM25      │  │ SemanticEngine │  │ Memory   │ │
│  │  (keyword)   │  │ (embeddings)   │  │  Store   │ │
│  └──────┬──────┘  └───────┬────────┘  └────┬─────┘ │
│         │                 │                 │       │
│         │    ┌────────────▼─────────┐       │       │
│         │    │   Embedding Cache    │       │       │
│         │    │  (.aiengram_cache.pkl)│       │       │
│         │    └──────────────────────┘       │       │
│         │                                   │       │
│  ┌──────▼───────────────────────────────────▼─────┐ │
│  │              FileWatcher (daemon)              │ │
│  │         polls .md changes every 5s             │ │
│  └────────────────────────────────────────────────┘ │
│                                                     │
│  13 MCP Tools exposed via FastMCP                   │
└─────────────────────────────────────────────────────┘
         │                              │
    ┌────▼────┐                ┌────────▼──────────┐
    │ .md     │                │ .aiengram_memory   │
    │ files   │                │     .jsonl         │
    └─────────┘                └───────────────────┘
```

### Core Components

**BM25 Engine** — Custom Okapi BM25 implementation (`k1=1.5`, `b=0.75`). Tokenizes markdown content, builds an inverted index in memory, and ranks documents by term frequency with length normalization. Includes snippet extraction that highlights matching terms.

**SemanticEngine** — Wraps `sentence-transformers` with the `all-MiniLM-L6-v2` model. Lazy-loads the model on first use to minimize startup time. Encodes documents into 384-dimensional vectors and ranks by cosine similarity. Embeddings are cached to disk (`.aiengram_cache.pkl`) keyed by file path + modification time, so only changed files get re-embedded.

**MemoryStore** — Persistent JSONL-based memory system. Each memory has an ID (`m_YYYYMMDDHHMMSS_XXXX`), category, content, optional tags, and timestamp. Supports semantic recall over memories via a separate embedding cache (`.aiengram_memory_cache.pkl`). Cross-search via `recall_all` combines memory recall with blog semantic search using reciprocal rank fusion (RRF, `k=60`).

**FileWatcher** — Daemon thread that polls the workspace every 5 seconds. Detects new, modified, or deleted `.md` files and triggers semantic re-indexing. Also watches the memory JSONL file and sets a lazy-reload flag on the MemoryStore when external changes are detected.

**MCP Transport** — Uses `mcp.server.fastmcp.FastMCP` with `stdio` transport. Async tools use `anyio.to_thread.run_sync` to offload CPU-intensive embedding work without blocking the event loop. Stdout is redirected to stderr during numpy/sentence-transformers imports to prevent JSON-RPC stream corruption.

---

## MCP Tools

### Content Search

| Tool | Description |
|------|-------------|
| `search_blog` | BM25 keyword search with relevance scoring and snippet extraction |
| `semantic_search_blog` | Meaning-based search using sentence-transformer embeddings |
| `build_index` | Pre-build or force-refresh the semantic embedding cache |
| `list_blog_files` | List all markdown files, filterable by collection |
| `blog_stats` | File counts and word totals across all collections |
| `read_blog_file` | Read full content of any markdown file by path (with fuzzy matching) |

### Conversation Memory

| Tool | Description |
|------|-------------|
| `remember` | Store a memory with category and optional tags |
| `recall` | Semantic search across stored memories |
| `recall_all` | Cross-search memories AND blog content via RRF fusion |
| `list_memories` | Browse memories by category, newest first |
| `forget` | Delete a specific memory by ID |
| `memory_stats` | Memory counts by category and storage size |
| `get_system_prompt` | Load the context memory protocol instructions |

### Memory Categories

| Category | Use Case |
|----------|----------|
| `decision` | Architectural choices, workflow rules, rejected approaches |
| `preference` | Tool choices, formatting styles, workflow preferences |
| `insight` | Key learnings, patterns discovered, aha moments |
| `context` | Background information, project state, environment details |
| `task` | Completed work, milestones, deliverables |
| `note` | General purpose — anything worth persisting |

---

## Repository Structure

This repo contains only the AI Engram source code and configuration. Blog content (posts, outlines, prompts, knowledge base) is excluded via `.gitignore` and lives locally in the workspace.

```
aiengram_mcp.py              # MCP server — search engines, memory, 13 tools, file watcher
aiengram.py                  # Standalone CLI — same engines with argparse interface
pyproject.toml               # Project metadata, dependencies, entry points
README.md                    # This file
.gitignore                   # Excludes blog content, caches, media
.github/
  copilot-instructions.md    # GitHub Copilot session initialization rules
```

### Generated at runtime (not tracked)

```
.aiengram_cache.pkl          # Semantic embedding cache (blog content)
.aiengram_memory.jsonl       # Persistent memory storage
.aiengram_memory_cache.pkl   # Semantic embedding cache (memories)
__pycache__/                 # Python bytecode
```

---

## Requirements

- Python >= 3.10
- [uv](https://docs.astral.sh/uv/) (recommended package manager)

### Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `sentence-transformers` | >= 3.0 | Semantic embeddings (`all-MiniLM-L6-v2`) |
| `torch` | >= 2.0 | Tensor backend for sentence-transformers |
| `numpy` | >= 1.24 | Vector math for cosine similarity |
| `mcp` | >= 1.0 | Model Context Protocol server framework (optional) |

---

## Installation

```bash
# Clone the repo
git clone https://github.com/MikeS071/ai-engram.git
cd ai-engram

# Install with MCP support
uv pip install -e ".[mcp]"

# Or without MCP (CLI-only)
uv pip install -e .
```

---

## Usage

### MCP Server

Run directly:

```bash
uv run aiengram_mcp.py
```

Or add to your MCP client configuration (e.g. VS Code `settings.json`):

```json
{
  "mcp": {
    "servers": {
      "aiengram": {
        "command": "uv",
        "args": ["run", "aiengram_mcp.py"],
        "cwd": "/path/to/your/markdown/workspace"
      }
    }
  }
}
```

Point `cwd` at any directory containing markdown files. AI Engram auto-discovers content in `Blog Posts/`, `Post Outlines/`, `Prompts/`, and knowledge base files matching `KB - *.md`.

### CLI

```bash
# BM25 keyword search (default)
aiengram "deep work"

# Semantic search (meaning-based)
aiengram "deep work" -s

# Hybrid search (BM25 + semantic, RRF-fused)
aiengram "deep work" --hybrid

# Filter by collection
aiengram "paradox" -f posts

# Limit results
aiengram "AI expertise" -n 3

# List all files
aiengram --list

# Show workspace stats
aiengram --stats

# Pre-build semantic cache
aiengram --build-index
```

### Memory Commands (CLI)

```bash
# Store a decision
aiengram --remember "Chose MIT license" -c decision -t license,legal

# Recall relevant memories
aiengram --recall "architecture decisions"

# List all memories
aiengram --memories

# List by category
aiengram --memories -c decision

# Delete a memory
aiengram --forget m_20250617_a3f2

# Memory stats
aiengram --memory-stats
```

### File Watcher (CLI)

```bash
# Watch for markdown changes and auto-reindex
aiengram --watch
```

### Social Scheduler (CLI)

```bash
# Initialize scheduler runtime files
./.venv/bin/python -m social_scheduler.main init

# Create campaign from blog markdown
./.venv/bin/python -m social_scheduler.main campaign-create 'Blog Posts/<file>.md' --audience-timezone 'America/New_York'

# Run worker loop in dry-run mode
./.venv/bin/python -m social_scheduler.main worker-daemon --interval-seconds 60 --dry-run true

# Start Telegram bot (polling mode)
./.venv/bin/python -m social_scheduler.main telegram-run
```

Detailed scheduler setup and runbook:

- `social_scheduler/README.md`
- `.env.social-scheduler.example`

---

## How It Works

### Search Pipeline

1. **File Discovery** — Scans the workspace root for `.md` files matching known collection patterns (`Blog Posts/`, `Post Outlines/`, `Prompt - *.md`, `KB - *.md`)
2. **Content Extraction** — Reads markdown with UTF-8 encoding, extracts title from first `#` heading or filename
3. **BM25 Indexing** — Tokenizes content (lowercased, alphanumeric), builds term frequency maps and inverted index
4. **Semantic Encoding** — Sentence-transformer encodes full document text into 384-dim vectors, cached to disk keyed by `(path, mtime)`
5. **Query Processing** — BM25 scores via Okapi formula; semantic via cosine similarity against query embedding
6. **Hybrid Fusion** — When both engines run, results merge via reciprocal rank fusion: $\text{RRF}(d) = \sum_{r \in R} \frac{1}{k + \text{rank}_r(d)}$ with $k = 60$

### Memory Pipeline

1. **Store** — Appends JSON entry to `.aiengram_memory.jsonl` with unique timestamped ID
2. **Embed** — Computes sentence embedding for the memory content, cached in `.aiengram_memory_cache.pkl`
3. **Recall** — Encodes query, computes cosine similarity against all memory embeddings, returns top-N
4. **Cross-recall** — Runs memory recall AND blog semantic search in parallel, fuses with RRF

---

## Roadmap

- [ ] **Single installation script** — one-command setup that installs dependencies, builds the index, and configures the MCP server
- [ ] **Docker deployment** — containerized deployment with MCP server, embedding model, and file watcher
- [ ] **Memory search improvements** — full-text search, tag-based filtering, and date-range queries
- [ ] **Cross-conversation summaries** — auto-summarize related memory clusters into condensed session summaries

---

## License

MIT
