import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set


CATALOG_PATH = Path(__file__).resolve().parents[1] / "super_skill" / "super_skill_catalog.json"
SEVERITIES = ("critical", "high", "medium", "low")
STOPWORDS = {
    "agent",
    "against",
    "also",
    "best",
    "code",
    "from",
    "guidance",
    "review",
    "rule",
    "rules",
    "skill",
    "source",
    "that",
    "this",
    "using",
    "when",
    "with",
}


def load_super_skill_catalog(path: Optional[str] = None) -> Dict[str, Any]:
    catalog_path = Path(path) if path else CATALOG_PATH
    if not catalog_path.exists():
        return {"rules": [], "official_best_practice_rules": []}
    with catalog_path.open("r", encoding="utf-8") as input_file:
        data = json.load(input_file)
    if not isinstance(data, dict):
        return {"rules": [], "official_best_practice_rules": []}
    data.setdefault("rules", [])
    data.setdefault("official_best_practice_rules", [])
    return data


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


def tokenize(text: str) -> Set[str]:
    tokens = set()
    for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text.lower()):
        normalized = token.replace("_", "-").strip("-")
        if len(normalized) < 3 or normalized in STOPWORDS:
            continue
        tokens.add(normalized)
    return tokens


def context_tokens(changed_paths: Sequence[str], file_contents: Dict[str, str]) -> Set[str]:
    limited_content = " ".join(text[:3500] for text in file_contents.values())
    return tokenize(" ".join(changed_paths) + " " + limited_content)


def finding_text(finding: Dict[str, Any]) -> str:
    return " ".join(
        [
            str(finding.get("rule_id") or ""),
            str(finding.get("title") or ""),
            str(finding.get("body") or ""),
            str(finding.get("path") or ""),
            str(finding.get("source_line") or ""),
        ]
    )


