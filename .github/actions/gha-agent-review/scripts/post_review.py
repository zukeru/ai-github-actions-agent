#!/usr/bin/env python3
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, List, Tuple

from auto_fix import bool_from_string, run_auto_fix
from compliance_rules import apply_compliance_mapping, load_compliance_catalog
from policy_checks import evaluate_policy, merge_policy_findings
from super_skill_rules import apply_super_skill_mapping, load_super_skill_catalog
from review_common import (
    build_history_summary,
    build_review_body,
    changed_line_sources_by_file,
    changed_lines_by_file,
    finding_to_comment_body,
    marker_payload_from_body,
    normalize_review_result,
    split_blocking_and_warnings,
)


API_ROOT = "https://api.github.com"


class GitHubApiError(RuntimeError):
    def __init__(self, status_code: int, path: str, details: str):
        super().__init__(f"GitHub API request failed: {status_code} {path}: {details}")
        self.status_code = status_code
        self.path = path
        self.details = details


def write_output(name: str, value: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as output_file:
            output_file.write(f"{name}={value}\n")
    else:
        print(f"{name}={value}")


def github_post(path: str, token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    request = urllib.request.Request(
        f"{API_ROOT}{path}",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
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
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise GitHubApiError(exc.code, path, details) from exc


def github_get(path: str, token: str) -> Any:
    request = urllib.request.Request(
        f"{API_ROOT}{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "gha-agent-review",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise GitHubApiError(exc.code, path, details) from exc


def paginated_get(path: str, token: str) -> List[Dict[str, Any]]:
    separator = "&" if "?" in path else "?"
    items: List[Dict[str, Any]] = []
    page = 1
    while True:
        current = github_get(f"{path}{separator}per_page=100&page={page}", token)
        if not current:
            return items
        items.extend(current)
        if len(current) < 100:
            return items
        page += 1


def post_issue_comment(token: str, repository: str, pr_number: int, body: str) -> None:
    github_post(f"/repos/{repository}/issues/{pr_number}/comments", token, {"body": body})


def load_previous_review_history(token: str, repository: str, pr_number: int) -> Dict[str, Any]:
    requested = set()
    current_blocking = set()
    current_warnings = set()

    sources = []
    try:
        sources.extend(paginated_get(f"/repos/{repository}/pulls/{pr_number}/reviews", token))
    except GitHubApiError:
        pass
    try:
        sources.extend(paginated_get(f"/repos/{repository}/issues/{pr_number}/comments", token))
    except GitHubApiError:
        pass

    for source in sources:
        body = str(source.get("body") or "")
        marker = marker_payload_from_body(body)
        if not marker:
            continue
        requested.update(str(item) for item in marker.get("requested_fingerprints") or [])
        current_blocking.update(str(item) for item in marker.get("current_blocking_fingerprints") or [])
        current_warnings.update(str(item) for item in marker.get("current_warning_fingerprints") or [])

    return {
        "requested_fingerprints": sorted(requested),
        "last_blocking_fingerprints": sorted(current_blocking),
        "last_warning_fingerprints": sorted(current_warnings),
    }


def can_not_request_changes_on_own_pr(exc: GitHubApiError) -> bool:
    return (
        exc.status_code == 422
        and "Can not request changes on your own pull request" in exc.details
    )


def can_not_approve_own_pr(exc: GitHubApiError) -> bool:
    details = exc.details.lower()
    return exc.status_code == 422 and "approve" in details and "own pull request" in details


def append_inline_comment_fallback(body: str, comments: List[Dict[str, Any]]) -> str:
    if not comments:
        return body

    fallback_items = []
    for comment in comments:
        fallback_items.append(f"- `{comment['path']}:{comment['line']}`\n\n{comment['body']}")

    return (
        body
        + "\n\nInline comments could not be submitted, so the intended inline findings are summarized here.\n\n"
        + "\n\n".join(fallback_items)
    )


def split_inline_findings(
    findings: List[Dict[str, Any]],
    changed_lines: Dict[str, set],
    max_inline_comments: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    inline = []
    summary = []

    for finding in findings:
        path = finding.get("path")
        line = finding.get("line")
        if (
            path
            and isinstance(line, int)
            and line in changed_lines.get(path, set())
            and len(inline) < max_inline_comments
        ):
            inline.append(finding)
        else:
            summary.append(finding)

    return inline, summary


def add_source_lines(findings: List[Dict[str, Any]], source_lines: Dict[str, Dict[int, str]]) -> None:
    for finding in findings:
        path = finding.get("path")
        line = finding.get("line")
        if path and isinstance(line, int):
            finding["source_line"] = source_lines.get(path, {}).get(line)


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as input_file:
        return json.load(input_file)


def submit_review(
    token: str,
    repository: str,
    pr_number: int,
    event: str,
    body: str,
    comments: List[Dict[str, Any]],
    commit_id: str,
) -> None:
    payload = {"event": event, "body": body, "comments": comments}
    if commit_id:
        payload["commit_id"] = commit_id
    try:
        github_post(f"/repos/{repository}/pulls/{pr_number}/reviews", token, payload)
    except GitHubApiError as exc:
        if event == "APPROVE" and can_not_approve_own_pr(exc):
            post_issue_comment(
                token,
                repository,
                pr_number,
                append_inline_comment_fallback(body, comments)
                + "\n\nGitHub would not allow this token to approve because it owns the PR. "
                "The workflow still passed because no blocking findings were found.",
            )
            return
        if event == "REQUEST_CHANGES" and can_not_request_changes_on_own_pr(exc):
            post_issue_comment(
                token,
                repository,
                pr_number,
                append_inline_comment_fallback(body, comments)
                + "\n\nGitHub would not allow this token to request changes because it owns the PR. "
                "The workflow still failed so the PR remains blocked by the check.",
            )
            return
        if not comments:
            raise
        fallback_body = append_inline_comment_fallback(body, comments)
        fallback_payload = {"event": event, "body": fallback_body, "comments": []}
        if commit_id:
            fallback_payload["commit_id"] = commit_id
        try:
            github_post(f"/repos/{repository}/pulls/{pr_number}/reviews", token, fallback_payload)
        except GitHubApiError as fallback_exc:
            if event == "REQUEST_CHANGES" and can_not_request_changes_on_own_pr(fallback_exc):
                post_issue_comment(
                    token,
                    repository,
                    pr_number,
                    fallback_body
                    + "\n\nGitHub would not allow this token to request changes because it owns the PR. "
                    "The workflow still failed so the PR remains blocked by the check.",
                )
                return
            raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pr-number", required=True, type=int)
    parser.add_argument("--context", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--max-inline-comments", required=True, type=int)
    parser.add_argument("--auto-fix-enabled", default="true")
    parser.add_argument("--coverage-warning-threshold", default="90")
    parser.add_argument("--add-readme-diagrams", default="true")
    parser.add_argument("--add-architecture-docs", default="true")
    parser.add_argument("--auto-fix-max-findings", default="25", type=int)
    parser.add_argument("--auto-fix-max-files", default="10", type=int)
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("GITHUB_TOKEN is required", file=sys.stderr)
        return 2

    context = load_json(args.context)
    context["coverage_warning_threshold"] = args.coverage_warning_threshold
    result = normalize_review_result(merge_policy_findings(load_json(args.result), evaluate_policy(context)))
    blocking_findings, warning_findings = split_blocking_and_warnings(result["findings"])
    history = load_previous_review_history(token, args.repository, args.pr_number)
    changed_lines = {path: set(lines) for path, lines in context.get("changed_lines", {}).items()}
    if not changed_lines:
        changed_lines = changed_lines_by_file(context.get("files", []))
    source_lines = changed_line_sources_by_file(context.get("files", []))
    add_source_lines(result["findings"], source_lines)
    result = apply_compliance_mapping(result, load_compliance_catalog())
    result = apply_super_skill_mapping(result, load_super_skill_catalog())
    result["auto_fix"] = run_auto_fix(
        token=token,
        repository=args.repository,
        context=context,
        result=result,
        enabled=bool_from_string(args.auto_fix_enabled, True),
        add_readme_diagrams=bool_from_string(args.add_readme_diagrams, True),
        add_architecture_docs=bool_from_string(args.add_architecture_docs, True),
        max_findings=args.auto_fix_max_findings,
        max_files=args.auto_fix_max_files,
    )

    inline_findings, summary_findings = split_inline_findings(
        result["findings"],
        changed_lines,
        args.max_inline_comments,
    )

    comments = [
        {
            "path": finding["path"],
            "line": finding["line"],
            "side": "RIGHT",
            "body": finding_to_comment_body(finding),
        }
        for finding in inline_findings
    ]

    review_state = "REQUEST_CHANGES" if blocking_findings else "APPROVE"
    review_body = build_review_body(result, len(comments), summary_findings, args.max_inline_comments, history)
    commit_id = str((context.get("pr") or {}).get("head_sha") or "")

    submit_review(token, args.repository, args.pr_number, review_state, review_body, comments, commit_id)

    write_output("finding-count", str(len(result["findings"])))
    write_output("blocking-finding-count", str(len(blocking_findings)))
    write_output("warning-count", str(len(warning_findings)))
    summary = build_history_summary(result, history)
    write_output("fixed-count", str(summary["fixed"]))
    write_output("requested-count", str(summary["requested"]))
    write_output("review-state", review_state)
    write_output("fix-pr-url", str(result["auto_fix"].get("fix_pr_url") or ""))
    write_output("fix-branch", str(result["auto_fix"].get("fix_branch") or ""))
    write_output("auto-fix-count", str(result["auto_fix"].get("fix_count") or 0))
    write_output("diagram-added", str(bool(result["auto_fix"].get("diagram_added"))).lower())
    write_output("architecture-doc-added", str(bool(result["auto_fix"].get("architecture_doc_added"))).lower())

    if review_state == "REQUEST_CHANGES":
        print(f"GHA AI Agent review requested changes with {len(blocking_findings)} blocking finding(s)")
        return 1

    print(f"GHA AI Agent review approved the PR with {len(warning_findings)} warning(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
