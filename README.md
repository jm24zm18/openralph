# OpenRalph [![Release](https://github.com/jm24zm18/openralph/actions/workflows/release.yml/badge.svg)](https://github.com/jm24zm18/openralph/actions/workflows/release.yml)

OpenRalph is a self-contained CLI that orchestrates native agents for repo work, with:

- Global + repo-local **OpenRalph config** (`.openralph.toml`, `~/.config/openralph/config.toml`)
- Gitignore managed block (`openralph gitignore sync`)
- Per-project **memory index** in SQLite using **Ollama** embeddings (e.g. `nomic-embed-text`)
- Bug index generated in `docs/bugs/index.md` from `.ralph/issues.json`
- Optional tool installs: pylsp, node language servers, Playwright

## Install (dev)

```bash
pip install -e .
```

## Install (pipx)

```bash
pipx install --force /home/justin/openralph
```

OpenRalph auto-loads a repo-local `.env` file (if present) before reading settings.
Example:

```bash
BRAVE_API_KEY=your_key_here
OPENRALPH_SEARCH_PROVIDER=brave
```

## Quickstart

```bash
openralph config init --scope global
openralph init . --node-tooling local --create-venv
openralph doctor .
openralph --version
```

## Run loop (scaffold)

```bash
openralph run . "Implement X. Follow skills and gates."
```

See `docs/USAGE.md` and `docs/ARCHITECTURE.md`.
