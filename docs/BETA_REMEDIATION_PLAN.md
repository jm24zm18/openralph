# Beta Remediation Plan

## Scope
Consolidated fixes for issues reported in:
- `bugs.md`
- `OPENRALPH_BETA_REPORT.md`
- `OPENRALPH_BETA_EVALUATION.md`
- `test_results.md`
- `ux_ui_review.md`

## Workstreams
- [x] Config load/validation UX hardening
- [x] Run outcome artifact consistency + warning tier
- [x] Smoke/runtime coherence improvements
- [x] Proxy OPTIONS/CORS support + doctor proxy semantics
- [x] Planner output completeness hardening
- [x] Long-run heartbeat output
- [x] Regression tests for new behavior
- [x] Usage docs updates

## Implementation Notes
1. Config parsing now raises structured field-aware errors (`ConfigLoadError`) with file and key path context.
2. Run status now supports `success_with_warnings` and persists `tool_errors` + `max_tool_errors` in `.ralph/RUN_STATUS.json` and `.ralph/RUN_SUMMARY.md`.
3. `loop.max_tool_errors` controls pass-with-warnings downgrade behavior.
4. Smoke checks now skip test-runner-only deps and validate README python script references.
5. Proxy supports optional CORS preflight/headers via `proxy.cors_enabled` and `proxy.cors_allow_origin`.
6. Doctor treats `proxy.enabled=true` + stopped proxy as non-fatal (`enabled but not running`), while stale PID states remain failures.
7. Planner validation now enforces feature path bounds and non-trivial required file content.
8. Agent runner emits periodic heartbeat lines during long operations.

## Validation Checklist
- [ ] `python3 -m pytest -q`
- [ ] Manual check: malformed `.openralph.toml` reports concise config error
- [ ] Manual check: `openralph run` with tool errors yields warning-tier status
- [ ] Manual check: proxy `OPTIONS /v1/models` responds with CORS when enabled
