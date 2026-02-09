# CLAUDE.md - OpenRalph Codebase Guide

This document provides AI assistants with context about the OpenRalph codebase structure, conventions, and development workflows.

## Project Overview

OpenRalph is a self-contained CLI orchestrator for native agents that provides:
- Multi-tier configuration system (global + repo-local)
- Semantic memory index using SQLite + Ollama embeddings
- Git checkpoint/rollback integration
- Skill templates for guiding AI agents
- Tool installation helpers (pylsp, Node LSP servers, Playwright)

## Tech Stack

- **Python 3.10+** - Core language
- **Typer** - CLI framework with subcommand groups
- **Rich** - Terminal formatting and colored output
- **SQLite 3** - Embedded database for memory storage (with WAL mode)
- **Ollama** - External embeddings service (e.g., `nomic-embed-text`)

## Project Structure

```
openralph/
├── openralph/                      # Main package
│   ├── __init__.py
│   └── openralph_cli/              # CLI implementation
│       ├── cli.py                  # Typer app and command definitions
│       ├── settings.py             # TOML config loading with deep merge
│       ├── paths.py                # Runtime paths (.ralph directory)
│       ├── loop.py                 # Main orchestration loop
│       ├── git_manager.py          # Branch/commit/rollback helpers
│       ├── gitignore.py            # .gitignore managed block sync
│       ├── tooling.py              # Tool checks/installs, doctor report
│       ├── policies.py             # Test/install policy templates
│       ├── repo.py                 # Repository validation
│       └── memory/                 # Semantic indexing subsystem
│           ├── __init__.py
│           ├── db.py               # SQLite schema initialization
│           ├── embed.py            # Ollama embedding client
│           ├── index.py            # File chunking and indexing
│           ├── query.py            # Cosine similarity search
│           └── maintenance.py      # Database vacuum
├── docs/
│   ├── ARCHITECTURE.md             # High-level module overview
│   └── USAGE.md                    # Command reference
├── pyproject.toml                  # Build config and dependencies
├── README.md                       # Project overview
└── LICENSE                         # MIT License
```

## CLI Command Structure

```
openralph                           # Root Typer app
├── init <repo>                     # Initialize repository
├── doctor <repo>                   # Health check
├── run <repo> <prompt>             # Main orchestration loop
├── config
│   ├── init [--scope repo|global]  # Create starter config
│   └── show                        # Show merged config
├── gitignore
│   ├── show                        # Preview managed block
│   └── sync                        # Sync .gitignore block
├── proxy
│   ├── start                       # Start LLM proxy
│   ├── stop                        # Stop LLM proxy
│   └── status                      # Show proxy status
└── memory
    ├── index                       # Index repo files
    ├── query <q> [--k N]           # Semantic search
    └── vacuum                      # Optimize database
```

## Configuration System

**Precedence (highest to lowest):**
1. CLI flags
2. Environment variables (`OLLAMA_HOST`, `EMBED_MODEL`)
3. Repo config (`.openralph.toml`)
4. Global config (`~/.config/openralph/config.toml` or `%APPDATA%\openralph\config.toml`)
5. Built-in defaults

**Config sections:**
```toml
[ollama]
host = "http://localhost:11434"
embed_model = "nomic-embed-text"

[init]
install_tools = true
node_tooling = "local"          # "global" or "local"
create_venv = false
playwright = true

[loop]
max_iters = 10
rollback_on_gate_fail = false
max_gate_fails = 3

[memory]
k = 8                           # Top-k results for search
chunk_chars = 1800              # Max chunk size
chunk_overlap = 200             # Overlap between chunks
vacuum_warn_mb = 200            # Warn if DB exceeds this
exclude_dirs = [".git", "node_modules", ".venv", "venv", "dist", "build", ".ralph"]
include_exts = [".md", ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".json", ".yaml", ".toml"]
```

## Runtime Paths (.ralph directory)

The `.ralph/` directory contains all runtime artifacts:
- `.ralph/memory.sqlite3` - Semantic index database
- `.ralph/logs/iter-{n}.log` - Iteration logs from run loop
- `.ralph/node-tools/` - Local Node.js packages (if node_tooling=local)
- `.ralph/test-policy.md` - Test command policy
- `.ralph/install-policy.md` - Install command policy

