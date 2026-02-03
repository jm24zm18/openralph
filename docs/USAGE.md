# Usage

## Config

Precedence (highest → lowest):
1) CLI flags
2) Environment variables
3) Repo config (`.openralph.toml`)
4) Global config (`~/.config/openralph/config.toml` or `%APPDATA%\\openralph\\config.toml`)
5) Built-in defaults

Create starter config:

```bash
openralph config init --scope global
openralph config init --scope repo
openralph config show .
```

## Init

```bash
openralph init . --node-tooling local --create-venv
```

Init will:
- create `.ralph/` runtime folder
- initialize memory DB
- create `opencode.json`
- create `.opencode/skills/...`
- sync `.gitignore` managed block
- install bundled OpenCode if missing (default)

## Doctor

```bash
openralph doctor .
```

## Run Loop

```bash
openralph run . "Implement X"
```

Key behaviors:
- Multi-stage loop: builder → test → review each iteration.
- Gate is determined by `Gate: PASS|FAIL` in `.ralph/TEST_REPORT.md`.
- Loop stops only when `.ralph/DONE` exists and the gate is PASS.
- Human handoff: `.ralph/HUMAN_REQUEST.md` + `.ralph/HUMAN_RESPONSE.md`.

PRD Q&A and refresh options:
```bash
openralph run . "Implement X" --prd-qa-mode handoff
openralph run . "Implement X" --prd-qa-mode auto-then-handoff
openralph run . "Implement X" --prd-refresh-every 5 --prd-refresh-mode ask
```

## Gitignore

```bash
openralph gitignore show .
openralph gitignore sync .
```

## Memory

```bash
openralph memory index .
openralph memory query . "how do we run tests?"
openralph memory vacuum .
```

## OpenCode

```bash
openralph opencode where .
openralph opencode install .
openralph opencode version .
```
