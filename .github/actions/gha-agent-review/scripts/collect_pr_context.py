#!/usr/bin/env python3
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List

from compliance_rules import build_compliance_prompt_context, load_compliance_catalog
from review_common import changed_lines_by_file
from super_skill_rules import build_super_skill_prompt_context, bool_from_value, load_super_skill_catalog


API_ROOT = "https://api.github.com"
TEXT_FILE_EXTENSIONS = {
    ".json",
    ".yml",
    ".yaml",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".py",
    ".md",
    ".txt",
    ".env",
    ".ini",
    ".toml",
    ".xml",
    ".info",
}

def github_request(path_or_url: str, token: str, accept: str = "application/vnd.github+json") -> Any:
    url = path_or_url if path_or_url.startswith("https://") else f"{API_ROOT}{path_or_url}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": accept,
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "gha-agent-review",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
            if accept.endswith(".diff"):
                return raw.decode("utf-8", errors="replace")
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API request failed: {exc.code} {url}: {details}") from exc


def paginated(path: str, token: str) -> List[Dict[str, Any]]:
    parsed = urllib.parse.urlparse(path)
    query = urllib.parse.parse_qs(parsed.query)
    query["per_page"] = ["100"]
    page = 1
    items: List[Dict[str, Any]] = []

    while True:
        query["page"] = [str(page)]
        page_path = parsed._replace(query=urllib.parse.urlencode(query, doseq=True)).geturl()
        current = github_request(page_path, token)
        if not current:
            return items
        items.extend(current)
        if len(current) < 100:
            return items
        page += 1


def repo_tree(repo: str, ref: str, token: str, max_paths: int = 5000) -> List[Dict[str, Any]]:
    encoded_ref = urllib.parse.quote(ref, safe="")
    tree = github_request(f"/repos/{repo}/git/trees/{encoded_ref}?recursive=1", token)
    items = tree.get("tree") or []
    if not isinstance(items, list):
        return []
    return items[:max_paths]


