#!/usr/bin/env python3
import argparse
import json
import os
import re
from typing import Any, Dict, List

from gha_agent_review_agent.providers import invoke_provider, resolve_provider


JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def extract_json(text: str) -> Dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("{"):
        return json.loads(stripped)

    match = JSON_BLOCK_RE.search(stripped)
    if match:
        return json.loads(match.group(1))

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        return json.loads(stripped[start : end + 1])

    raise ValueError("Provider response did not contain a JSON object")


def build_prompt(context: Dict[str, Any]) -> str:
    files_summary = [
        {
            "filename": file_info.get("filename"),
            "status": file_info.get("status"),
            "additions": file_info.get("additions"),
            "deletions": file_info.get("deletions"),
            "changes": file_info.get("changes"),
        }
        for file_info in context.get("files", [])
    ]

    payload = {
        "repository": context.get("repository"),
        "pr_number": context.get("pr_number"),
        "pr": context.get("pr"),
        "files": files_summary,
        "changed_lines": context.get("changed_lines"),
        "head_tree_paths": context.get("head_tree_paths"),
        "reference_repos": summarize_reference_repos(context.get("reference_repos") or {}),
        "compliance_rules": context.get("compliance_rules"),
        "diff_truncated": context.get("diff_truncated"),
        "diff": context.get("diff"),
    }

    return f"""
Review this pull request according to the skill, compliance rules, and bundled Super Skill rules.

Return JSON only with this exact shape:
{{
  "summary": "short review summary",
  "outcome": "pass" | "fail",
  "findings": [
    {{
      "path": "changed/file.ext",
      "line": 123,
      "severity": "low" | "medium" | "high" | "critical",
      "blocks_merge": true | false,
      "warning_type": "public-runner|compliance|reference-context|optional",
      "rule_id": "security|reliability|maintainability|testing|operations|custom",
      "title": "short finding title",
      "body": "why this must change before merge",
      "suggestion": "optional replacement text",
      "auto_fix": false,
      "compliance_frameworks": ["gdpr", "hipaa", "hitrust", "iso27001", "nist_ai_rmf", "nist_sp80053r5", "pci_dss_v4_0_1", "soc2"],
      "compliance_rule_ids": ["matching framework rule IDs when applicable"],
      "super_skill_rule_ids": ["matching bundled skill rule IDs when applicable"],
      "super_skill_sources": ["matching skill or source names when applicable"],
      "best_practice_rule_ids": ["matching official best-practice rule IDs when applicable"]
    }}
  ]
}}

Rules:
- Report concrete critical/high issues that require a code or test change before merge with blocks_merge true.
- Report custom runner and advisory compliance concerns as non-blocking findings with blocks_merge false and warning_type set.
- For other medium/low concerns, include them only when they are useful, actionable, and tied to touched lines.
- Do not fail a PR for hypothetical future scale concerns, nice-to-have hardening, or requirements not present in the changed production surface.
- Prefer changed-line findings using new-file line numbers from changed_lines.
- Do not report findings on unchanged lines unless no changed line can carry the comment.
- Include a concrete suggestion when a safe automatic fix is obvious so a follow-up fixer can update the PR branch.
- Use compliance_rules.frameworks to map compliance-relevant findings to the listed framework keys and rule IDs.
- Include compliance_frameworks and compliance_rule_ids when a finding violates one or more framework rules.
- Use super_skill_rules.rules to apply the bundled Super Skill catalog relevant to this PR.
- Include super_skill_rule_ids, super_skill_sources, and best_practice_rule_ids when a finding maps to bundled skills or official best-practice rules.
- Use outcome "fail" only when at least one finding has blocks_merge true.
- Use outcome "pass" when no blocking findings remain, even if warning findings are present.
- Do not include markdown fences, prose outside JSON, or comments in the JSON.

Skill:
{context.get("skill", "")}

Compliance rules:
{context.get("rules", "")}

Super Skill catalog context:
{json.dumps(context.get("super_skill_rules") or {}, indent=2, sort_keys=True)}

Pull request payload:
{json.dumps(payload, indent=2, sort_keys=True)}
""".strip()


