import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple


CATALOG_PATH = Path(__file__).resolve().parents[1] / "compliance" / "infrastructure_compliance_catalog.json"
SEVERITIES = ("critical", "high", "medium", "low")
STOPWORDS = {
    "about",
    "above",
    "across",
    "after",
    "against",
    "also",
    "amazon",
    "before",
    "being",
    "between",
    "cloud",
    "compliance",
    "control",
    "controls",
    "data",
    "during",
    "ensure",
    "from",
    "have",
    "into",
    "must",
    "only",
    "review",
    "rule",
    "rules",
    "should",
    "that",
    "their",
    "there",
    "these",
    "this",
    "those",
    "through",
    "using",
    "when",
    "where",
    "with",
    "within",
}


def load_compliance_catalog(path: Optional[str] = None) -> Dict[str, Any]:
    catalog_path = Path(path) if path else CATALOG_PATH
    if not catalog_path.exists():
        return {"frameworks": []}
    with catalog_path.open("r", encoding="utf-8") as input_file:
        data = json.load(input_file)
    if not isinstance(data, dict) or not isinstance(data.get("frameworks"), list):
        return {"frameworks": []}
    return data


def tokenize(text: str) -> Set[str]:
    tokens = set()
    for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text.lower()):
        normalized = token.replace("_", "-").strip("-")
        if len(normalized) < 4 or normalized in STOPWORDS:
            continue
        tokens.add(normalized)
    return tokens


def finding_text(finding: Dict[str, Any]) -> str:
    parts = [
        str(finding.get("rule_id") or ""),
        str(finding.get("title") or ""),
        str(finding.get("body") or ""),
        str(finding.get("path") or ""),
        str(finding.get("source_line") or ""),
    ]
    return " ".join(parts)


def framework_summaries(catalog: Dict[str, Any]) -> List[Dict[str, Any]]:
    summaries = []
    for framework in catalog.get("frameworks") or []:
        rules = framework.get("rules") if isinstance(framework.get("rules"), list) else []
        summaries.append(
            {
                "key": framework.get("key"),
                "name": framework.get("name"),
                "total_rules": framework.get("total_rules") or len(rules),
                "source_files": framework.get("source_files") or [],
            }
        )
    return summaries


def context_tokens(changed_paths: Sequence[str], file_contents: Dict[str, str]) -> Set[str]:
    limited_content = " ".join(text[:4000] for text in file_contents.values())
    return tokenize(" ".join(changed_paths) + " " + limited_content)


def score_rule(tokens: Set[str], rule: Dict[str, Any]) -> int:
    keywords = set(str(item).lower() for item in (rule.get("keywords") or []))
    if not keywords:
        keywords = tokenize(str(rule.get("title") or ""))
    return len(tokens & keywords)


def top_rules_for_framework(tokens: Set[str], framework: Dict[str, Any], limit: int = 12) -> List[Dict[str, Any]]:
    scored = []
    for rule in framework.get("rules") or []:
        score = score_rule(tokens, rule)
        if score <= 0:
            continue
        scored.append((score, str(rule.get("id") or ""), rule))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [
        {
            "id": rule.get("id"),
            "title": rule.get("title"),
            "keywords": list(rule.get("keywords") or [])[:12],
        }
        for _score, _rule_id, rule in scored[:limit]
    ]