def read_repo_file(repo: str, path: str, ref: str, token: str, max_bytes: int = 250_000) -> str:
    encoded_path = urllib.parse.quote(path, safe="/")
    encoded_ref = urllib.parse.quote(ref, safe="")
    request = urllib.request.Request(
        f"{API_ROOT}/repos/{repo}/contents/{encoded_path}?ref={encoded_ref}",
        headers={
            "Accept": "application/vnd.github.raw, text/plain;q=0.9, */*;q=0.1",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "gha-agent-review",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read(max_bytes).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub file request failed: {exc.code} {repo}/{path}@{ref}: {details}") from exc


def should_capture_text_content(path: str) -> bool:
    suffix = os.path.splitext(path)[1].lower()
    basename = os.path.basename(path).lower()
    if suffix in TEXT_FILE_EXTENSIONS:
        return True
    return basename in {
        ".coveragerc",
        "dockerfile",
        "package.json",
        "cdk.json",
        "requirements.txt",
        "pipfile",
    } or basename.startswith("dockerfile.")


def collect_head_tree_paths(repository: str, head_sha: str, token: str) -> List[str]:
    try:
        return [str(item.get("path") or "") for item in repo_tree(repository, head_sha, token, max_paths=2000)]
    except RuntimeError:
        return []


def capture_extra_repo_paths(head_tree_paths: List[str]) -> List[str]:
    selected = []
    for path in head_tree_paths:
        basename = os.path.basename(path).lower()
        lower = path.lower()
        if path in {"cdk.json", "package.json", "pyproject.toml", ".coveragerc"}:
            selected.append(path)
        elif basename in {
            "readme.md",
            "architecture.md",
            "platform-architecture.md",
            "technical-architecture.md",
            "coverage-summary.json",
            "lcov.info",
            "coverage.xml",
            "jest.config.js",
            "jest.config.ts",
            "vitest.config.js",
            "vitest.config.ts",
            "vite.config.js",
            "vite.config.ts",
            "tox.ini",
            "setup.cfg",
        }:
            selected.append(path)
        elif lower.endswith(("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "uv.lock", "pdm.lock", "pipfile.lock")):
            selected.append(path)
        elif path.startswith("bin/") or path.startswith("lib/") or path.startswith(".github/workflows/configuration/"):
            selected.append(path)
        elif lower.startswith("docs/") and any(term in basename for term in ("architecture", "design", "technical-overview")):
            selected.append(path)
    return selected[:120]


def collect_file_contents(
    repository: str,
    files: List[Dict[str, Any]],
    head_sha: str,
    head_tree_paths: List[str],
    token: str,
) -> Dict[str, str]:
    paths = {
        str(file_info.get("filename") or "")
        for file_info in files
        if file_info.get("status") != "removed" and file_info.get("filename")
    }
    paths.update(capture_extra_repo_paths(head_tree_paths))
    contents: Dict[str, str] = {}
    for path in sorted(paths):
        if not should_capture_text_content(path):
            continue
        try:
            contents[path] = read_repo_file(repository, path, head_sha, token)
        except RuntimeError as exc:
            contents[path] = f"[gha-agent-review fetch error: {exc}]"
    return contents


def github_blob_to_contents_url(source: str) -> str:
    parsed = urllib.parse.urlparse(source)
    if parsed.netloc.lower() != "github.com":
        return source

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 5 or parts[2] != "blob":
        return source

    owner, repo = parts[0], parts[1]
    ref = parts[3]
    file_path = "/".join(parts[4:])
    encoded_path = urllib.parse.quote(file_path, safe="/")
    encoded_ref = urllib.parse.quote(ref, safe="")
    return f"{API_ROOT}/repos/{owner}/{repo}/contents/{encoded_path}?ref={encoded_ref}"


def read_text_source(source: str, label: str, token: str) -> str:
    if source.startswith(("https://", "http://")):
        url = github_blob_to_contents_url(source)
        parsed = urllib.parse.urlparse(url)
        headers = {
            "Accept": "application/vnd.github.raw, text/plain;q=0.9, */*;q=0.1",
            "User-Agent": "gha-agent-review",
        }
        if parsed.netloc.lower() in {"api.github.com", "github.com", "raw.githubusercontent.com"}:
            headers["Authorization"] = f"Bearer {token}"
            headers["X-GitHub-Api-Version"] = "2022-11-28"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{label} URL request failed: {exc.code} {url}: {details}") from exc

    if not os.path.exists(source):
        raise FileNotFoundError(f"{label} was not found at {source}")
    with open(source, "r", encoding="utf-8") as input_file:
        return input_file.read()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pr-number", required=True, type=int)
    parser.add_argument("--skill-file", required=True)
    parser.add_argument("--rules-file", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-diff-bytes", type=int, default=500_000)
    parser.add_argument("--super-skill-enabled", default="true")
    parser.add_argument("--super-skill-max-rules", type=int, default=120)
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("GITHUB_TOKEN is required", file=sys.stderr)
        return 2

    pr_path = f"/repos/{args.repository}/pulls/{args.pr_number}"
    pr = github_request(pr_path, token)
    files = paginated(f"/repos/{args.repository}/pulls/{args.pr_number}/files", token)
    head_sha = str(((pr.get("head") or {}).get("sha")) or "")
    head_tree_paths = collect_head_tree_paths(args.repository, head_sha, token) if head_sha else []
    diff = github_request(pr_path, token, accept="application/vnd.github.v3.diff")
    diff_truncated = len(diff.encode("utf-8")) > args.max_diff_bytes
    if diff_truncated:
        diff = diff.encode("utf-8")[: args.max_diff_bytes].decode("utf-8", errors="replace")

    context = {
        "repository": args.repository,
        "pr_number": args.pr_number,
        "pr": {
            "title": pr.get("title"),
            "body": pr.get("body"),
            "state": pr.get("state"),
            "base_ref": (pr.get("base") or {}).get("ref"),
            "base_sha": (pr.get("base") or {}).get("sha"),
            "base_repo": (((pr.get("base") or {}).get("repo") or {}).get("full_name")),
            "head_ref": (pr.get("head") or {}).get("ref"),
            "head_sha": head_sha,
            "head_repo": (((pr.get("head") or {}).get("repo") or {}).get("full_name")),
            "author": ((pr.get("user") or {}).get("login")),
            "html_url": pr.get("html_url"),
        },
        "files": files,
        "file_contents": collect_file_contents(args.repository, files, head_sha, head_tree_paths, token),
        "head_tree_paths": head_tree_paths,
        "changed_lines": {path: sorted(lines) for path, lines in changed_lines_by_file(files).items()},
        "diff": diff,
        "diff_truncated": diff_truncated,
        "skill": read_text_source(args.skill_file, "skill file", token),
        "rules": read_text_source(args.rules_file, "rules file", token),
        "reference_repos": {},
    }
    context["compliance_rules"] = build_compliance_prompt_context(load_compliance_catalog(), context)
    context["super_skill_rules"] = build_super_skill_prompt_context(
        load_super_skill_catalog(),
        context,
        enabled=bool_from_value(args.super_skill_enabled, True),
        max_rules=args.super_skill_max_rules,
    )

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as output_file:
        json.dump(context, output_file, indent=2, sort_keys=True)

    print(f"Collected context for PR #{args.pr_number} with {len(files)} changed files")
    if diff_truncated:
        print("PR diff was truncated before review context was sent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
