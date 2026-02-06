from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .agent import run_agent, AgentConfig
from .agent.providers import OpenAIProvider
from .settings import OpenRalphSettings


@dataclass
class PRDContext:
    repo_name: str
    files: dict[str, str]
    file_tree: list[str]


PRD_TEMPLATE = """# Product Requirements Document — {repo_name}
- Date: {date}
- Owner: (TBD)
- Status: Draft

## 1. Problem statement
## 2. Goals
## 3. Non-goals
## 4. Users and use cases
## 5. Requirements
### 5.1 Functional requirements
### 5.2 Non-functional requirements
### 5.3 Accessibility / i18n (if relevant)
## 6. UX notes (if relevant)
## 7. Technical considerations
## 8. Analytics / success metrics
## 9. Risks and mitigations
## 10. Milestones
## 11. Open questions
"""

CONTEXT_FILES = [
    ("README.md", "README"),
    ("README.rst", "README"),
    ("CONTRIBUTING.md", "CONTRIBUTING"),
    ("docs/README.md", "DOCS_README"),
    ("package.json", "PACKAGE_JSON"),
    ("tsconfig.json", "TSCONFIG"),
    ("pyproject.toml", "PYPROJECT"),
    ("requirements.txt", "REQUIREMENTS"),
    ("setup.py", "SETUP_PY"),
    ("Makefile", "MAKEFILE"),
    (".github/workflows/ci.yml", "CI_WORKFLOW"),
    (".github/workflows/ci.yaml", "CI_WORKFLOW"),
]

EXCLUDE_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build", ".ralph", "__pycache__", ".ruff_cache"}


def _collect_context(repo: Path) -> PRDContext:
    files: dict[str, str] = {}
    for rel_path, label in CONTEXT_FILES:
        full_path = repo / rel_path
        if full_path.exists() and full_path.is_file():
            try:
                content = full_path.read_text(encoding="utf-8", errors="replace")
                # Cap file size
                lines = content.split("\n")[:400]
                files[label] = "\n".join(lines)
            except Exception:
                pass

    # Collect file tree
    file_tree: list[str] = []
    try:
        for p in repo.rglob("*"):
            if p.is_file():
                rel = p.relative_to(repo)
                parts = rel.parts
                if any(ex in parts for ex in EXCLUDE_DIRS):
                    continue
                if len(parts) <= 4:
                    file_tree.append(str(rel))
                    if len(file_tree) >= 500:
                        break
    except Exception:
        pass

    return PRDContext(
        repo_name=repo.name,
        files=files,
        file_tree=sorted(file_tree)[:500],
    )


def _build_prompt(ctx: PRDContext, extra_context: str | None = None) -> str:
    today = date.today().isoformat()

    context_parts = []
    for label, content in ctx.files.items():
        context_parts.append(f"===== BEGIN {label} =====")
        context_parts.append(content)
        context_parts.append(f"===== END {label} =====")
        context_parts.append("")

    if ctx.file_tree:
        context_parts.append("===== BEGIN FILE TREE (depth 4) =====")
        context_parts.extend(ctx.file_tree)
        context_parts.append("===== END FILE TREE =====")

    context_text = "\n".join(context_parts)

    extra = f"\nADDITIONAL INPUTS:\n{extra_context}\n" if extra_context else ""
    prompt = f"""You are writing a PRD for the software repository '{ctx.repo_name}'.

Output requirements:
- Produce a single markdown document.
- Use a crisp, product-style tone (not marketing).
- Include concrete acceptance criteria and non-goals.
- Include clear user stories and success metrics.
- Be honest about unknowns: call them out as open questions.
- Keep it actionable for engineering.

Write the PRD to match this structure:

# Product Requirements Document — {ctx.repo_name}
- Date: {today}
- Owner: (TBD)
- Status: Draft

## 1. Problem statement
## 2. Goals
## 3. Non-goals
## 4. Users and use cases
## 5. Requirements
### 5.1 Functional requirements
### 5.2 Non-functional requirements
### 5.3 Accessibility / i18n (if relevant)
## 6. UX notes (if relevant)
## 7. Technical considerations
## 8. Analytics / success metrics
## 9. Risks and mitigations
## 10. Milestones
## 11. Open questions

Use the repository context below. If the repo is a developer tool, treat the 'users' as developers.

REPOSITORY CONTEXT:
{context_text}
{extra}"""
    return prompt


def generate_prd(
    repo: Path,
    output_path: Path | None = None,
    extra_context: str | None = None,
) -> Path:
    """Generate a PRD for the repository using the native agent."""
    if output_path is None:
        output_path = repo / "docs" / "PRD.md"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    ctx = _collect_context(repo)
    prompt = _build_prompt(ctx, extra_context=extra_context)
    settings = OpenRalphSettings.load(repo)
    provider = _get_provider(settings)
    result = run_agent(
        provider=provider,
        prompt=prompt,
        repo=repo,
        config=AgentConfig(
            max_turns=settings.agent_max_turns,
            timeout_default=settings.agent_timeout,
            max_output_chars=settings.agent_max_output,
        ),
    )
    output = (result.final_text or "").strip()
    if not output:
        raise RuntimeError("PRD generation returned empty output")
    output_path.write_text(output, encoding="utf-8")
    return output_path

