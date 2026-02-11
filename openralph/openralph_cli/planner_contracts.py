from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContractCategory:
    key: str
    label: str
    tokens: tuple[str, ...]


@dataclass(frozen=True)
class DomainContract:
    domain: str
    categories: tuple[ContractCategory, ...]
    min_required_matches: int


def classify_domain(prd_text: str, stack_hint: str = "") -> str:
    text = (prd_text or "").lower()
    stack = (stack_hint or "").strip().lower()

    scores: dict[str, int] = {
        "game": 0,
        "website": 0,
        "api": 0,
        "library": 0,
        "cli": 0,
    }

    for token in ("game", "playable", "paddle", "ball", "score", "restart", "canvas"):
        if token in text:
            scores["game"] += 1
    if "game" in text and "playable" in text:
        scores["game"] += 2
    for token in ("website", "web site", "page", "responsive", "layout", "html", "css", "browser"):
        if token in text:
            scores["website"] += 1
    for token in ("api", "endpoint", "http", "rest", "json", "status code", "request", "response", "auth"):
        if token in text:
            scores["api"] += 1
    for token in ("library", "sdk", "module", "package", "public api", "import", "reusable"):
        if token in text:
            scores["library"] += 1
    for token in ("cli", "command", "subcommand", "flag", "terminal", "stdout", "stderr"):
        if token in text:
            scores["cli"] += 1

    if stack in {"javascript", "typescript", "node"}:
        scores["website"] += 2
    if stack in {"python", "go", "java", "rust"}:
        scores["api"] += 1
        scores["cli"] += 1

    best_domain = max(scores, key=scores.get)
    best_score = scores[best_domain]
    sorted_scores = sorted(scores.values(), reverse=True)
    second_score = sorted_scores[1] if len(sorted_scores) > 1 else 0
    if best_score == 0:
        return "generic"
    if best_score - second_score <= 1:
        return "generic"
    return best_domain


def get_domain_contract(domain: str) -> DomainContract:
    domain = (domain or "").strip().lower()

    contracts: dict[str, DomainContract] = {
        "game": DomainContract(
            domain="game",
            categories=(
                ContractCategory("setup", "setup/scaffold", ("setup", "scaffold", "project", "bootstrap")),
                ContractCategory("gameplay_loop", "gameplay loop", ("loop", "engine", "update", "render", "state")),
                ContractCategory("controls_input", "controls/input", ("control", "input", "keyboard", "mouse", "touch")),
                ContractCategory("score_progression", "score/progression", ("score", "points", "scoring", "progression")),
                ContractCategory("terminal_restart", "terminal/restart", ("game over", "terminal", "restart", "replay", "reset")),
                ContractCategory("test_verification", "test/verification", ("test", "verify", "acceptance", "qa")),
            ),
            min_required_matches=4,
        ),
        "website": DomainContract(
            domain="website",
            categories=(
                ContractCategory("scaffold_structure", "scaffold/structure", ("setup", "scaffold", "project", "structure", "bootstrap")),
                ContractCategory("page_route_flow", "pages/routes", ("page", "route", "navigation", "view")),
                ContractCategory("interaction_logic", "interaction logic", ("interaction", "event", "form", "state", "ui logic")),
                ContractCategory("styling_accessibility", "styling/accessibility", ("style", "css", "responsive", "accessibility", "a11y")),
                ContractCategory("content_data_flow", "content/data flow", ("content", "data", "fetch", "render", "api")),
                ContractCategory("test_verification", "test/verification", ("test", "verify", "acceptance", "qa")),
            ),
            min_required_matches=4,
        ),
        "api": DomainContract(
            domain="api",
            categories=(
                ContractCategory("scaffold_structure", "scaffold/structure", ("setup", "scaffold", "project", "bootstrap")),
                ContractCategory("endpoint_surface", "endpoint surface", ("endpoint", "route", "http", "rest", "handler")),
                ContractCategory("data_validation", "data/validation", ("schema", "validation", "payload", "serialization")),
                ContractCategory("auth_error_handling", "auth/error handling", ("auth", "authorization", "error", "status code", "exception")),
                ContractCategory("docs_contracts", "docs/contracts", ("openapi", "swagger", "contract", "documentation")),
                ContractCategory("test_verification", "test/verification", ("test", "verify", "integration", "qa")),
            ),
            min_required_matches=4,
        ),
        "library": DomainContract(
            domain="library",
            categories=(
                ContractCategory("scaffold_structure", "scaffold/structure", ("setup", "scaffold", "project", "package")),
                ContractCategory("public_api_surface", "public API surface", ("public api", "interface", "function", "class", "module")),
                ContractCategory("core_logic_modules", "core logic/modules", ("core", "logic", "module", "implementation")),
                ContractCategory("docs_examples", "docs/examples", ("readme", "example", "usage", "documentation")),
                ContractCategory("packaging_release", "packaging/release", ("version", "release", "publish", "package", "distribution")),
                ContractCategory("test_verification", "test/verification", ("test", "verify", "unit", "qa")),
            ),
            min_required_matches=4,
        ),
        "cli": DomainContract(
            domain="cli",
            categories=(
                ContractCategory("scaffold_structure", "scaffold/structure", ("setup", "scaffold", "project", "bootstrap")),
                ContractCategory("command_surface", "command surface", ("command", "subcommand", "flag", "option", "argument")),
                ContractCategory("io_validation", "I/O validation", ("input", "output", "stdout", "stderr", "validation")),
                ContractCategory("error_handling", "error handling", ("error", "exit code", "exception", "failure")),
                ContractCategory("help_docs", "help/docs", ("help", "usage", "docs", "man page", "readme")),
                ContractCategory("test_verification", "test/verification", ("test", "verify", "qa", "integration")),
            ),
            min_required_matches=4,
        ),
        "generic": DomainContract(
            domain="generic",
            categories=(
                ContractCategory("scaffold_structure", "scaffold/structure", ("setup", "scaffold", "project", "bootstrap")),
                ContractCategory("core_functionality", "core functionality", ("core", "feature", "functionality", "implementation")),
                ContractCategory("test_verification", "test/verification", ("test", "verify", "acceptance", "qa")),
            ),
            min_required_matches=2,
        ),
    }

    return contracts.get(domain, contracts["generic"])
