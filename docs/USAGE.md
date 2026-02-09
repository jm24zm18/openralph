# Usage

## Install (pipx)

```bash
pipx install --force /home/justin/openralph
```

## Config

Precedence (highest → lowest):
1) CLI flags
2) Environment variables
3) Repo config (`.openralph.toml`)
4) Global config (`~/.config/openralph/config.toml` or `%APPDATA%\\openralph\\config.toml`)
5) Built-in defaults

OpenRalph also auto-loads repo-local `.env` values (for example `BRAVE_API_KEY`)
before settings are resolved.

Create starter config:

```bash
openralph config init --scope global
openralph config init --scope repo
openralph config show .
openralph config show --repo .
```

## UI Modes

Global UI controls apply to all commands:

```bash
openralph --plain doctor .
openralph --ui-style minimal run . "Implement X"
openralph --ui-style signature run . "Implement X"
```

- `--plain`: force plain output (no Rich panels/live dashboard).
- `--ui-style minimal`: lower-ornament rendering for tighter terminals.
- `--ui-style signature`: full visual style with richer panels and live run telemetry.

You can also disable rich UI using environment variable:

```bash
OPENRALPH_NO_UI=1 openralph run . "Implement X"
```

## Init

```bash
openralph init . --node-tooling local --create-venv
```

Init will:
- create `.ralph/` runtime folder
- initialize memory DB
- sync `.gitignore` managed block
- start proxy (if enabled and auto-start is true)

## Doctor

```bash
openralph doctor .
```

When `proxy.enabled = true` but proxy is stopped, doctor reports
`proxy: enabled but not running` (non-fatal) with a start hint.

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

## Bugs

OpenRalph writes extracted issues to `.ralph/issues.json` and mirrors a
human-friendly index in `docs/bugs/index.md`.

Create a bug folder:

```bash
openralph bug new . "Title" --description "Short description"
```

## Proxy

```bash
openralph proxy status .
openralph proxy start .
openralph proxy stop .
```

To enable per-request proxy logs:

```toml
[proxy]
log_requests = true
```

To enable browser preflight support for `/v1/*`:

```toml
[proxy]
cors_enabled = true
cors_allow_origin = "*"
```

## Run Status Semantics

- `success`: run completed and tool errors are within budget.
- `success_with_warnings`: run completed but tool errors exceeded `loop.max_tool_errors`.
- `partial` / `failed` / `blocked`: run did not complete cleanly.

Tune warning threshold:

```toml
[loop]
max_tool_errors = 0
```