def summarize_reference_repos(reference_repos: Dict[str, Any]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {}
    for name, value in reference_repos.items():
        if name == "platform_defaults" and isinstance(value, dict):
            summary[name] = {
                platform: {
                    "repo": snapshot.get("repo"),
                    "path_prefix": snapshot.get("path_prefix"),
                    "paths": list(snapshot.get("paths") or [])[:80],
                    "error": snapshot.get("error"),
                }
                for platform, snapshot in value.items()
            }
            continue
        if isinstance(value, dict):
            summary[name] = {
                "repo": value.get("repo"),
                "path_prefix": value.get("path_prefix"),
                "paths": list(value.get("paths") or [])[:120],
                "error": value.get("error"),
            }
    return summary


def validate_result(result: Dict[str, Any]) -> Dict[str, Any]:
    summary = str(result.get("summary") or "GHA AI Agent review completed.").strip()
    outcome = str(result.get("outcome") or "").strip().lower()
    findings = result.get("findings", [])

    if not isinstance(findings, list):
        raise ValueError("findings must be a list")
    if outcome not in {"pass", "fail"}:
        outcome = "fail" if findings else "pass"
    if findings and outcome == "pass":
        outcome = "fail"

    normalized: List[Dict[str, Any]] = []
    blocking_count = 0
    for index, finding in enumerate(findings, start=1):
        if not isinstance(finding, dict):
            raise ValueError(f"finding {index} must be an object")
        severity = str(finding.get("severity") or "medium").lower()
        if severity not in {"critical", "high", "medium", "low"}:
            severity = "high"
        warning_type = str(finding.get("warning_type") or "").strip().lower() or None
        default_blocks = severity in {"critical", "high"} and warning_type not in {"compliance", "public-runner"}
        blocks_merge = finding.get("blocks_merge", default_blocks)
        if isinstance(blocks_merge, str):
            blocks_merge = blocks_merge.strip().lower() not in {"false", "0", "no", "off"}
        blocks_merge = bool(blocks_merge)
        if blocks_merge:
            blocking_count += 1
        normalized.append(
            {
                "path": finding.get("path"),
                "line": finding.get("line"),
                "severity": severity,
                "blocks_merge": blocks_merge,
                "warning_type": warning_type,
                "rule_id": finding.get("rule_id") or "gha-agent-review",
                "title": finding.get("title") or f"Finding {index}",
                "body": finding.get("body") or "This issue must be corrected before merge.",
                "suggestion": finding.get("suggestion"),
                "auto_fix": finding.get("auto_fix"),
                "compliance_frameworks": finding.get("compliance_frameworks") or [],
                "compliance_rule_ids": finding.get("compliance_rule_ids") or [],
                "super_skill_rule_ids": finding.get("super_skill_rule_ids") or [],
                "super_skill_sources": finding.get("super_skill_sources") or [],
                "best_practice_rule_ids": finding.get("best_practice_rule_ids") or [],
            }
        )

    return {"summary": summary, "outcome": "fail" if blocking_count else "pass", "findings": normalized}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    parser.add_argument("--model-id", default="")
    parser.add_argument("--aws-region", default="")
    parser.add_argument("--provider", default="auto")
    parser.add_argument("--azure-openai-endpoint", default="")
    parser.add_argument("--azure-openai-api-version", default="")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    with open(args.context, "r", encoding="utf-8") as context_file:
        context = json.load(context_file)

    config = resolve_provider(
        provider=args.provider,
        model_id=args.model_id,
        aws_region=args.aws_region,
        azure_openai_endpoint=args.azure_openai_endpoint,
        azure_openai_api_version=args.azure_openai_api_version,
    )
    result = validate_result(extract_json(invoke_provider(config, build_prompt(context))))

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as output_file:
        json.dump(result, output_file, indent=2, sort_keys=True)

    print(f"Review agent completed with {len(result['findings'])} finding(s) using provider {config.provider}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
