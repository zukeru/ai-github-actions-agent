#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set


STOPWORDS = {
    "about",
    "above",
    "across",
    "after",
    "against",
    "amazon",
    "assessment",
    "aws",
    "azure",
    "check",
    "cloud",
    "compliance",
    "control",
    "controls",
    "data",
    "ensure",
    "evaluate",
    "evidence",
    "framework",
    "from",
    "google",
    "infrastructure",
    "must",
    "review",
    "rule",
    "rules",
    "source",
    "that",
    "this",
    "using",
    "when",
    "where",
    "with",
}
TEXT_FIELDS = {
    "applicability",
    "assessment_logic",
    "automatable_checks",
    "category",
    "cloud_components",
    "cloud_mapping",
    "cloud_relevance",
    "controlDescription",
    "controlSummary",
    "control_family",
    "control_statement",
    "description",
    "evidence",
    "implementation_pattern",
    "normalized_resource_types",
    "plainEnglishObjective",
    "remediation_guidance",
    "riskThemes",
    "scan_assertions",
    "shared_responsibility",
    "summary",
    "title",
    "validation_checks",
    "validation_focus",
    "why_it_matters_for_validation",
}


def tokenize(text: str, limit: int = 32) -> List[str]:
    tokens: List[str] = []
    seen: Set[str] = set()
    for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text.lower()):
        normalized = token.replace("_", "-").strip("-")
        if len(normalized) < 4 or normalized in STOPWORDS or normalized in seen:
            continue
        seen.add(normalized)
        tokens.append(normalized)
        if len(tokens) >= limit:
            break
    return tokens


def flatten_selected(value: Any, depth: int = 0) -> str:
    if depth > 4:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return " ".join(flatten_selected(item, depth + 1) for item in value[:20])
    if isinstance(value, dict):
        parts = []
        for key, child in value.items():
            if str(key) in TEXT_FIELDS or depth > 0:
                parts.append(flatten_selected(child, depth + 1))
        return " ".join(parts)
    return ""


def normalize_rule(check: Dict[str, Any]) -> Dict[str, Any]:
    check_data = check.get("check_data") if isinstance(check.get("check_data"), dict) else {}
    rule_id = str(check.get("check_id") or check_data.get("id") or check_data.get("control_id") or "").strip()
    title = str(check.get("check_title") or check_data.get("title") or check_data.get("control_title") or rule_id).strip()
    source_file = str(check.get("source_file") or "").strip()
    text = " ".join(
        [
            rule_id,
            title,
            flatten_selected(check_data),
        ]
    )
    return {
        "id": rule_id,
        "title": title,
        "source_file": source_file,
        "keywords": tokenize(text),
    }


def load_framework(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as input_file:
        data = json.load(input_file)
    checks = data.get("checks") if isinstance(data.get("checks"), list) else []
    rules = [normalize_rule(check) for check in checks if isinstance(check, dict)]
    return {
        "key": data.get("framework_key"),
        "name": data.get("framework"),
        "total_rules": data.get("total_infrastructure_checks") or len(rules),
        "source_files": sorted({rule["source_file"] for rule in rules if rule["source_file"]}),
        "rules": rules,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    source_dir = Path(args.source_dir)
    frameworks = [
        load_framework(path)
        for path in sorted(source_dir.glob("*_infrastructure_compliance_rules.json"))
    ]
    catalog = {
        "catalog_version": 1,
        "source": "duplo-ai-compliance infrastructure compliance rules",
        "frameworks": frameworks,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as output_file:
        json.dump(catalog, output_file, indent=2, sort_keys=True)
        output_file.write("\n")
    print(f"Wrote {output} with {sum(len(item['rules']) for item in frameworks)} rules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
