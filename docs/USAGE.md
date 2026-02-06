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
- sync `.gitignore` managed block
- start proxy (if enabled and auto-start is true)

## Doctor

```bash
openralph doctor .
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

## Proxy

```bash
openralph proxy status .
openralph proxy start .
openralph proxy stop .
```
