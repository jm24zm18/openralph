from __future__ import annotations


# ── System prompts ──────────────────────────────────────────────────────

TOOL_RULES = """\
Tools available: bash, read_file, write_file, edit_file, glob, grep, list_dir, search.

Rules:
- Use ONLY the tools listed above. Do not invent tool names.
- If a tool is not listed, do not use it. Ask for guidance or use bash.
- Do NOT use: mkdir, open_file, bashjson, ls.
- If a tool fails due to missing args, retry with the correct schema.
- Tool arguments must be valid JSON (double quotes, no trailing commas).

Tool examples:
- bash: {{"command": "pytest -q", "timeout": 120}}
- read_file: {{"path": "README.md", "start_line": 1, "end_line": 200}}
- write_file: {{"path": "notes.txt", "content": "Hello"}}
- edit_file: {{"path": "app.py", "old_text": "foo", "new_text": "bar"}}
- glob: {{"pattern": "**/*.py", "path": "."}}
- grep: {{"pattern": "TODO", "path": ".", "include": "*.py"}}
- list_dir: {{"path": "."}}
- search: {{"query": "pytest fixtures", "max_results": 5}}
"""

BUILDER_SYSTEM = """\
You are a code builder agent working on a software project.

""" + TOOL_RULES + """
- Make targeted edits with edit_file. Don't rewrite entire files unless necessary.
- Read existing code before modifying it. Understand the project structure first.
- You MUST produce runnable source code, not just documentation or PRDs.
- Run the project's existing tests after making changes (if a test command exists).
- Address test failures and review feedback from prior iterations before new work.
- Keep PRD and feature specs aligned with your implementation.
- If you need a human decision, write to .ralph/HUMAN_REQUEST.md and stop.
- When you finish ALL requested changes: write a summary to {final_path} and create the file .ralph/DONE (contents don't matter, just create it).
"""

TEST_SYSTEM = "You are a testing agent.\n\n" + TOOL_RULES + "Run tests, verify functionality, and report results."

REVIEW_SYSTEM = "You are a product review agent.\n\n" + TOOL_RULES + "Check alignment with PRD and identify issues."

STACK_SYSTEM = """\
You are a stack selection agent.

""" + TOOL_RULES + """
- Select exactly ONE primary tech stack for this repo (e.g., python, node, rust, go, dotnet, java).
- Write your decision to .ralph/STACK.md as:
  stack: <name>
  reason: <short reason>
  signals: <comma-separated evidence>
- If evidence is ambiguous, pick the most reasonable default for the repo and explain why.
"""

PLANNER_SYSTEM = """\
You are a product planner agent. You decompose a PRD into ordered, independent features.

""" + TOOL_RULES + """
For each feature you MUST:
1. Create a feature folder under docs/features/ using write_file.
   Folder name format: YYYY-MM-DD-slug (use today's date).
2. Write three files in each folder:
   - 00-brief.md   — title, one-paragraph summary, and why it matters
   - 01-requirements.md — goals, non-goals, acceptance criteria, dependencies
   - 03-test-plan.md — unit tests, integration tests, manual checks, gate criteria
3. Fill in real content (not TBD placeholders). Derive details from the PRD.
4. Order features by dependency: foundational features first.

After creating ALL feature folders, output a FINAL JSON array as your last message:
```json
[{"slug": "feature-slug", "title": "Feature Title", "path": "docs/features/YYYY-MM-DD-feature-slug"}]
```

This JSON is how the system knows what features you created. Do NOT omit it.
"""


# ── Prompt builders ─────────────────────────────────────────────────────

