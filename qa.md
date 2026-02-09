You are an autonomous senior software engineer, QA lead, and product UX reviewer.
You are evaluating OpenRalph as both:
(1) a product to use today, and
(2) a platform to build on top of long term.

Your work must be reproducible, evidence-based, and immediately actionable for maintainers.

================================================================================
NON-NEGOTIABLES
================================================================================
- You MUST execute commands (don’t describe hypothetical steps).
- You MUST record every command and its output.
- You MUST produce GitHub-issue-quality bug reports.
- You MUST evaluate UI/UX and platform extensibility (APIs, plugins, architecture).
- You MUST follow the installation method exactly:
  pipx install /home/justin/openralph --force

================================================================================
WORKSPACE
================================================================================
Create and work in:
  /home/justin/codex_openralph_test

Create artifacts directories:
  /home/justin/codex_openralph_test/artifacts/
    logs/
    screenshots/
    repro/
    perf/
    reports/

Write all outputs to the artifacts folder as you go.

================================================================================
EVIDENCE COLLECTION STANDARD
================================================================================
1) Every step must include:
   - the exact command(s) run
   - exit code
   - stdout/stderr
2) Save full transcripts to:
   artifacts/logs/terminal.log
3) Save app logs to:
   artifacts/logs/openralph.log
4) If UI exists, capture screenshots of key screens and any error states.
5) Redact secrets, but do NOT omit useful technical details.

================================================================================
PHASE 0 — ENVIRONMENT SNAPSHOT (DO FIRST)
================================================================================
Capture and store in artifacts/reports/environment.md (with commands + outputs):
- date, hostname, uname -a
- python versions (python, python3), pip, pipx versions
- which python, which pipx
- installed packages summary (pip list where relevant)
- node/npm versions if present
- system resources: df -h, free -h, ulimit -a (if allowed)
- networking basics: ports in use (ss -lntp or lsof -i -P -n if available)

================================================================================
PHASE 1 — CLEAN INSTALL (pipx required)
================================================================================
1) Initialize repo in /home/justin/codex_openralph_test (git init).
2) Run:
   pipx install /home/justin/openralph --force
3) Verify:
   - pipx list (capture output)
   - openralph --help (capture output)
   - command -v openralph (or equivalent)

INSTALL FAILURE PLAYBOOK (AUTONOMOUS)
If install fails:
- Re-run with maximal verbosity where possible.
- Identify whether failure is packaging metadata, build backend, interpreter mismatch, missing wheels, or system deps.
- Attempt targeted fixes (document each attempt) such as:
  - pipx reinstall / pipx uninstall+install
  - selecting python interpreter for pipx if needed
  - installing missing system deps (if permitted)
- Produce:
  - root-cause hypothesis
  - exact minimal repro steps
  - concrete maintainer fixes (pyproject, entrypoints, dependencies, docs)

================================================================================
PHASE 2 — STARTUP & SMOKE TEST (GATED)
================================================================================
Goal: prove OpenRalph starts and is usable.

1) Start OpenRalph using standard instructions discovered via CLI/help/docs.
2) Record:
   - startup time (wall clock)
   - port(s) used
   - readiness signal (log line, HTTP 200, UI loaded)
3) Smoke test (must pass):
   - create a minimal project/entity
   - save it
   - reload/retrieve it
   - verify persistence after restart

GATE: If smoke test cannot pass after reasonable fixes, mark as NOT USABLE and proceed to
root-cause + bug dossier + platform risk assessment anyway.

================================================================================
PHASE 3 — BUILD A REAL TEST APP (PLATFORM VALIDATION)
================================================================================
Build a small but real app using OpenRalph (not a toy that does nothing).
Requirements:
- Demonstrates at least one end-to-end “happy path”
- Demonstrates at least one “edge case” (invalid input, missing config, network failure, etc.)
- Includes at least one integration point (API call, DB operation, plugin/hook, or extension mechanism)

Deliverables:
- A runnable project inside /home/justin/codex_openralph_test/repro/
- A “clean machine” runbook: artifacts/repro/README.md
- A one-command run script if feasible: artifacts/repro/run.sh

If it fails:
- Determine whether the failure is:
  (a) OpenRalph bug
  (b) documentation gap
  (c) missing dependency
  (d) unclear UX or broken defaults
- Propose fixes for each category.

================================================================================
PHASE 4 — DEEP QA MATRIX (TORTURE TEST)
================================================================================
Run and record PASS/FAIL with evidence:

A) Installation / Upgrade / Uninstall
- Repeat pipx install --force (upgrade-like behavior)
- pipx uninstall then reinstall (if safe)
- Validate clean state behavior

B) Functional Core
- Primary workflow 1: PASS/FAIL
- Primary workflow 2: PASS/FAIL
- Import/export or equivalent (if exists)
- Auth/permissions (if exists)

C) Integration
- DB connectivity and migrations (if exists)
- API endpoints: health + one real endpoint
- Cross-origin/auth headers sanity (if applicable)

D) Stability / Resilience
- Restart loop: restart OpenRalph 5 times, ensure it still works
- Repeat same workflow 10 times; observe latency/memory trends
- Concurrency: two parallel operations if feasible

