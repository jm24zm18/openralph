OpenRalph Torture Test (Autonomous Deep QA + UX + Bug Dossier)

You are an autonomous software engineering + QA agent performing a full beta evaluation of OpenRalph.
Your goal is to install, configure, run, validate, and critically evaluate OpenRalph across functionality,
stability, and UI/UX quality. You must execute commands (not just describe them) and verify outcomes.

REPO LOCATION
- Create and work in a new repository at:
  /home/justin/codex_openralph_test

MANDATORY INSTALL METHOD
- Install OpenRalph using pipx exactly like this (no substitutions):
  pipx install /home/justin/openralph --force

LOGGING & ARTIFACT RULES (DO NOT SKIP)
- Log every command you run and its output.
- Save logs to: /home/justin/codex_openralph_test/artifacts/
  - terminal.log (full command transcript)
  - openralph.log (app logs)
  - test_results.md (structured results)
  - bugs.md (detailed bug list)
  - ux_ui_review.md (UI/UX review)
  - screenshots/ (if you can capture screenshots)
- If a command fails, immediately capture:
  - exit code
  - stdout/stderr
  - relevant log tail (last 200–500 lines)
  - environment details at time of failure

ENVIRONMENT SNAPSHOT (DO THIS EARLY)
Capture and record (with commands + outputs):
- OS + kernel (uname -a)
- Python version(s) (python --version, which python)
- pipx version (pipx --version)
- Node/npm versions if relevant (node -v, npm -v)
- Disk + memory (df -h, free -h)
- Relevant env vars (printenv | sort) — redact secrets if present

PHASE 1 — CLEAN SETUP
1) Ensure /home/justin/codex_openralph_test exists and is empty-ish.
2) Initialize a git repo there.
3) Create artifacts/ folder structure.
4) Run the mandatory pipx install:
   pipx install /home/justin/openralph --force
5) Confirm installation succeeded:
   - pipx list
   - verify the openralph executable is available (command -v openralph or equivalent)
   - run the CLI help (openralph --help)

If installation fails:
- Diagnose root cause (missing deps, packaging metadata, python constraints, build backend issues).
- Attempt reasonable fixes (system deps, pipx interpreter selection, clearing venvs, etc.).
- Document every attempt and why you tried it.
- End with a best-guess root cause and a concrete fix recommendation.

PHASE 2 — BOOT & SMOKE TEST
Goal: Launch OpenRalph and prove it runs.
1) Start OpenRalph using the recommended/standard startup method.
2) Identify what services it uses (web server, background workers, db, etc.).
3) Confirm it is reachable (CLI output, local URL, HTTP status, logs show “ready”, etc.).
4) Run a minimal “smoke test” workflow end-to-end:
   - create something
   - save it
   - retrieve it
   - confirm data integrity

Capture:
- startup time
- port used
- logs during startup
- any warnings/errors even if it “works”

PHASE 3 — BUILD A TEST APP / PROJECT WITH OPENRALPH
Goal: Build a simple but realistic app using OpenRalph and verify it works.

Requirements:
- Use OpenRalph to create/build a small app or project that exercises core features.
- The app must run successfully and demonstrate at least:
  - basic CRUD or equivalent meaningful workflow
  - one “happy path” scenario
  - one “edge case” scenario (e.g., invalid input)
- Provide exact steps to run the built app from scratch.

If the app does not work:
- Determine if the failure is due to OpenRalph, documentation gaps, environment issues, or usage.
- Provide a concrete fix (code/config changes, doc updates, packaging fixes, etc.).

PHASE 4 — DEEP QA “TORTURE TEST” MATRIX
Run the following tests and record PASS/FAIL with evidence:

A) INSTALLATION & CONFIG
- Fresh install (done)
- Reinstall/upgrade path (repeat pipx install --force)
- Missing dependency simulation (if feasible) and recovery
- Config validation: invalid config, missing env vars, malformed values

