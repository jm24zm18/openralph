# Test policy

## Required actions
1. You MUST execute the test command, not just identify it.
2. Capture and report the full output.

## Common test commands
- Node.js: `npm test` or `yarn test`
- Python: `pytest` or `python -m pytest`
- Rust: `cargo test`
- Go: `go test ./...`
- Make: `make test`

## Gate decision
- Tests executed and passed -> PASS
- Tests executed and failed -> FAIL
- Test command exists but NOT executed -> FAIL
- No test infrastructure at all -> PASS (with recommendation)
