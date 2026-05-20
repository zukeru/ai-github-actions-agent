import hashlib
import json
import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
SEVERITY_BADGES = {
    "critical": "![critical](https://img.shields.io/badge/severity-critical-b00020)",
    "high": "![high](https://img.shields.io/badge/severity-high-d73a49)",
    "medium": "![medium](https://img.shields.io/badge/severity-medium-f66a0a)",
    "low": "![low](https://img.shields.io/badge/severity-low-2ea44f)",
}
SEVERITY_IMPACT = {
    "critical": "Must fix. Merge should be blocked.",
    "high": "Must fix unless explicitly risk-accepted.",
    "medium": "Warning. Track or fix, but do not block merge by default.",
    "low": "Advisory. Non-blocking guidance.",
}
VALID_SEVERITIES = set(SEVERITY_BADGES)
BLOCKING_SEVERITIES = {"critical", "high"}
NON_BLOCKING_WARNING_TYPES = {
    "code-quality",
    "compliance",
    "coverage",
    "dependency",
    "documentation",
    "public-runner",
    "reference-context",
    "supply-chain",
}
REVIEW_MARKER_PREFIX = "<!-- gha-agent-review:"
REVIEW_MARKER_SUFFIX = "-->"


def parse_trigger_phrases(raw: str) -> List[str]:
    return [phrase.strip().lower() for phrase in raw.split(",") if phrase.strip()]


def body_has_trigger(body: str, phrases: Iterable[str]) -> bool:
    lowered = body.lower()
    return any(phrase.lower() in lowered for phrase in phrases)


def changed_lines_from_patch(patch: str) -> Set[int]:
    changed: Set[int] = set()
    new_line: Optional[int] = None

    for line in patch.splitlines():
        match = HUNK_RE.match(line)
        if match:
            new_line = int(match.group(1))
            continue

        if new_line is None:
            continue

        if line.startswith("+") and not line.startswith("+++"):
            changed.add(new_line)
            new_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            continue
        else:
            new_line += 1

    return changed


def changed_line_sources_from_patch(patch: str) -> Dict[int, str]:
    sources: Dict[int, str] = {}
    new_line: Optional[int] = None

    for line in patch.splitlines():
        match = HUNK_RE.match(line)
        if match:
            new_line = int(match.group(1))
            continue

        if new_line is None:
            continue

        if line.startswith("+") and not line.startswith("+++"):
            sources[new_line] = line[1:]
            new_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            continue
        else:
            new_line += 1

    return sources


def changed_lines_by_file(files: Iterable[Dict[str, Any]]) -> Dict[str, Set[int]]:
    changed: Dict[str, Set[int]] = {}
    for file_info in files:
        filename = file_info.get("filename")
        patch = file_info.get("patch") or ""
        if filename:
            changed[filename] = changed_lines_from_patch(patch)
    return changed


def changed_line_sources_by_file(files: Iterable[Dict[str, Any]]) -> Dict[str, Dict[int, str]]:
    sources: Dict[str, Dict[int, str]] = {}
    for file_info in files:
        filename = file_info.get("filename")
        patch = file_info.get("patch") or ""
        if filename:
            sources[filename] = changed_line_sources_from_patch(patch)
    return sources


def language_for_path(path: Optional[str]) -> str:
    if not path:
        return "text"
    extension = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return {
        "js": "javascript",
        "jsx": "jsx",
        "ts": "typescript",
        "tsx": "tsx",
        "py": "python",
        "yml": "yaml",
        "yaml": "yaml",
        "json": "json",
        "sh": "bash",
        "bash": "bash",
        "md": "markdown",
        "tf": "hcl",
        "dockerfile": "dockerfile",
    }.get(extension, "text")


def severity_badge(severity: str) -> str:
    return SEVERITY_BADGES.get(severity.lower(), SEVERITY_BADGES["medium"])


