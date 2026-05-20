---
name: gha-ai-agent-super-skill
description: Use when refreshing or applying the bundled GHA AI Agent Super Skill catalog for broad PR review, compliance, security, code quality, cloud, IaC, package, testing, and documentation coverage.
---

# GHA AI Agent Super Skill

Created by Grant Zukel for using Claude skills in a GitHub Action.

## Purpose

This setup skill keeps the GitHub Action self-contained while allowing it to use public Claude-skill guidance, official best-practice rules, compliance catalogs, and deterministic review behavior. Runtime PR reviews must use the bundled generated catalog only; they must not install external skills, clone repositories, or execute third-party scripts.

## Refresh Flow

1. Run `python tools/build_super_skill_catalog.py --clean-cache` from the repository root.
2. Review `.github/actions/gha-agent-review/super_skill/source_manifest.json` for every source URL, pinned commit, license, and extraction error.
3. Review `.github/actions/gha-agent-review/super_skill/super_skill_catalog.json` for relevant categories, rule IDs, official best-practice rules, and artifact metadata.
4. Keep incompatible or unknown-license sources as metadata-only. Do not vendor or execute their scripts.
5. Run the Python tests, `py_compile`, `git diff --check`, and the repository term sweep before committing.

## Runtime Rules

- Treat bundled scripts, MCP descriptors, references, and agents as review guidance unless explicitly allowlisted in repository code.
- Select only relevant Super Skill rules for the PR surface to control prompt size.
- Findings that map to the catalog should include `super_skill_rule_ids`, `super_skill_sources`, and `best_practice_rule_ids`.
- Official source rules should be preferred when a marketplace skill conflicts with a primary-source security, compliance, CI/CD, or language rule.
- Continue to map compliance findings to the infrastructure compliance catalog and render one count table per framework.

## Safety

- Never execute third-party downloaded scripts during PR review.
- Never rely on live internet access during PR review.
- Pin every cloned source to a commit SHA.
- Preserve source attribution and license metadata.
- Apply automatic fixes only when they are deterministic, minimal, and safe for a fix PR.
