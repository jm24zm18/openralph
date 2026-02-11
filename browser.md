 Plan: Full Browser + Debug Console Access for Agents                                      
                                                                                           
 Context                                                                                   
                                                                                           
 OpenRalph agents currently interact with browsers only through playwright-cli bash        
 commands (open, click, fill, screenshot, snapshot). This gives zero access to the browser
  debug console — no console.log output, no JS evaluation, no network request inspection,
 no uncaught error capture. The agents are flying blind when debugging web apps.

 This plan adds 8 first-class browser tools backed by Playwright's Python sync API with a
 persistent session that captures console/network/error events automatically.

 ---
 What Changes

 1. New file: openralph/openralph_cli/agent/browser.py

 Core browser session manager using playwright.sync_api:

 BrowserSessionConfig (frozen dataclass):
 - headless, viewport_width, viewport_height, default_timeout
 - console_buffer_max (500), network_buffer_max (200)
 - screenshot_dir (defaults to .ralph/screenshots/)

 BrowserSession class:
 - Lazily starts Playwright + Chromium + BrowserContext + Page via ensure_started()
 - Registers event listeners on page creation:
   - page.on("console") → appends to _console_log ring buffer {type, text, url, timestamp}
   - page.on("pageerror") → appends to _error_log {message, url, timestamp}
   - page.on("response") → appends to _network_log {method, url, status, content_type,
 timestamp}
   - page.on("crash") → marks session crashed
 - Action methods: navigate(), click(), fill(), type_text(), press(), screenshot(),
 snapshot(), evaluate(), get_console(), get_network(), get_errors(), wait_for_selector(),
 get_url(), get_content()
 - Auto-recovery: if page/browser crashes, restart transparently and tell agent to
 re-navigate
 - close(): tears down everything, idempotent
 - Thread-safe via threading.Lock

 Module-level singleton:
 - get_session(config) / close_session() — session persists across tool calls within an
 agent run

 Graceful degradation: if playwright not importable, all tools return install
 instructions.

 2. Modify: openralph/openralph_cli/agent/tools.py

 Add 8 tool definitions to TOOLS list:
 Tool: browser_navigate
 Purpose: Open URL, returns title/status
 Key Args: url, wait_until
 ────────────────────────────────────────
 Tool: browser_click
 Purpose: Click element by selector
 Key Args: selector
 ────────────────────────────────────────
 Tool: browser_fill
 Purpose: Fill form field
 Key Args: selector, value
 ────────────────────────────────────────
 Tool: browser_screenshot
 Purpose: Screenshot + accessibility tree
 Key Args: full_page, name
 ────────────────────────────────────────
 Tool: browser_snapshot
 Purpose: Accessibility tree (page structure)
 Key Args: —
 ────────────────────────────────────────
 Tool: browser_evaluate
 Purpose: Run JS in page context, return result
 Key Args: expression
 ────────────────────────────────────────
 Tool: browser_console
 Purpose: Read captured console output
 Key Args: level, last_n, clear
 ────────────────────────────────────────
 Tool: browser_network
 Purpose: View captured network requests
 Key Args: method, status_filter, last_n, clear
 Add to execute_tool() dispatch (8 new elif branches after repo_search). Each handler:
 - Calls get_session().method(...)
 - Catches exceptions → returns (error_str, True)
 - Runs on host (NOT through Docker sandbox) — same as search tool

 Add alias resolution for common agent misnaming (navigate → browser_navigate, js_eval →
 browser_evaluate, console → browser_console, etc.)

 3. Modify: openralph/openralph_cli/prompts.py

 Replace PLAYWRIGHT_CLI_RULES with BROWSER_TOOL_RULES:
 Browser tools (persistent headless browser session):
 - browser_navigate: Open a URL
 - browser_click / browser_fill: Interact with elements
 - browser_screenshot / browser_snapshot: See page state
 - browser_evaluate: Run JS in page context
 - browser_console: Read console.log/warn/error output
 - browser_network: View network requests (filter by status/method)

 Tips: start with navigate, use console to check for errors, use evaluate for DOM
 inspection.

 Update TOOL_RULES to include browser tool names in the available tools list and add
 examples.

 Update BUILDER_SYSTEM and TEST_SYSTEM to use BROWSER_TOOL_RULES (replace
 PLAYWRIGHT_CLI_RULES). Review/plan agents do NOT get browser tools.

 4. Modify: openralph/openralph_cli/settings.py

 - Add browser config fields: browser_headless, browser_viewport_width,
 browser_viewport_height, browser_default_timeout, browser_console_buffer_max,
 browser_network_buffer_max
 - Add [browser] section to config loader and STARTER_TOML
 - Add browser tool names to _VALID_AGENT_TOOL_PERMISSIONS
 - Add browser tools to default agent_code_permissions and agent_test_permissions
 - Add aliases to _TOOL_PERMISSION_ALIASES (navigate → browser_navigate, etc.)

 5. Modify: openralph/openralph_cli/loop/feature_runner.py

 Update _kill_playwright_sessions() to also call browser.close_session() before the legacy
  playwright-cli kill-all.

 6. Modify: openralph/openralph_cli/tooling.py

 Update doctor_report() to check Playwright Python availability and browser binaries as a
 health check.

 7. Modify: openralph/openralph_cli/agent/__init__.py

 Export close_session from browser module.

 ---
 Key Design Decisions

 - Dedicated tools, not bash commands: Structured tools give better validation, error
 handling, and prompt guidance vs playwright-cli via bash
 - Persistent session: Browser stays alive across tool calls within an agent run
 (singleton pattern)
 - Ring buffers for console/network: Prevents memory blowout on noisy pages (configurable
 max, oldest entries dropped)
 - Host-only execution: Browser tools always run on host, never in Docker sandbox (no
 browser binaries in python:3.12-slim)
 - Single-page model: One page at a time to keep it simple; browser_navigate reuses the
 same page
 - Auto-recovery: Crashed browser restarts transparently, agent told to re-navigate
 - browser_screenshot returns accessibility tree: LLM agents can't see images, so
 screenshot returns file path + text accessibility snapshot

 ---
 Files Summary
 ┌────────────────────────────────────────────────┬────────┐
 │                      File                      │ Action │
 ├────────────────────────────────────────────────┼────────┤
 │ openralph/openralph_cli/agent/browser.py       │ CREATE │
 ├────────────────────────────────────────────────┼────────┤
 │ openralph/openralph_cli/agent/tools.py         │ MODIFY │
 ├────────────────────────────────────────────────┼────────┤
 │ openralph/openralph_cli/agent/__init__.py      │ MODIFY │
 ├────────────────────────────────────────────────┼────────┤
 │ openralph/openralph_cli/prompts.py             │ MODIFY │
 ├────────────────────────────────────────────────┼────────┤
 │ openralph/openralph_cli/settings.py            │ MODIFY │
 ├────────────────────────────────────────────────┼────────┤
 │ openralph/openralph_cli/loop/feature_runner.py │ MODIFY │
 ├────────────────────────────────────────────────┼────────┤
 │ openralph/openralph_cli/tooling.py             │ MODIFY │
 └────────────────────────────────────────────────┴────────┘
 ---
 Verification

 1. Unit test: Import BrowserSession, verify console/network buffer capture with a local
 HTML file
 2. Tool dispatch test: Call execute_tool("browser_navigate", {"url": "..."}, ctx) and
 verify return format
 3. Permission test: Verify code/test roles have browser tools, review/plan roles don't
 4. Config test: Add [browser] section to a test TOML, verify settings load correctly
 5. Doctor check: Run openralph doctor . and verify browser-tools status line appears
 6. End-to-end: Run openralph run . "Build a simple web page" and confirm agents use
 browser tools to navigate, check console, and evaluate JS