## Code Conventions

### Style
- **Type hints** - Use `from __future__ import annotations` and type hints throughout
- **Frozen dataclasses** - Use for immutable config/result objects
- **No docstrings** - Code is self-documenting through clear naming
- **Private functions** - Prefix with underscore (`_deep_merge`, `_slugify`)

### Naming
- Functions: `snake_case`
- Classes: `PascalCase` (dataclasses for data, regular classes for behavior)
- Constants: `UPPER_SNAKE_CASE`
- Branch names: lowercase, hyphen-separated, max 40 chars

### Error Handling
- Raise `RuntimeError` for critical failures (e.g., proxy unavailable)
- Use `typer.Exit(code=1)` for CLI error reporting
- "Best-effort" operations silently continue on failure (e.g., memory indexing in loop)

### Platform Support
- Windows: check `os.name == "nt"` or `sys.platform.startswith("win")`
- Use `pathlib.Path` for all file paths
- Handle OS/arch detection for binary downloads (`platform.system()`, `platform.machine()`)

## Key Patterns

### Config Loading (settings.py)
```python
settings = OpenRalphSettings.load(repo_path)
# Merges global → repo → env vars with deep merge
```

### Memory System (memory/)
- Files are chunked (1800 chars, 200 overlap)
- Chunks embedded via Ollama API
- Stored as f32 binary blobs in SQLite
- Search uses cosine similarity (O(n) brute force)

### Orchestration Loop (loop.py)
1. Index repo into memory (best-effort)
2. Create/checkout git branch
3. For each iteration:
   - Query memory with prompt
   - Inject top hits into combined prompt
   - Call native agent with tool support
   - On gate pass: commit checkpoint, exit
   - On gate fail: optionally rollback after N failures
   - Reindex memory (best-effort)

### Git Integration (git_manager.py)
- Branch names prefixed with `openralph-`
- Checkpoint commits on gate pass
- Rollback to last checkpoint on repeated gate failures

## Development Workflow

### Installation
```bash
pip install -e .
```

### Initialize a Repository
```bash
openralph config init --scope global    # One-time global setup
openralph init . --node-tooling local   # Per-repo setup
openralph doctor .                      # Verify setup
```

### Run the Orchestration Loop
```bash
openralph run . "Implement feature X"
```

### Memory Operations
```bash
openralph memory index .
openralph memory query . "how do we handle authentication?"
openralph memory vacuum .
```

## Testing

No formal test suite exists yet. Testing is currently done through:
- Manual `openralph doctor .` health checks
- Integration testing via the run loop
- Config validation via `openralph config show .`

## Dependencies

From `pyproject.toml`:
- `typer>=0.12.0` - CLI framework
- `rich>=13.7.0` - Terminal formatting
- `tomli>=2.0.1` - TOML parsing (for Python <3.11)

External:
- **Ollama** - Must be running locally for embeddings
- **Git** - For branch/commit/rollback features
- **Node.js/npm** - Optional, for language server installs

## Important Files to Know

| File | Purpose |
|------|---------|
| `cli.py` | All CLI commands defined here |
| `settings.py` | Config loading, defaults, STARTER_TOML template |
| `loop.py` | Main run loop orchestration |
| `paths.py` | `Paths` dataclass for .ralph subdirectories |
| `memory/index.py` | File chunking and embedding |
| `memory/query.py` | Semantic search implementation |
| `git_manager.py` | Git operations (branch, commit, rollback) |

## Common Tasks for AI Assistants

### Adding a New CLI Command
1. Add command function in `cli.py`
2. Use `@app.command()` or `@{subapp}.command()` decorator
3. Follow existing patterns for repo validation and settings loading

### Adding a New Config Option
1. Add field to `OpenRalphSettings` dataclass in `settings.py`
2. Load from merged config in `OpenRalphSettings.load()`
3. Add to `as_dict()` method
4. Update `STARTER_TOML` with example

### Modifying Memory System
- Schema: `memory/db.py`
- Embedding logic: `memory/embed.py`
- Chunking: `memory/index.py`
- Search: `memory/query.py`

### Adding Tool Support
1. Add check function in `tooling.py`
2. Add to `doctor_report()` results
3. Add installation logic in `ensure_tools()`
