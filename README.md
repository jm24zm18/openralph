# OpenRalph

OpenRalph is a self-contained CLI that orchestrates **OpenCode** for agent-driven repo work, with:

- Bundled **OpenCode** binary per repo (`.ralph/bin/opencode`)
- Global + repo-local **OpenRalph config** (`.openralph.toml`, `~/.config/openralph/config.toml`)
- Schema-correct **OpenCode config** (`opencode.json`)
- OpenCode **skills** under `.opencode/skills/*/SKILL.md`
- Gitignore managed block (`openralph gitignore sync`)
- Per-project **memory index** in SQLite using **Ollama** embeddings (e.g. `nomic-embed-text`)
- Optional tool installs: pylsp, node language servers, Playwright

## Install (dev)

```bash
pip install -e .
```

## Quickstart

```bash
openralph config init --scope global
openralph init . --node-tooling local --create-venv
openralph doctor .
```

## Run loop (scaffold)

```bash
openralph run . "Implement X. Follow skills and gates."
```

See `docs/USAGE.md` and `docs/ARCHITECTURE.md`.