def all_catalog_rules(catalog: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(catalog.get("official_best_practice_rules") or []) + list(catalog.get("rules") or [])


def score_rule(tokens: Set[str], rule: Dict[str, Any]) -> int:
    keywords = {str(item).lower() for item in (rule.get("keywords") or [])}
    if not keywords:
        keywords = tokenize(str(rule.get("title") or ""))
    return len(tokens & keywords)


def top_rules(tokens: Set[str], rules: Iterable[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    scored = []
    for rule in rules:
        score = score_rule(tokens, rule)
        if score <= 0:
            continue
        scored.append((score, str(rule.get("id") or ""), rule))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [
        {
            "id": rule.get("id"),
            "category": rule.get("category"),
            "source": rule.get("source") or rule.get("source_url"),
            "title": rule.get("title"),
            "source_url": rule.get("source_url"),
            "keywords": list(rule.get("keywords") or [])[:12],
            "artifacts": rule.get("artifacts") or {},
        }
        for _score, _rule_id, rule in scored[:limit]
    ]


def category_counts(rules: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    counts: Dict[str, int] = {}
    for rule in rules:
        category = str(rule.get("category") or "uncategorized")
        counts[category] = counts.get(category, 0) + 1
    return [{"category": key, "rule_count": counts[key]} for key in sorted(counts)]


def build_super_skill_prompt_context(
    catalog: Dict[str, Any],
    context: Dict[str, Any],
    *,
    enabled: bool = True,
    max_rules: int = 120,
) -> Dict[str, Any]:
    if not enabled:
        return {"enabled": False, "rules": [], "instructions": "Super Skill catalog context is disabled."}
    files = context.get("files") or []
    changed_paths = [str(item.get("filename") or "") for item in files if item.get("filename")]
    file_contents = {str(path): str(text) for path, text in (context.get("file_contents") or {}).items()}
    rules = all_catalog_rules(catalog)
    selected_rules = top_rules(context_tokens(changed_paths, file_contents), rules, max_rules)
    if not selected_rules:
        selected_rules = top_rules(tokenize(" ".join(changed_paths)), rules, max_rules)
    return {
        "enabled": True,
        "catalog_version": catalog.get("catalog_version"),
        "source_count": catalog.get("source_count"),
        "rule_count": catalog.get("rule_count") or len(rules),
        "category_counts": category_counts(rules),
        "selected_rule_count": len(selected_rules),
        "rules": selected_rules,
        "instructions": (
            "Apply matching super_skill_rules to the review. When a finding maps to these rules, "
            "include super_skill_rule_ids, super_skill_sources, and best_practice_rule_ids where applicable."
        ),
    }


def normalized_string_list(value: Any) -> List[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    items = []
    for item in value:
        if isinstance(item, dict):
            raw = item.get("id") or item.get("source") or item.get("name") or item.get("key")
        else:
            raw = item
        text = str(raw or "").strip()
        if text:
            items.append(text)
    return sorted(set(items))


def explicit_rule_ids(finding: Dict[str, Any]) -> Set[str]:
    values = []
    values.extend(normalized_string_list(finding.get("super_skill_rule_ids")))
    values.extend(normalized_string_list(finding.get("best_practice_rule_ids")))
    return set(values)


def best_rule_matches(
    finding: Dict[str, Any],
    catalog: Dict[str, Any],
    *,
    min_score: int = 2,
    max_rules: int = 5,
) -> List[Dict[str, Any]]:
    tokens = tokenize(finding_text(finding))
    explicit = explicit_rule_ids(finding)
    scored = []
    for rule in all_catalog_rules(catalog):
        rule_id = str(rule.get("id") or "")
        score = score_rule(tokens, rule)
        if rule_id in explicit:
            score += 100
        if score >= min_score or rule_id in explicit:
            scored.append((score, rule_id, rule))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [rule for _score, _rule_id, rule in scored[:max_rules]]


def apply_super_skill_mapping(result: Dict[str, Any], catalog: Dict[str, Any]) -> Dict[str, Any]:
    rules = all_catalog_rules(catalog)
    summary: Dict[str, Dict[str, Any]] = {}
    for rule in rules:
        category = str(rule.get("category") or "uncategorized")
        bucket = summary.setdefault(
            category,
            {
                "category": category,
                "loaded_rules": 0,
                "violations": 0,
                "blocking": 0,
                "warnings": 0,
                "critical": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
                "rule_ids": set(),
                "sources": set(),
            },
        )
        bucket["loaded_rules"] += 1

    for finding in result.get("findings") or []:
        matches = best_rule_matches(finding, catalog)
        if not matches:
            finding.setdefault("super_skill_rule_ids", normalized_string_list(finding.get("super_skill_rule_ids")))
            finding.setdefault("super_skill_sources", normalized_string_list(finding.get("super_skill_sources")))
            finding.setdefault("best_practice_rule_ids", normalized_string_list(finding.get("best_practice_rule_ids")))
            continue

        skill_ids = []
        source_names = []
        best_practice_ids = []
        seen_categories = set()
        for rule in matches:
            rule_id = str(rule.get("id") or "")
            category = str(rule.get("category") or "uncategorized")
            source_name = str(rule.get("source") or rule.get("source_url") or category)
            if rule_id.startswith("official."):
                best_practice_ids.append(rule_id)
            else:
                skill_ids.append(rule_id)
            source_names.append(source_name)
            bucket = summary.setdefault(
                category,
                {
                    "category": category,
                    "loaded_rules": 0,
                    "violations": 0,
                    "blocking": 0,
                    "warnings": 0,
                    "critical": 0,
                    "high": 0,
                    "medium": 0,
                    "low": 0,
                    "rule_ids": set(),
                    "sources": set(),
                },
            )
            if category not in seen_categories:
                bucket["violations"] += 1
                if bool_from_value(finding.get("blocks_merge"), False):
                    bucket["blocking"] += 1
                else:
                    bucket["warnings"] += 1
                severity = str(finding.get("severity") or "medium").lower()
                if severity in SEVERITIES:
                    bucket[severity] += 1
                seen_categories.add(category)
            bucket["rule_ids"].add(rule_id)
            bucket["sources"].add(source_name)

        finding["super_skill_rule_ids"] = sorted(set(normalized_string_list(finding.get("super_skill_rule_ids")) + skill_ids))
        finding["super_skill_sources"] = sorted(set(normalized_string_list(finding.get("super_skill_sources")) + source_names))
        finding["best_practice_rule_ids"] = sorted(set(normalized_string_list(finding.get("best_practice_rule_ids")) + best_practice_ids))

    result["super_skill_summary"] = {
        "categories": [
            {
                **{key: value for key, value in bucket.items() if key not in {"rule_ids", "sources"}},
                "distinct_rule_count": len(bucket["rule_ids"]),
                "rule_ids": sorted(bucket["rule_ids"])[:12],
                "sources": sorted(bucket["sources"])[:12],
            }
            for bucket in sorted(summary.values(), key=lambda item: str(item["category"]))
        ]
    }
    return result
