import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Tuple


API_ROOT = "https://api.github.com"
ARCHITECTURE_DOC_PATH = "docs/architecture.md"


class AutoFixError(RuntimeError):
    pass


def bool_from_string(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off"}:
        return False
    return default


def sanitize_branch_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-._")
    return cleaned[:80] or "branch"


def build_fix_branch_name(source_branch: str, head_sha: str) -> str:
    short_commit = re.sub(r"[^a-fA-F0-9]", "", head_sha)[:7] or "unknown"
    return f"{sanitize_branch_component(source_branch)}-agent-fixes-{short_commit}"


def is_agent_fix_branch(branch: str) -> bool:
    return "-agent-fixes-" in branch.lower()


def line_ending(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def apply_line_replacement(text: str, line_number: int, suggestion: str, source_line: Optional[str]) -> Optional[str]:
    lines = text.splitlines()
    if line_number < 1 or line_number > len(lines):
        return None
    current = lines[line_number - 1]
    if source_line is not None and current != source_line:
        return None
    replacement = suggestion.rstrip("\r\n").splitlines() or [""]
    updated = lines[: line_number - 1] + replacement + lines[line_number:]
    ending = line_ending(text)
    result = ending.join(updated)
    if text.endswith(("\n", "\r\n")):
        result += ending
    return result


def apply_safe_finding_fixes(
    file_contents: Dict[str, str],
    findings: Iterable[Dict[str, Any]],
    max_findings: int,
    max_files: int,
) -> Tuple[Dict[str, str], int]:
    modified = dict(file_contents)
    applied = 0
    touched_files = set()

    for finding in findings:
        if applied >= max_findings:
            break
        if not bool_from_string(finding.get("auto_fix")):
            continue
        path = str(finding.get("path") or "")
        line = finding.get("line")
        suggestion = str(finding.get("suggestion") or "")
        if not path or not isinstance(line, int) or not suggestion or path not in modified:
            continue
        if path not in touched_files and len(touched_files) >= max_files:
            continue
        next_text = apply_line_replacement(
            modified[path],
            line,
            suggestion,
            finding.get("source_line") if isinstance(finding.get("source_line"), str) else None,
        )
        if next_text is None or next_text == modified[path]:
            continue
        modified[path] = next_text
        touched_files.add(path)
        applied += 1

    return modified, applied


def readme_path(file_contents: Dict[str, str]) -> Optional[str]:
    for path in sorted(file_contents):
        if PurePosixPath(path).name.lower() == "readme.md":
            return path
    return None


def readme_has_mermaid(text: str) -> bool:
    return "```mermaid" in text.lower()


def mermaid_diagram_for_repo(repository: str) -> str:
    return (
        "## Architecture\n\n"
        "```mermaid\n"
        "flowchart LR\n"
        "  contributor[\"Contributor\"] --> pr[\"Pull Request\"]\n"
        "  pr --> ci[\"CI and Review Checks\"]\n"
        "  ci --> app[\"Application and Infrastructure\"]\n"
        "  app --> deploy[\"Deployment Runtime\"]\n"
        "  ci --> feedback[\"Review Findings and Fix PRs\"]\n"
        "  feedback --> pr\n"
        "```\n\n"
        f"This diagram was added by GHA AI Agent while preparing automated fixes for `{repository}`.\n"
    )


def add_readme_mermaid_if_missing(
    file_contents: Dict[str, str],
    repository: str,
    enabled: bool,
) -> Tuple[Dict[str, str], bool]:
    if not enabled:
        return dict(file_contents), False
    path = readme_path(file_contents)
    if not path:
        return dict(file_contents), False
    text = file_contents[path]
    if readme_has_mermaid(text):
        return dict(file_contents), False
    ending = line_ending(text)
    separator = ending if text.endswith(("\n", "\r\n")) else ending + ending
    updated = dict(file_contents)
    updated[path] = text + separator + mermaid_diagram_for_repo(repository).replace("\n", ending)
    return updated, True


def is_architecture_doc_path(path: str) -> bool:
    normalized = path.lower().replace("\\", "/")
    name = PurePosixPath(normalized).name
    return (
        normalized in {"architecture.md", "docs/architecture.md", "docs/platform-architecture.md"}
        or name in {"architecture.md", "platform-architecture.md", "technical-architecture.md"}
        or ("docs/" in normalized and any(part in name for part in ("architecture", "design", "technical-overview")))
    )


def architecture_docs_exist(context: Dict[str, Any], file_contents: Dict[str, str]) -> bool:
    paths = set(str(path) for path in file_contents)
    paths.update(str(path) for path in (context.get("head_tree_paths") or []))
    for path in paths:
        if is_architecture_doc_path(path):
            return True
    return False


def architecture_doc_for_repo(repository: str, context: Dict[str, Any]) -> str:
    tree_paths = [str(path) for path in (context.get("head_tree_paths") or [])]
    workflows = sorted(path for path in tree_paths if path.startswith(".github/workflows/"))[:12]
    containers = sorted(path for path in tree_paths if PurePosixPath(path).name.lower().startswith("dockerfile"))[:12]
    packages = sorted(
        path
        for path in tree_paths
        if PurePosixPath(path).name.lower()
        in {"package.json", "pyproject.toml", "requirements.txt", "go.mod", "pom.xml", "build.gradle", "cargo.toml"}
    )[:12]
    infra = sorted(
        path
        for path in tree_paths
        if path.endswith((".tf", ".tfvars", ".bicep", ".template.yaml", ".template.yml"))
        or any(part in path.lower() for part in ("infra/", "terraform/", "k8s/", "kubernetes/", "helm/", "charts/"))
    )[:16]

    def bullet_section(title: str, items: List[str]) -> str:
        if not items:
            return f"### {title}\n\nNo {title.lower()} paths were detected from the repository tree captured by GHA AI Agent.\n"
        bullets = "\n".join(f"- `{item}`" for item in items)
        return f"### {title}\n\n{bullets}\n"

    return (
        f"# {repository} Architecture\n\n"
        "This document was created by GHA AI Agent to provide a baseline platform architecture overview for reviewers and maintainers. "
        "Update it with service-specific details as the system evolves.\n\n"
        "## System Flow\n\n"
        "```mermaid\n"
        "flowchart LR\n"
        "  contributor[\"Contributor\"] --> pr[\"Pull Request\"]\n"
        "  pr --> ci[\"CI and Review Workflows\"]\n"
        "  ci --> build[\"Build and Test Steps\"]\n"
        "  build --> app[\"Application or Infrastructure Code\"]\n"
        "  app --> runtime[\"Deployment Runtime\"]\n"
        "  ci --> review[\"Review Findings\"]\n"
        "  review --> fixes[\"Fix PRs\"]\n"
        "  fixes --> pr\n"
        "```\n\n"
        "## Repository Responsibilities\n\n"
        "- Keep application, infrastructure, CI/CD, and documentation changes reviewable from pull requests.\n"
        "- Keep secrets in GitHub Actions secrets, cloud secret managers, or runtime identity systems rather than source files.\n"
        "- Keep architecture, operational, security, and compliance decisions visible in Markdown documentation.\n"
        "- Keep tests and coverage reports close to the behavior they validate.\n\n"
        "## Trust Boundaries\n\n"
        "```mermaid\n"
        "flowchart TD\n"
        "  user[\"User or Operator\"] --> app[\"Application Boundary\"]\n"
        "  app --> data[\"Data Stores and Queues\"]\n"
        "  app --> cloud[\"Cloud Control Plane\"]\n"
        "  ci[\"GitHub Actions Runner\"] --> cloud\n"
        "  ci --> registry[\"Package and Image Registries\"]\n"
        "  secrets[\"Secrets and Identity\"] --> ci\n"
        "  secrets --> app\n"
        "```\n\n"
        "Review every change that crosses these boundaries for authentication, authorization, encryption, logging, retention, and rollback behavior.\n\n"
        + bullet_section("GitHub Workflows", workflows)
        + "\n"
        + bullet_section("Container Entrypoints", containers)
        + "\n"
        + bullet_section("Package Manifests", packages)
        + "\n"
        + bullet_section("Infrastructure And Deployment Paths", infra)
        + "\n"
        "## Review Expectations\n\n"
        "- Architecture-affecting changes should update this document or explain why the current architecture remains accurate.\n"
        "- Security-sensitive changes should identify assets, trust boundaries, attacker-controlled inputs, and mitigations.\n"
        "- Infrastructure changes should document blast radius, rollback, identity, network exposure, and audit evidence.\n"
        "- CI/CD changes should document token scopes, runner trust, artifact integrity, and deployment gates.\n"
    )


def add_architecture_docs_if_missing(
    file_contents: Dict[str, str],
    repository: str,
    context: Dict[str, Any],
    enabled: bool,
) -> Tuple[Dict[str, str], bool]:
    if not enabled:
        return dict(file_contents), False
    if architecture_docs_exist(context, file_contents):
        return dict(file_contents), False
    updated = dict(file_contents)
    updated[ARCHITECTURE_DOC_PATH] = architecture_doc_for_repo(repository, context)
    return updated, True


def github_request(
    method: str,
    repo: str,
    path: str,
    token: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    url = f"{API_ROOT}/repos/{repo}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "gha-agent-review",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise AutoFixError(f"GitHub API {method} {repo}{path} failed: {exc.code}: {details}") from exc


def create_fix_branch_commit_and_pr(
    *,
    token: str,
    head_repo: str,
    source_branch: str,
    fix_branch: str,
    head_sha: str,
    modified_files: Dict[str, str],
    title: str,
    body: str,
) -> str:
    github_request(
        "POST",
        head_repo,
        "/git/refs",
        token,
        {"ref": f"refs/heads/{fix_branch}", "sha": head_sha},
    )
    commit = github_request("GET", head_repo, f"/git/commits/{urllib.parse.quote(head_sha, safe='')}", token)
    base_tree = ((commit.get("tree") or {}).get("sha")) or ""
    if not base_tree:
        raise AutoFixError("Could not resolve the PR head tree for automatic fixes")

    tree_entries = [
        {"path": path, "mode": "100644", "type": "blob", "content": content}
        for path, content in sorted(modified_files.items())
    ]
    tree = github_request(
        "POST",
        head_repo,
        "/git/trees",
        token,
        {"base_tree": base_tree, "tree": tree_entries},
    )
    new_commit = github_request(
        "POST",
        head_repo,
        "/git/commits",
        token,
        {
            "message": "Apply GHA AI Agent automatic fixes",
            "tree": tree["sha"],
            "parents": [head_sha],
        },
    )
    encoded_ref = urllib.parse.quote(f"heads/{fix_branch}", safe="")
    github_request(
        "PATCH",
        head_repo,
        f"/git/refs/{encoded_ref}",
        token,
        {"sha": new_commit["sha"], "force": False},
    )
    pr = github_request(
        "POST",
        head_repo,
        "/pulls",
        token,
        {
            "title": title,
            "head": fix_branch,
            "base": source_branch,
            "body": body,
            "maintainer_can_modify": True,
        },
    )
    return str(pr.get("html_url") or "")


def run_auto_fix(
    *,
    token: str,
    repository: str,
    context: Dict[str, Any],
    result: Dict[str, Any],
    enabled: bool,
    add_readme_diagrams: bool,
    add_architecture_docs: bool,
    max_findings: int,
    max_files: int,
) -> Dict[str, Any]:
    status: Dict[str, Any] = {
        "status": "disabled" if not enabled else "skipped",
        "message": "",
        "fix_branch": "",
        "fix_pr_url": "",
        "fix_count": 0,
        "diagram_added": False,
        "architecture_doc_added": False,
    }
    if not enabled:
        status["message"] = "Automatic fix PR creation is disabled by action input."
        return status

    pr = context.get("pr") or {}
    source_branch = str(pr.get("head_ref") or "")
    head_sha = str(pr.get("head_sha") or "")
    head_repo = str(pr.get("head_repo") or repository)
    if not source_branch or not head_sha:
        status["message"] = "Automatic fixes skipped because PR head branch metadata was unavailable."
        return status
    if is_agent_fix_branch(source_branch):
        status["message"] = "Automatic fixes skipped because this is already an agent fix branch."
        return status

    original_contents = {str(path): str(text) for path, text in (context.get("file_contents") or {}).items()}
    fixed_contents, fix_count = apply_safe_finding_fixes(
        original_contents,
        result.get("findings") or [],
        max_findings=max_findings,
        max_files=max_files,
    )
    fixed_contents, diagram_added = add_readme_mermaid_if_missing(
        fixed_contents,
        repository,
        enabled=add_readme_diagrams,
    )
    fixed_contents, architecture_doc_added = add_architecture_docs_if_missing(
        fixed_contents,
        repository,
        context,
        enabled=add_architecture_docs,
    )
    modified_files = {
        path: text
        for path, text in fixed_contents.items()
        if original_contents.get(path) != text
    }
    if not modified_files:
        status["message"] = "No safe deterministic fixes were available."
        return status

    fix_branch = build_fix_branch_name(source_branch, head_sha)
    body = (
        "This PR was opened by GHA AI Agent with safe deterministic fixes from the review.\n\n"
        f"- Source branch: `{source_branch}`\n"
        f"- Source commit: `{head_sha[:12]}`\n"
        f"- Safe finding fixes: `{fix_count}`\n"
        f"- README Mermaid diagram added: `{str(diagram_added).lower()}`\n"
        f"- Architecture documentation added: `{str(architecture_doc_added).lower()}`\n\n"
        "Review these changes before merging."
    )
    try:
        fix_pr_url = create_fix_branch_commit_and_pr(
            token=token,
            head_repo=head_repo,
            source_branch=source_branch,
            fix_branch=fix_branch,
            head_sha=head_sha,
            modified_files=modified_files,
            title="Apply GHA AI Agent automatic fixes",
            body=body,
        )
    except AutoFixError as exc:
        status["status"] = "failed"
        status["fix_branch"] = fix_branch
        status["fix_count"] = fix_count
        status["diagram_added"] = diagram_added
        status["architecture_doc_added"] = architecture_doc_added
        status["message"] = str(exc)
        return status

    status.update(
        {
            "status": "created",
            "message": "Opened a fix PR from the reviewed branch.",
            "fix_branch": fix_branch,
            "fix_pr_url": fix_pr_url,
            "fix_count": fix_count,
            "diagram_added": diagram_added,
            "architecture_doc_added": architecture_doc_added,
        }
    )
    return status