def generate_prd_answers(repo: Path, user_prompt: str = "") -> dict[str, str]:
    """Generate PRD Q&A answers using the native agent."""
    prompt = build_prd_answers_prompt(repo, user_prompt=user_prompt)
    settings = OpenRalphSettings.load(repo)
    provider = _get_provider(settings)
    result = run_agent(
        provider=provider,
        prompt=prompt,
        repo=repo,
        config=AgentConfig(
            max_turns=settings.agent_max_turns,
            system_prompt=(
                "You are a product manager. You may use tools if helpful, but your final response "
                "MUST be a single JSON object answering all questions. No markdown."
            ),
            timeout_default=settings.agent_timeout,
            max_output_chars=settings.agent_max_output,
        ),
    )
    output = (result.final_text or "").strip()
    data = _extract_json_from_response(output)
    if not data:
        raise RuntimeError("Failed to parse PRD answers JSON.")
    return data


def build_prd_answers_prompt(repo: Path, user_prompt: str = "") -> str:
    ctx = _collect_context(repo)
    questions = "\n".join([f"- {k}: {q}" for k, q in PRD_QA_QUESTIONS])
    user_context = f"\nUser's request:\n{user_prompt}\n" if user_prompt else ""
    prompt = f"""You are drafting PRD Q&A answers for the repository '{ctx.repo_name}'.
{user_context}
Return a single JSON object with keys matching the question ids.
Do not include extra commentary or markdown.
Your answers MUST align with the user's request above (especially tech_stack and features).

Questions:
{questions}
"""
    return prompt


def _get_provider(settings: OpenRalphSettings) -> OpenAIProvider:
    base_url = f"http://127.0.0.1:{settings.proxy_listen_port}"
    return OpenAIProvider(
        base_url=base_url,
        api_key=settings.proxy_api_key,
        model=settings.proxy_model_id,
        timeout=settings.agent_timeout,
    )


def _extract_json_from_response(text: str) -> dict[str, str] | None:
    try:
        return json.loads(text)
    except Exception:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except Exception:
                return None
        return None


PRD_QA_QUESTIONS = [
    ("project_name", "What is the name of this project?"),
    ("problem", "What problem does this project solve? (1-2 sentences)"),
    ("users", "Who are the primary users of this project?"),
    ("goals", "What are the main goals? (comma-separated)"),
    ("non_goals", "What is explicitly out of scope? (comma-separated)"),
    ("features", "What are the key features? (comma-separated)"),
    ("tech_stack", "What technologies/languages does this use?"),
    ("success_metrics", "How will you measure success?"),
    ("open_questions", "What questions remain unanswered?"),
]


def run_prd_qa(repo: Path) -> dict[str, str]:
    """Run interactive Q&A to gather PRD info."""
    answers: dict[str, str] = {}

    print("\n[bold]PRD Q&A Session[/bold]")
    print("Answer the following questions to generate a PRD.\n")

    for key, question in PRD_QA_QUESTIONS:
        print(f"[cyan]{question}[/cyan]")
        answer = input("> ").strip()
        answers[key] = answer
        print()

    return answers


def generate_prd_from_answers(repo: Path, answers: dict[str, str], output_path: Path | None = None) -> Path:
    """Generate a PRD from Q&A answers."""
    if output_path is None:
        output_path = repo / "docs" / "PRD.md"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()

    goals = [g.strip() for g in answers.get("goals", "").split(",") if g.strip()]
    non_goals = [g.strip() for g in answers.get("non_goals", "").split(",") if g.strip()]
    features = [f.strip() for f in answers.get("features", "").split(",") if f.strip()]
    open_questions = [q.strip() for q in answers.get("open_questions", "").split(",") if q.strip()]

    content = f"""# Product Requirements Document — {answers.get('project_name', repo.name)}
- Date: {today}
- Owner: (TBD)
- Status: Draft

## 1. Problem statement

{answers.get('problem', 'TBD')}

## 2. Goals

{chr(10).join(f'- {g}' for g in goals) if goals else '- TBD'}

## 3. Non-goals

{chr(10).join(f'- {g}' for g in non_goals) if non_goals else '- TBD'}

## 4. Users and use cases

**Primary users:** {answers.get('users', 'TBD')}

## 5. Requirements

### 5.1 Functional requirements

{chr(10).join(f'- {f}' for f in features) if features else '- TBD'}

### 5.2 Non-functional requirements

- TBD

### 5.3 Accessibility / i18n (if relevant)

- TBD

## 6. UX notes (if relevant)

- TBD

## 7. Technical considerations

**Tech stack:** {answers.get('tech_stack', 'TBD')}

## 8. Analytics / success metrics

{answers.get('success_metrics', 'TBD')}

## 9. Risks and mitigations

- TBD

## 10. Milestones

- TBD

## 11. Open questions

{chr(10).join(f'- {q}' for q in open_questions) if open_questions else '- None identified yet'}
"""

    output_path.write_text(content, encoding="utf-8")
    return output_path


def save_prd_answers(repo: Path, answers: dict[str, str]) -> Path:
    """Save PRD Q&A answers to .ralph/prd-answers.json."""
    ralph_dir = repo / ".ralph"
    ralph_dir.mkdir(parents=True, exist_ok=True)
    answers_path = ralph_dir / "prd-answers.json"
    answers_path.write_text(json.dumps(answers, indent=2), encoding="utf-8")
    return answers_path


def load_prd_answers(repo: Path) -> dict[str, str] | None:
    """Load PRD Q&A answers from .ralph/prd-answers.json."""
    answers_path = repo / ".ralph" / "prd-answers.json"
    if not answers_path.exists():
        return None
    try:
        return json.loads(answers_path.read_text(encoding="utf-8"))
    except Exception:
        return None