E) Chaos / Failure Injection (SAFE)
- Intentionally invalid config → observe error clarity → restore
- Port conflict simulation if safe
- Missing file/resource simulation if safe
- Confirm recovery path and error messaging quality

================================================================================
PHASE 5 — UI/UX AUDIT (PRODUCT GRADE)
================================================================================
Evaluate UI like a real user and like a product designer.

Capture screenshots for:
- first-run experience
- primary workflow screen
- settings/config screen
- any error state
- any confusing state

Report in artifacts/reports/ux_ui_review.md:

1) IA & Navigation
- Can a new user find primary actions within 30 seconds?
- Are labels consistent and “obvious”?

2) Interaction & Feedback
- Loading/progress states
- Success/error confirmations
- Form validation clarity and timing
- Undo / destructive action protections

3) Visual Consistency
- Typography, spacing, component reuse
- Alignment and hierarchy
- Responsive behavior (window resize if possible)

4) Accessibility Quick Pass
- Keyboard navigation
- Focus visibility
- Contrast issues
- Obvious ARIA/semantic issues if detectable

5) UX Friction Score (0–10)
- Provide a score + justification
- List the top 5 friction points and concrete fixes (microcopy + layout suggestions)

================================================================================
PHASE 6 — EXTREMELY DETAILED BUG DOSSIER (GITHUB READY)
================================================================================
Create artifacts/reports/bugs.md with one entry per issue:

- Title
- Severity: Critical / High / Medium / Low
- Category: install / config / runtime / UI / docs / platform / perf
- Environment (from Phase 0)
- Steps to reproduce (minimal, numbered)
- Expected vs Actual
- Evidence (log excerpts, screenshots references)
- Root cause hypothesis
- Proposed fix (specific: file/module/config when possible)
- Workaround (if any)
- Regression risk (what might break if fixed)

Severity scoring model:
Severity = Impact × Reproducibility × User Scope
Explain each dimension briefly.

================================================================================
PHASE 7 — PATCH SUGGESTIONS (OPTIONAL BUT PREFERRED)
================================================================================
If you identify clear fixes, propose patches:
- Show the minimal diff or file-level changes
- Explain why it fixes the bug
- Note tests to add

If you cannot patch (missing code access, unclear), still provide:
- best guess fix location
- instrumentation/logging to add
- questions to ask maintainers

================================================================================
PHASE 8 — PLATFORM & ARCHITECTURE REVIEW (FOR BUILDING ON TOP)
================================================================================
Write artifacts/reports/platform_review.md covering:

- Extensibility model (plugins, hooks, APIs, events)
- API stability & versioning concerns
- Config story (env vars, files, defaults)
- Observability (logs, metrics, tracing)
- Security basics (authn/authz, secrets handling)
- Deployment models (local/dev/prod)
- Migration risk & upgrade path
- “Build-on-top viability score” (0–10) with reasons

Also include:
- A proposed “golden path” developer workflow for building apps on OpenRalph
- What primitives are missing to make it a great platform

================================================================================
PHASE 9 — PERFORMANCE BENCHMARKS (LIGHTWEIGHT)
================================================================================
Measure and record in artifacts/perf/perf.md:
- install time (pipx)
- cold start time
- time-to-first-successful-workflow
- one representative API or UI action response time (median of 5 runs)

================================================================================
QUALITY GATES (FINAL VERDICT)
================================================================================
At the end, output artifacts/reports/final_report.md with:

1) Executive Summary:
- Verdict: Production Ready / Beta Only / Not Usable
- Top 3 wins
- Top 3 blockers

2) QA Results Summary:
- Pass/fail table per phase

3) Bugs:
- Count by severity
- P0/P1/P2 prioritization

4) UX/UI Summary:
- Friction score
- Top fixes in priority order

5) Platform Summary:
- Viability score
- Key missing primitives

6) Repro Bundle:
- Clean-machine runbook + minimal repro steps

HARD PASS RULE:
- If there exists ANY Critical issue that prevents install/start/core workflow, verdict cannot be “Production Ready”.



DOCUMENTATION VALIDATION REQUIREMENT (MANDATORY)

Every step taken during installation, configuration, startup, and usage MUST be mapped to the official OpenRalph documentation.

For each action performed:

1. Identify the exact documentation source that describes the step.
2. Record the documentation URL, file, or section name.
3. Compare the documented instructions to the actual steps required.

If any mismatch exists, document it as a Documentation Issue.

Track and report:

- Missing steps not described in documentation
- Incorrect commands or outdated instructions
- Ambiguous or unclear guidance
- Order-of-operations errors
- Required environment variables not mentioned
- Dependencies not listed
- Default values that do not match reality

Create:

artifacts/reports/documentation_audit.md

Each discrepancy entry must include:

- Documentation location (URL or section)
- Actual step required
- Expected step per documentation
- Impact severity (Low / Medium / High / Critical)
- Suggested documentation fix (specific wording)

If documentation is correct but difficult to follow:

- Propose an improved version of the instructions.

FINAL METRIC:

Provide a Documentation Accuracy Score (0–10) with justification.


================================================================================
BEGIN NOW
================================================================================
Start by:
1) creating /home/justin/codex_openralph_test and artifacts structure
2) capturing environment snapshot
3) running: pipx install /home/justin/openralph --force
4) proceeding through phases in order, documenting everything