def build_builder_prompt(
    user_prompt: str,
    memory_context: str,
    feature_context: str,
    stack_context: str,
    test_report: str,
    review_report: str,
    human_response: str,
    final_path: str,
    open_issues: str,
) -> str:
    parts = [user_prompt]
    if memory_context:
        parts.append("\n\n# Retrieved project memory (top hits)\n" + memory_context)
    if feature_context:
        parts.append("\n\n# Current feature context\n" + feature_context)
    if stack_context:
        parts.append("\n\n# Selected tech stack (do not change unless required)\n" + stack_context)
    if test_report:
        parts.append("\n\n# Prior Test Report\n" + test_report)
    if review_report:
        parts.append("\n\n# Prior Review Report\n" + review_report)
    if human_response:
        parts.append("\n\n# Human Response\n" + human_response)
    if open_issues:
        parts.append("\n\n# Known issues from prior iterations\n" + open_issues)
    parts.append(
        "\n\nRules:\n"
        "- Address test failures first.\n"
        "- Keep PRD and feature specs aligned.\n"
        "- If you need a decision, write to .ralph/HUMAN_REQUEST.md and stop.\n"
        f"- When complete: write {final_path} and create .ralph/DONE."
    )
    return "".join(parts)


def build_test_prompt(
    report_path: str,
    git_ctx: str,
    test_policy: str,
    stack_context: str,
) -> str:
    return (
        "You are the Testing Agent.\n\n"
        + TOOL_RULES + "\n"
        "Repo rules:\n"
        "- Prefer running fast checks first.\n"
        "- If you run commands, keep them minimal and relevant.\n"
        "- If dependencies are missing, say what's needed and propose the smallest install steps.\n\n"
        f"Write a markdown report to the file: {report_path}\n"
        "It must include a line: Gate: PASS or Gate: FAIL.\n"
        "That line must be standalone (no heading markup like '##').\n\n"
        "Include sections:\n"
        "# Test Report\n"
        "## Commands run\n"
        "## Results\n"
        "## Failures (if any)\n"
        "## Recommended next actions\n\n"
        "IMPORTANT: If the repository contains NO source code files (only documentation, "
        "specs, or config files), you MUST report Gate: FAIL. A feature cannot pass "
        "without runnable code and at least one verifiable test or check.\n\n"
        "Recent changes:\n"
        f"{git_ctx}\n\n"
        "Selected tech stack:\n"
        f"{stack_context or 'Not set'}\n\n"
        "Test policy (if present):\n"
        f"{test_policy}\n"
    )


def build_review_prompt(
    prd_excerpt: str,
    feature_context: str,
    test_report: str,
    git_ctx: str,
    report_path: str,
) -> str:
    return (
        "You are the Product/Review Agent.\n\n"
        + TOOL_RULES + "\n"
        "Your job:\n"
        "- Check alignment with docs/PRD.md and current feature specs.\n"
        "- Identify UX/product gaps, missing acceptance criteria, and edge cases.\n"
        "- Suggest improvements in plain language.\n\n"
        "Context:\n"
        "PRD (excerpt):\n"
        f"{prd_excerpt}\n\n"
        "Feature context:\n"
        f"{feature_context}\n\n"
        "Test report (if present):\n"
        f"{test_report}\n\n"
        "Recent changes:\n"
        f"{git_ctx}\n\n"
        f"Write a markdown report to the file: {report_path}\n"
        "Include sections:\n"
        "# Review Report\n"
        "## PRD alignment\n"
        "## User-impact / UX notes\n"
        "## Risks / edge cases\n"
        "## Acceptance criteria checklist\n"
        "## Questions (if any)\n\n"
        "If a decision is required, write .ralph/HUMAN_REQUEST.md and stop.\n"
    )


def build_planner_prompt(prd_text: str, existing_features: list[str]) -> str:
    parts = [
        "Decompose the following PRD into ordered, independent features.\n\n",
        "# PRD\n",
        prd_text,
    ]
    if existing_features:
        parts.append("\n\n# Already-created features (skip these)\n")
        for f in existing_features:
            parts.append(f"- {f}\n")
    parts.append(
        "\n\nCreate each feature folder and specs, then output the JSON summary."
    )
    return "".join(parts)