def severity_legend_markdown() -> str:
    rows = ["| Severity | Visual | Merge guidance |", "| --- | --- | --- |"]
    for severity in ("critical", "high", "medium", "low"):
        rows.append(f"| `{severity}` | {severity_badge(severity)} | {SEVERITY_IMPACT[severity]} |")
    return "\n".join(rows)


def location_for_finding(finding: Dict[str, Any]) -> str:
    location = finding.get("path") or "PR"
    if finding.get("line"):
        location = f"{location}:{finding['line']}"
    return location


def bool_from_value(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return default


def finding_blocks_merge(finding: Dict[str, Any]) -> bool:
    warning_type = str(finding.get("warning_type") or "").strip().lower()
    severity = str(finding.get("severity") or "high").strip().lower()
    default = severity in BLOCKING_SEVERITIES and warning_type not in NON_BLOCKING_WARNING_TYPES
    return bool_from_value(finding.get("blocks_merge"), default)


def finding_fingerprint(finding: Dict[str, Any]) -> str:
    existing = str(finding.get("fingerprint") or "").strip()
    if existing:
        return existing

    payload = "|".join(
        [
            str(finding.get("rule_id") or "gha-agent-review").strip().lower(),
            str(finding.get("path") or "PR").strip().lower(),
            str(finding.get("title") or "").strip().lower(),
            re.sub(r"\s+", " ", str(finding.get("body") or "").strip().lower())[:160],
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def normalized_string_list(value: Any) -> List[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    items = []
    for item in value:
        if isinstance(item, dict):
            raw = item.get("key") or item.get("name") or item.get("framework")
        else:
            raw = item
        text = str(raw or "").strip()
        if text:
            items.append(text)
    return sorted(set(items))


def split_blocking_and_warnings(findings: Iterable[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    blocking: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    for finding in findings:
        if finding_blocks_merge(finding):
            blocking.append(finding)
        else:
            warnings.append(finding)
    return blocking, warnings


def marker_payload_from_body(body: str) -> Optional[Dict[str, Any]]:
    start = body.find(REVIEW_MARKER_PREFIX)
    if start < 0:
        return None
    start += len(REVIEW_MARKER_PREFIX)
    end = body.find(REVIEW_MARKER_SUFFIX, start)
    if end < 0:
        return None
    raw = body[start:end].strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def build_history_summary(result: Dict[str, Any], history: Optional[Dict[str, Any]] = None) -> Dict[str, int]:
    history = history or {}
    findings = list(result.get("findings", []))
    blocking, warnings = split_blocking_and_warnings(findings)

    current_blocking = {item["fingerprint"] for item in blocking if item.get("fingerprint")}
    previous_requested = set(history.get("requested_fingerprints") or [])
    requested = previous_requested | current_blocking
    fixed = previous_requested - current_blocking

    return {
        "requested": len(requested),
        "fixed": len(fixed),
        "remaining": len(current_blocking),
        "warnings": len(warnings),
        "blocking": len(blocking),
        "total": len(findings),
    }


def build_review_marker(result: Dict[str, Any], history: Optional[Dict[str, Any]] = None) -> str:
    history = history or {}
    blocking, warnings = split_blocking_and_warnings(result.get("findings", []))
    current_blocking = {item["fingerprint"] for item in blocking if item.get("fingerprint")}
    requested = set(history.get("requested_fingerprints") or []) | current_blocking
    payload = {
        "version": 1,
        "requested_fingerprints": sorted(requested),
        "current_blocking_fingerprints": sorted(current_blocking),
        "current_warning_fingerprints": sorted(
            item["fingerprint"] for item in warnings if item.get("fingerprint")
        ),
    }
    return f"{REVIEW_MARKER_PREFIX} {json.dumps(payload, sort_keys=True)} {REVIEW_MARKER_SUFFIX}"


def normalize_review_result(data: Dict[str, Any]) -> Dict[str, Any]:
    summary = str(data.get("summary") or "").strip()
    outcome = str(data.get("outcome") or "").strip().lower()
    raw_findings = data.get("findings", [])

    if not isinstance(raw_findings, list):
        raise ValueError("review result field 'findings' must be a list")

    findings = []
    for index, finding in enumerate(raw_findings, start=1):
        if not isinstance(finding, dict):
            raise ValueError(f"finding {index} must be an object")

        title = str(finding.get("title") or "").strip()
        body = str(finding.get("body") or "").strip()
        if not title or not body:
            raise ValueError(f"finding {index} must include title and body")

        line = finding.get("line")
        if line in ("", None):
            normalized_line = None
        else:
            try:
                normalized_line = int(line)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"finding {index} line must be an integer") from exc

        severity = str(finding.get("severity") or "high").strip().lower()
        if severity not in VALID_SEVERITIES:
            severity = "high"
        warning_type = str(finding.get("warning_type") or "").strip().lower() or None
        normalized = {
            "path": str(finding.get("path") or "").strip() or None,
            "line": normalized_line,
            "severity": severity,
            "rule_id": str(finding.get("rule_id") or "gha-agent-review").strip(),
            "title": title,
            "body": body,
            "suggestion": str(finding.get("suggestion") or "").strip() or None,
            "warning_type": warning_type,
            "compliance_frameworks": normalized_string_list(finding.get("compliance_frameworks")),
            "compliance_rule_ids": normalized_string_list(finding.get("compliance_rule_ids")),
            "super_skill_rule_ids": normalized_string_list(finding.get("super_skill_rule_ids")),
            "super_skill_sources": normalized_string_list(finding.get("super_skill_sources")),
            "best_practice_rule_ids": normalized_string_list(finding.get("best_practice_rule_ids")),
        }
        normalized["auto_fix"] = bool_from_value(finding.get("auto_fix"), False)
        normalized["blocks_merge"] = finding_blocks_merge({**finding, **normalized})
        if not normalized["blocks_merge"] and normalized["warning_type"] not in NON_BLOCKING_WARNING_TYPES:
            continue
        normalized["fingerprint"] = finding_fingerprint({**finding, **normalized})
        findings.append(normalized)

    blocking, _warnings = split_blocking_and_warnings(findings)
    if outcome not in {"pass", "fail"}:
        outcome = "fail" if blocking else "pass"
    if blocking:
        outcome = "fail"
    elif outcome == "fail":
        outcome = "pass"

    if not summary:
        summary = "GHA AI Agent review completed."

    return {"summary": summary, "outcome": outcome, "findings": findings}


def finding_to_comment_body(finding: Dict[str, Any]) -> str:
    location = location_for_finding(finding)
    language = language_for_path(finding.get("path"))
    compliance_frameworks = normalized_string_list(finding.get("compliance_frameworks"))
    compliance_rule_ids = normalized_string_list(finding.get("compliance_rule_ids"))
    super_skill_rule_ids = normalized_string_list(finding.get("super_skill_rule_ids"))
    best_practice_rule_ids = normalized_string_list(finding.get("best_practice_rule_ids"))
    super_skill_sources = normalized_string_list(finding.get("super_skill_sources"))
    parts = [
        f"{severity_badge(finding['severity'])} **{finding['title']}**",
        "",
        f"**Location:** `{location}`",
        f"**Rule:** `{finding['rule_id']}`",
        f"**Severity:** `{finding['severity']}`",
        f"**Merge impact:** `{'blocks merge' if finding_blocks_merge(finding) else 'warning only'}`",
        "",
        "**Current line**",
        "",
    ]
    if finding.get("warning_type"):
        parts.insert(5, f"**Warning type:** `{finding['warning_type']}`")
    if compliance_frameworks:
        parts.insert(6, f"**Compliance frameworks:** `{', '.join(compliance_frameworks)}`")
    if compliance_rule_ids:
        parts.insert(7, f"**Compliance rule IDs:** `{', '.join(compliance_rule_ids[:8])}`")
    if super_skill_rule_ids:
        parts.insert(8, f"**Super Skill rule IDs:** `{', '.join(super_skill_rule_ids[:8])}`")
    if best_practice_rule_ids:
        parts.insert(9, f"**Best-practice rule IDs:** `{', '.join(best_practice_rule_ids[:8])}`")
    if super_skill_sources:
        parts.insert(10, f"**Super Skill sources:** `{', '.join(super_skill_sources[:6])}`")

    if finding.get("source_line") is not None and finding.get("line"):
        parts.extend(
            [
                f"```{language}",
                f"{finding['line']} | {finding['source_line']}",
                "```",
            ]
        )
    else:
        parts.append("No changed-line source snippet was available for this finding.")

    parts.extend(["", "**Why this matters**", "", finding["body"], "", "**Recommended change**", ""])
    if finding.get("suggestion"):
        parts.extend(
            [
                "Apply this replacement or an equivalent fix that satisfies the rule:",
                "",
                f"```suggestion\n{finding['suggestion']}\n```",
            ]
        )
    else:
        parts.append("Update the cited code to satisfy the rule and add or adjust tests where behavior changes.")
    return "\n".join(parts)


def compliance_tables_markdown(result: Dict[str, Any]) -> List[str]:
    summary = result.get("compliance_summary") if isinstance(result.get("compliance_summary"), dict) else {}
    frameworks = summary.get("frameworks") if isinstance(summary.get("frameworks"), list) else []
    if not frameworks:
        return []

    lines = ["", "### Compliance Framework Violation Counts", ""]
    for framework in frameworks:
        name = str(framework.get("name") or framework.get("key") or "Framework")
        rule_ids = list(framework.get("rule_ids") or [])
        rule_text = ", ".join(f"`{rule_id}`" for rule_id in rule_ids[:12]) if rule_ids else "`none`"
        lines.extend(
            [
                f"#### {name}",
                "",
                "| Metric | Count |",
                "| --- | ---: |",
                f"| Catalog rules loaded | `{framework.get('total_rules', 0)}` |",
                f"| Violating findings | `{framework.get('violations', 0)}` |",
                f"| Distinct violated rules | `{framework.get('distinct_rule_count', 0)}` |",
                f"| Blocking findings | `{framework.get('blocking', 0)}` |",
                f"| Warning findings | `{framework.get('warnings', 0)}` |",
                f"| Critical | `{framework.get('critical', 0)}` |",
                f"| High | `{framework.get('high', 0)}` |",
                f"| Medium | `{framework.get('medium', 0)}` |",
                f"| Low | `{framework.get('low', 0)}` |",
                "",
                f"Matched rule IDs: {rule_text}",
                "",
            ]
        )
    return lines


def super_skill_tables_markdown(result: Dict[str, Any]) -> List[str]:
    summary = result.get("super_skill_summary") if isinstance(result.get("super_skill_summary"), dict) else {}
    categories = summary.get("categories") if isinstance(summary.get("categories"), list) else []
    if not categories:
        return []

    lines = ["", "### Super Skill Rule Coverage", ""]
    lines.extend(
        [
            "| Category | Loaded rules | Matched findings | Blocking | Warnings | Critical | High | Medium | Low | Distinct rules |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for category in categories:
        if not category.get("loaded_rules") and not category.get("violations"):
            continue
        lines.append(
            f"| `{category.get('category', 'uncategorized')}` "
            f"| `{category.get('loaded_rules', 0)}` "
            f"| `{category.get('violations', 0)}` "
            f"| `{category.get('blocking', 0)}` "
            f"| `{category.get('warnings', 0)}` "
            f"| `{category.get('critical', 0)}` "
            f"| `{category.get('high', 0)}` "
            f"| `{category.get('medium', 0)}` "
            f"| `{category.get('low', 0)}` "
            f"| `{category.get('distinct_rule_count', 0)}` |"
        )
    matched = [
        category
        for category in categories
        if category.get("violations") and (category.get("rule_ids") or category.get("sources"))
    ]
    if matched:
        lines.extend(["", "Matched Super Skill sources:"])
        for category in matched[:12]:
            sources = ", ".join(f"`{source}`" for source in list(category.get("sources") or [])[:8]) or "`none`"
            rule_ids = ", ".join(f"`{rule_id}`" for rule_id in list(category.get("rule_ids") or [])[:8]) or "`none`"
            lines.append(f"- `{category.get('category')}`: {sources}; rules: {rule_ids}")
    return lines


def build_review_body(
    result: Dict[str, Any],
    inline_count: int,
    summary_findings: Iterable[Dict[str, Any]],
    max_inline_comments: int,
    history: Optional[Dict[str, Any]] = None,
) -> str:
    findings = list(result["findings"])
    blocking, warnings = split_blocking_and_warnings(findings)
    summary = build_history_summary(result, history)
    resolved_all_blockers = summary["requested"] > 0 and summary["remaining"] == 0
    progress_title = "Changes Resolved" if resolved_all_blockers else "Requested vs Fixed"
    progress_rows = [
        "| Metric | Count |",
        "| --- | ---: |",
    ]
    if resolved_all_blockers:
        progress_rows.extend(
            [
                f"| Changes resolved | `{summary['fixed']}` |",
                f"| Tracked blockers | `{summary['requested']}` |",
                f"| Remaining blockers | `{summary['remaining']}` |",
                f"| Non-blocking warnings | `{summary['warnings']}` |",
            ]
        )
    else:
        progress_rows.extend(
            [
                f"| Requested blockers | `{summary['requested']}` |",
                f"| Fixed blockers | `{summary['fixed']}` |",
                f"| Remaining blockers | `{summary['remaining']}` |",
                f"| Non-blocking warnings | `{summary['warnings']}` |",
            ]
        )
    body = [
        "## GHA AI Agent Review",
        "",
        result["summary"],
        "",
        "### Severity Legend",
        "",
        severity_legend_markdown(),
        "",
        f"### {progress_title}",
        "",
        *progress_rows,
        "",
        f"Findings: `{len(findings)}`",
        f"Blocking findings: `{len(blocking)}`",
        f"Warnings: `{len(warnings)}`",
        f"Inline comments: `{inline_count}`",
        f"Inline comment limit: `{max_inline_comments}`",
    ]
    body.extend(compliance_tables_markdown(result))
    body.extend(super_skill_tables_markdown(result))

    summary_items = list(summary_findings)
    if summary_items:
        body.extend(["", "### Findings And Warnings Requiring Summary Review", ""])
        for item in summary_items:
            location = location_for_finding(item)
            impact = "blocks merge" if finding_blocks_merge(item) else "warning only"
            body.append(
                f"- {severity_badge(item['severity'])} **{item['title']}** at `{location}` "
                f"(`{impact}`) - {item['body']}"
            )

    auto_fix = result.get("auto_fix") if isinstance(result.get("auto_fix"), dict) else None
    if auto_fix:
        body.extend(["", "### Automatic Fix PR", ""])
        status = str(auto_fix.get("status") or "not-run")
        message = str(auto_fix.get("message") or "").strip()
        body.append(f"Status: `{status}`")
        if auto_fix.get("fix_branch"):
            body.append(f"Fix branch: `{auto_fix['fix_branch']}`")
        if auto_fix.get("fix_pr_url"):
            body.append(f"Fix PR: {auto_fix['fix_pr_url']}")
        body.append(f"Safe fixes applied: `{auto_fix.get('fix_count', 0)}`")
        body.append(f"README diagram added: `{str(bool(auto_fix.get('diagram_added'))).lower()}`")
        body.append(f"Architecture documentation added: `{str(bool(auto_fix.get('architecture_doc_added'))).lower()}`")
        if message:
            body.append(message)

    body.extend(["", build_review_marker(result, history)])
    return "\n".join(body)