B) FUNCTIONAL
- Core workflow #1 (primary use case)
- Core workflow #2 (secondary use case)
- Data persistence: create → restart → verify data still present
- Permissions/auth flows (if applicable)

C) INTEGRATION
- Database connectivity (if applicable)
- External services integration (if applicable)
- API endpoints: basic healthcheck + one real endpoint
- CORS / auth headers / error codes sanity (if applicable)

D) STABILITY & RESILIENCE
- Restart OpenRalph service multiple times; verify no degradation
- Kill and relaunch; confirm recovery
- Run same workflow 10x; check for memory leaks or increasing latency (basic observation)
- Concurrency check: run two workflows in parallel if feasible

E) ERROR RECOVERY
- Intentionally break a config value → observe failure mode → restore → confirm recovery
- Intentionally input invalid data → confirm UX + error messaging
- Network/port conflict simulation if feasible

PHASE 5 — UI/UX REVIEW (CRITICAL)
Evaluate the UI like a real user. Provide both qualitative notes and actionable fixes.

Cover:
1) Information architecture & navigation
- Can a new user find key actions quickly?
- Are labels clear? Is the mental model consistent?

2) Interaction design
- Form validation quality (inline errors, clarity, timing)
- Feedback states (loading, success, error)
- Undo/confirm patterns, destructive action safety

3) Visual design
- Consistency (spacing, typography, components)
- Readability and hierarchy
- Dark mode (if any), contrast issues

4) Accessibility
- Keyboard navigation
- Focus states
- Contrast and text sizing
- Screen reader hints (if detectable)

5) Performance perception
- Time to interactive
- UI responsiveness under load

For every UI/UX issue include:
- Steps to reach the issue
- What the user expected vs what happened
- Severity (Minor/Major/Critical)
- A specific recommendation (copy suggestion, layout tweak, component fix, flow change)
- If possible, propose improved microcopy for confusing labels/messages

If you can capture screenshots, store them in artifacts/screenshots and reference them.

PHASE 6 — BUG DOSSIER (ENGINEERING GRADE)
For each bug, produce a GitHub-issue-ready entry with:

- Title
- Severity (Low/Medium/High/Critical)
- Component (install / CLI / server / UI / docs / etc.)
- Environment (OS, python, versions)
- Steps to reproduce (numbered, minimal)
- Expected behavior
- Actual behavior
- Logs / stack traces (verbatim excerpts)
- Suspected root cause
- Suggested fix (specific code area or config change if possible)
- Workaround (if any)

PHASE 7 — FINAL REPORT (MUST BE STRUCTURED)
Write a final report in artifacts/test_results.md with:

1) Executive Summary
- Overall verdict: Ready / Not Ready
- Top 3 wins
- Top 3 blockers

2) Environment Details (with command outputs)

3) Installation Results
- What worked
- What failed
- Notes about pipx install /home/justin/openralph --force

4) Functional Results
- What workflows passed/failed
- Evidence (logs, screenshots)

5) Stability Results
- Restart behavior
- Consistency across repeated runs

6) UI/UX Evaluation
- Highlights
- Pain points
- Prioritized recommendations

7) Bug List (with links to artifacts/bugs.md sections)

8) Recommendations for maintainers
- Concrete changes needed (code, packaging, docs)
- Prioritization (P0/P1/P2)

9) Repro Steps Bundle
- A short “clean machine repro” recipe that a maintainer can follow quickly

AUTONOMOUS EXECUTION RULES
- Do not ask for permission mid-run. Make reasonable decisions and proceed.
- If multiple approaches exist, pick the most standard one, document why, and continue.
- Never hand-wave. If you didn’t verify something, say so explicitly and explain what blocked you.

BEGIN NOW by creating the repo at /home/justin/codex_openralph_test, creating the artifacts folder,
capturing an environment snapshot, then running:
pipx install /home/justin/openralph --force