def build_compliance_prompt_context(catalog: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    files = context.get("files") or []
    changed_paths = [str(item.get("filename") or "") for item in files if item.get("filename")]
    file_contents = {str(path): str(text) for path, text in (context.get("file_contents") or {}).items()}
    tokens = context_tokens(changed_paths, file_contents)
    frameworks = []
    for framework in catalog.get("frameworks") or []:
        frameworks.append(
            {
                "key": framework.get("key"),
                "name": framework.get("name"),
                "total_rules": framework.get("total_rules"),
                "matching_rules": top_rules_for_framework(tokens, framework, limit=12),
            }
        )
    return {
        "catalog_version": catalog.get("catalog_version"),
        "frameworks": frameworks,
        "instructions": (
            "For compliance-relevant findings, include compliance_frameworks with framework keys and "
            "compliance_rule_ids with matched rule IDs from the catalog when applicable."
        ),
    }


def normalize_framework_key(value: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", value.strip().lower()).strip("_")


def explicit_framework_keys(finding: Dict[str, Any]) -> Set[str]:
    values = finding.get("compliance_frameworks") or finding.get("compliance") or []
    if isinstance(values, str):
        values = [values]
    keys = set()
    if not isinstance(values, list):
        return keys
    for item in values:
        if isinstance(item, dict):
            raw = item.get("key") or item.get("framework") or item.get("name")
        else:
            raw = item
        if raw:
            keys.add(normalize_framework_key(str(raw)))
    return keys


def explicit_rule_ids(finding: Dict[str, Any]) -> List[str]:
    values = finding.get("compliance_rule_ids") or finding.get("compliance_rules") or []
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []
    return [str(item).strip() for item in values if str(item).strip()]


def best_framework_matches(
    finding: Dict[str, Any],
    catalog: Dict[str, Any],
    min_score: int = 2,
    max_rules_per_framework: int = 3,
) -> Dict[str, List[str]]:
    tokens = tokenize(finding_text(finding))
    explicit_keys = explicit_framework_keys(finding)
    explicit_rules = explicit_rule_ids(finding)
    matches: Dict[str, List[str]] = {}
    for framework in catalog.get("frameworks") or []:
        key = str(framework.get("key") or "")
        key_norm = normalize_framework_key(key)
        scored = []
        for rule in framework.get("rules") or []:
            rule_id = str(rule.get("id") or "")
            score = score_rule(tokens, rule)
            if rule_id in explicit_rules:
                score += 100
            if score >= min_score or key_norm in explicit_keys:
                scored.append((score, rule_id))
        scored.sort(key=lambda item: (-item[0], item[1]))
        if scored:
            matches[key] = [rule_id for _score, rule_id in scored[:max_rules_per_framework] if rule_id]
    return matches


def framework_name_by_key(catalog: Dict[str, Any]) -> Dict[str, str]:
    return {
        str(framework.get("key") or ""): str(framework.get("name") or framework.get("key") or "")
        for framework in catalog.get("frameworks") or []
    }


def total_rules_by_key(catalog: Dict[str, Any]) -> Dict[str, int]:
    return {
        str(framework.get("key") or ""): int(framework.get("total_rules") or len(framework.get("rules") or []))
        for framework in catalog.get("frameworks") or []
    }


def apply_compliance_mapping(result: Dict[str, Any], catalog: Dict[str, Any]) -> Dict[str, Any]:
    if not catalog.get("frameworks"):
        result["compliance_summary"] = {"frameworks": []}
        return result

    names = framework_name_by_key(catalog)
    totals = total_rules_by_key(catalog)
    summary: Dict[str, Dict[str, Any]] = {
        key: {
            "key": key,
            "name": names[key],
            "total_rules": totals[key],
            "violations": 0,
            "blocking": 0,
            "warnings": 0,
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "rule_ids": set(),
        }
        for key in names
    }

    for finding in result.get("findings") or []:
        matches = best_framework_matches(finding, catalog)
        frameworks = []
        for key, rule_ids in matches.items():
            if key not in summary:
                continue
            frameworks.append({"key": key, "name": names[key], "rule_ids": rule_ids})
            bucket = summary[key]
            bucket["violations"] += 1
            if bool(finding.get("blocks_merge")):
                bucket["blocking"] += 1
            else:
                bucket["warnings"] += 1
            severity = str(finding.get("severity") or "medium").lower()
            if severity in SEVERITIES:
                bucket[severity] += 1
            bucket["rule_ids"].update(rule_ids)
        finding["compliance_frameworks"] = frameworks
        finding["compliance_rule_ids"] = sorted({rule_id for item in frameworks for rule_id in item["rule_ids"]})

    result["compliance_summary"] = {
        "frameworks": [
            {
                **{key: value for key, value in bucket.items() if key != "rule_ids"},
                "distinct_rule_count": len(bucket["rule_ids"]),
                "rule_ids": sorted(bucket["rule_ids"])[:12],
            }
            for bucket in summary.values()
        ]
    }
    return result
