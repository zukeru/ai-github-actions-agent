#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
SUPER_SKILL_DIR = REPO_ROOT / ".github" / "actions" / "gha-agent-review" / "super_skill"
DEFAULT_MANIFEST_PATH = SUPER_SKILL_DIR / "source_manifest.json"
DEFAULT_CATALOG_PATH = SUPER_SKILL_DIR / "super_skill_catalog.json"
COMPATIBLE_LICENSES = {
    "apache-2.0",
    "bsd",
    "cc0",
    "isc",
    "mit",
    "mpl-2.0",
    "unlicense",
}


DEFAULT_SOURCES: List[Dict[str, str]] = [
    {"skill_name": "csv-data-summarizer", "category": "data-analysis", "url": "https://github.com/coffeefuelbump/csv-data-summarizer-claude-skill"},
    {"skill_name": "root-cause-tracing", "category": "debugging", "url": "https://github.com/obra/superpowers-skills/tree/main/skills/debugging/root-cause-tracing"},
    {"skill_name": "postgres", "category": "data", "url": "https://github.com/sanjay3290/ai-skills/tree/main/skills/postgres"},
    {"skill_name": "read-only-postgres", "category": "data", "url": "https://github.com/jawwadfirdousi/agent-skills"},
    {"skill_name": "prompt-template-wizard", "category": "planning", "url": "https://github.com/jawwadfirdousi/agent-skills"},
    {"skill_name": "grill-with-docs", "category": "planning", "url": "https://github.com/mattpocock/skills/tree/main/skills/engineering/grill-with-docs"},
    {"skill_name": "tdd", "category": "testing", "url": "https://github.com/mattpocock/skills/tree/main/skills/engineering/tdd"},
    {"skill_name": "diagnose", "category": "debugging", "url": "https://github.com/mattpocock/skills/tree/main/skills/engineering/diagnose"},
    {"skill_name": "to-prd", "category": "planning", "url": "https://github.com/mattpocock/skills/tree/main/skills/engineering/to-prd"},
    {"skill_name": "to-issues", "category": "planning", "url": "https://github.com/mattpocock/skills/tree/main/skills/engineering/to-issues"},
    {"skill_name": "zoom-out", "category": "architecture", "url": "https://github.com/mattpocock/skills/tree/main/skills/engineering/zoom-out"},
    {"skill_name": "triage", "category": "workflow", "url": "https://github.com/mattpocock/skills/tree/main/skills/engineering/triage"},
    {"skill_name": "prototype", "category": "engineering", "url": "https://github.com/mattpocock/skills/tree/main/skills/engineering/prototype"},
    {"skill_name": "improve-codebase-architecture", "category": "architecture", "url": "https://github.com/mattpocock/skills/tree/main/skills/engineering/improve-codebase-architecture"},
    {"skill_name": "setup-matt-pocock-skills", "category": "workflow", "url": "https://github.com/mattpocock/skills/tree/main/skills/engineering/setup-matt-pocock-skills"},
    {"skill_name": "interview-me", "category": "planning", "url": "https://github.com/addyosmani/agent-skills/tree/main/skills/interview-me"},
    {"skill_name": "source-driven-development", "category": "engineering", "url": "https://github.com/addyosmani/agent-skills/tree/main/skills/source-driven-development"},
    {"skill_name": "performance-optimization", "category": "performance", "url": "https://github.com/addyosmani/agent-skills/tree/main/skills/performance-optimization"},
    {"skill_name": "code-review-and-quality", "category": "code-quality", "url": "https://github.com/addyosmani/agent-skills/tree/main/skills/code-review-and-quality"},
    {"skill_name": "incremental-implementation", "category": "engineering", "url": "https://github.com/addyosmani/agent-skills/tree/main/skills/incremental-implementation"},
    {"skill_name": "planning-and-task-breakdown", "category": "planning", "url": "https://github.com/addyosmani/agent-skills/tree/main/skills/planning-and-task-breakdown"},
    {"skill_name": "swiftui-pro", "category": "mobile", "url": "https://github.com/twostraws/SwiftUI-Agent-Skill/tree/main/swiftui-pro"},
    {"skill_name": "swift-concurrency-pro", "category": "mobile", "url": "https://github.com/twostraws/Swift-Concurrency-Agent-Skill/tree/main/swift-concurrency-pro"},
    {"skill_name": "react-components-stitch", "category": "react", "url": "https://github.com/google-labs-code/stitch-skills/tree/main/skills/react-components"},
    {"skill_name": "mcp-builder", "category": "mcp", "url": "https://github.com/anthropics/skills/tree/main/skills/mcp-builder"},
    {"skill_name": "changelog-generator", "category": "docs", "url": "https://github.com/ComposioHQ/awesome-claude-skills/tree/master/changelog-generator"},
    {"skill_name": "using-git-worktrees", "category": "git", "url": "https://github.com/obra/superpowers/tree/main/skills/using-git-worktrees"},
    {"skill_name": "test-driven-development", "category": "testing", "url": "https://github.com/obra/superpowers/tree/main/skills/test-driven-development"},
    {"skill_name": "subagent-driven-development", "category": "workflow", "url": "https://github.com/obra/superpowers/tree/main/skills/subagent-driven-development"},
    {"skill_name": "executing-plans", "category": "workflow", "url": "https://github.com/obra/superpowers/tree/main/skills/executing-plans"},
    {"skill_name": "finishing-a-development-branch", "category": "git", "url": "https://github.com/obra/superpowers/tree/main/skills/finishing-a-development-branch"},
    {"skill_name": "preserving-productive-tensions", "category": "architecture", "url": "https://github.com/obra/superpowers-skills/tree/main/skills/architecture/preserving-productive-tensions"},
    {"skill_name": "web-artifacts-builder", "category": "frontend", "url": "https://github.com/anthropics/skills/tree/main/skills/web-artifacts-builder"},
    {"skill_name": "pypict-claude-skill", "category": "testing", "url": "https://github.com/omkamal/pypict-claude-skill"},
    {"skill_name": "aws-skills", "category": "aws", "url": "https://github.com/zxkane/aws-skills"},
    {"skill_name": "move-code-quality-skill", "category": "code-quality", "url": "https://github.com/1NickPappas/move-code-quality-skill"},
    {"skill_name": "audit-website", "category": "security", "url": "https://github.com/squirrelscan/skills/tree/main"},
    {"skill_name": "stripe-best-practices", "category": "payments", "url": "https://github.com/stripe/ai/tree/main/skills/stripe-best-practices"},
    {"skill_name": "upgrade-stripe", "category": "payments", "url": "https://github.com/stripe/ai/tree/main/skills/upgrade-stripe"},
    {"skill_name": "expo-app-design", "category": "mobile", "url": "https://github.com/expo/skills"},
    {"skill_name": "supabase-postgres", "category": "data", "url": "https://github.com/supabase/agent-skills"},
    {"skill_name": "terraform-code-generation", "category": "iac", "url": "https://github.com/hashicorp/agent-skills/tree/main/terraform/code-generation"},
    {"skill_name": "terraform-module-generation", "category": "iac", "url": "https://github.com/hashicorp/agent-skills/tree/main/terraform/module-generation"},
    {"skill_name": "terraform-provider-development", "category": "iac", "url": "https://github.com/hashicorp/agent-skills/tree/main/terraform/provider-development"},
    {"skill_name": "terraform-skill", "category": "iac", "url": "https://github.com/antonbabenko/terraform-skill"},
    {"skill_name": "cloudflare-agents-sdk", "category": "cloudflare", "url": "https://github.com/cloudflare/skills/tree/main/skills/agents-sdk"},
    {"skill_name": "cloudflare-wrangler", "category": "cloudflare", "url": "https://github.com/cloudflare/skills/tree/main/skills/wrangler"},
    {"skill_name": "cloudflare-web-perf", "category": "performance", "url": "https://github.com/cloudflare/skills/tree/main/skills/web-perf"},
    {"skill_name": "cloudflare-building-ai-agent", "category": "ai-agent", "url": "https://github.com/cloudflare/skills/blob/main/commands/build-agent.md"},
    {"skill_name": "cloudflare-building-mcp-server", "category": "mcp", "url": "https://github.com/cloudflare/skills/blob/main/commands/build-mcp.md"},
    {"skill_name": "cloudflare-durable-objects", "category": "cloudflare", "url": "https://github.com/cloudflare/skills/tree/main/skills/durable-objects"},
    {"skill_name": "cloudflare-sandbox-sdk", "category": "security", "url": "https://github.com/cloudflare/skills/tree/main/skills/sandbox-sdk"},
    {"skill_name": "cloudflare-workers-best-practices", "category": "cloudflare", "url": "https://github.com/cloudflare/skills/tree/main/skills/workers-best-practices"},
    {"skill_name": "netlify-functions", "category": "serverless", "url": "https://github.com/netlify/context-and-tools"},
    {"skill_name": "netlify-db", "category": "data", "url": "https://github.com/netlify/context-and-tools"},
    {"skill_name": "neon-postgres", "category": "data", "url": "https://github.com/neondatabase/agent-skills"},
    {"skill_name": "vercel-react", "category": "react", "url": "https://github.com/vercel-labs/agent-skills"},
    {"skill_name": "next-best-practices", "category": "nextjs", "url": "https://github.com/vercel-labs/next-skills"},
    {"skill_name": "next-upgrade", "category": "nextjs", "url": "https://github.com/vercel-labs/next-skills"},
    {"skill_name": "react-native-best-practices", "category": "mobile", "url": "https://github.com/callstackincubator/agent-skills"},
    {"skill_name": "better-auth", "category": "auth", "url": "https://github.com/better-auth/skills"},
    {"skill_name": "tinybird", "category": "data", "url": "https://github.com/tinybirdco/tinybird-agent-skills"},
    {"skill_name": "sanity", "category": "cms", "url": "https://github.com/sanity-io/agent-toolkit"},
    {"skill_name": "clickhouse", "category": "data", "url": "https://github.com/ClickHouse/agent-skills"},
    {"skill_name": "remotion-skill", "category": "video", "url": "https://github.com/remotion-dev/skills"},
    {"skill_name": "ios-simulator-skill", "category": "mobile-testing", "url": "https://github.com/conorluddy/ios-simulator-skill"},
    {"skill_name": "claude-d3js-skill", "category": "visualization", "url": "https://github.com/chrisvoncsefalvay/claude-d3js-skill"},
    {"skill_name": "playwright-skill", "category": "testing", "url": "https://github.com/lackeyjb/playwright-skill"},
    {"skill_name": "claude-a11y-skill", "category": "accessibility", "url": "https://github.com/airowe/claude-a11y-skill"},
    {"skill_name": "context-engineering-kit", "category": "ai-agent", "url": "https://github.com/NeoLabHQ/context-engineering-kit"},
    {"skill_name": "compound-engineering-plugin", "category": "engineering", "url": "https://github.com/EveryInc/compound-engineering-plugin"},
    {"skill_name": "algorithmic-art", "category": "visual", "url": "https://github.com/anthropics/skills/tree/main/skills/algorithmic-art"},
    {"skill_name": "canvas-design", "category": "visual", "url": "https://github.com/anthropics/skills/tree/main/skills/canvas-design"},
    {"skill_name": "slack-gif-creator", "category": "visual", "url": "https://github.com/anthropics/skills/tree/main/skills/slack-gif-creator"},
    {"skill_name": "brand-guidelines", "category": "visual", "url": "https://github.com/anthropics/skills/tree/main/skills/brand-guidelines"},
    {"skill_name": "theme-factory", "category": "visual", "url": "https://github.com/anthropics/skills/tree/main/skills/theme-factory"},
    {"skill_name": "nano-banana-image-generation", "category": "visual", "url": "https://github.com/livelabs-ventures/nano-skills/tree/main/skills/nano-image-generator"},
    {"skill_name": "frontend-slides", "category": "frontend", "url": "https://github.com/zarazhangrui/frontend-slides"},
    {"skill_name": "web-asset-generator", "category": "frontend", "url": "https://github.com/alonw0/web-asset-generator"},
    {"skill_name": "color-expert", "category": "accessibility", "url": "https://github.com/meodai/skill.color-expert"},
]


OFFICIAL_BEST_PRACTICE_RULES: List[Dict[str, Any]] = [
    {
        "id": "official.github-actions.secure-use",
        "category": "github-actions",
        "title": "Harden GitHub Actions against untrusted input and overprivileged tokens",
        "source_url": "https://docs.github.com/en/actions/reference/security/secure-use",
        "keywords": ["github", "actions", "permissions", "pull_request_target", "secrets", "runner", "workflow"],
    },
    {
        "id": "official.github-actions.oidc",
        "category": "github-actions",
        "title": "Prefer OIDC short-lived cloud credentials over long-lived deployment secrets",
        "source_url": "https://docs.github.com/en/actions/concepts/security/openid-connect",
        "keywords": ["oidc", "id-token", "cloud", "credentials", "federation", "aws", "azure", "google"],
    },
    {
        "id": "official.owasp.code-review",
        "category": "application-security",
        "title": "Use OWASP code review coverage for input validation, auth, injection, sessions, logging, and data protection",
        "source_url": "https://owasp.org/www-project-code-review-guide/",
        "keywords": ["owasp", "injection", "authentication", "authorization", "xss", "csrf", "session", "validation"],
    },
    {
        "id": "official.owasp.asvs",
        "category": "application-security",
        "title": "Map security-sensitive application changes to ASVS-style verification controls",
        "source_url": "https://owasp.org/www-project-application-security-verification-standard/",
        "keywords": ["asvs", "verification", "controls", "auth", "session", "api", "crypto", "validation"],
    },
    {
        "id": "official.kubernetes.pod-security",
        "category": "kubernetes",
        "title": "Apply Kubernetes Pod Security Standards and avoid privileged container defaults",
        "source_url": "https://kubernetes.io/docs/concepts/security/pod-security-standards/",
        "keywords": ["kubernetes", "pod", "securitycontext", "privileged", "capabilities", "hostpath", "runasnonroot"],
    },
    {
        "id": "official.kubernetes.security-checklist",
        "category": "kubernetes",
        "title": "Review workload, network, RBAC, image, secret, and cluster hardening with the Kubernetes security checklist",
        "source_url": "https://kubernetes.io/docs/concepts/security/security-checklist/",
        "keywords": ["kubernetes", "networkpolicy", "rbac", "serviceaccount", "secret", "image", "admission"],
    },
    {
        "id": "official.docker.build-best-practices",
        "category": "containers",
        "title": "Use Docker build best practices for minimal, reproducible, non-secret container images",
        "source_url": "https://docs.docker.com/build/building/best-practices/",
        "keywords": ["dockerfile", "docker", "image", "base", "layer", "build", "cache", "secret"],
    },
    {
        "id": "official.aws.security-pillar",
        "category": "aws",
        "title": "Apply AWS Well-Architected security patterns for identity, detection, infrastructure, data, and incident response",
        "source_url": "https://docs.aws.amazon.com/wellarchitected/latest/security-pillar/welcome.html",
        "keywords": ["aws", "iam", "cloudtrail", "kms", "s3", "securitygroup", "well-architected"],
    },
    {
        "id": "official.azure.waf-security",
        "category": "azure",
        "title": "Apply Azure Well-Architected security guidance for identity, network, data, operations, and governance",
        "source_url": "https://learn.microsoft.com/en-us/azure/well-architected/security/",
        "keywords": ["azure", "managed identity", "key vault", "rbac", "private endpoint", "diagnostic"],
    },
    {
        "id": "official.google-cloud.architecture-security",
        "category": "google-cloud",
        "title": "Apply Google Cloud Architecture Framework security principles for IAM, data, network, logging, and supply chain",
        "source_url": "https://docs.cloud.google.com/architecture/framework/security",
        "keywords": ["google", "gcp", "iam", "service account", "secret manager", "audit logging", "workload identity"],
    },
    {
        "id": "official.nist.ssdf",
        "category": "secure-development",
        "title": "Use NIST SSDF practices for secure software development, vulnerability response, and evidence",
        "source_url": "https://csrc.nist.gov/pubs/sp/800/218/final",
        "keywords": ["nist", "ssdf", "secure", "development", "vulnerability", "evidence", "supply chain"],
    },
    {
        "id": "official.openssf.scorecard",
        "category": "supply-chain",
        "title": "Check OpenSSF Scorecard-style supply-chain controls such as pinned dependencies, branch protection, fuzzing, and token permissions",
        "source_url": "https://github.com/ossf/scorecard",
        "keywords": ["openssf", "scorecard", "branch", "token", "dependencies", "sast", "fuzzing"],
    },
    {
        "id": "official.slsa.v1.2",
        "category": "supply-chain",
        "title": "Use SLSA v1.2 provenance and build integrity concepts for release and package pipelines",
        "source_url": "https://slsa.dev/spec/",
        "keywords": ["slsa", "provenance", "attestation", "build", "release", "artifact", "supply chain"],
    },
    {
        "id": "official.terraform.style",
        "category": "iac",
        "title": "Follow Terraform style and module practices for readable, maintainable infrastructure",
        "source_url": "https://developer.hashicorp.com/terraform/language/style",
        "keywords": ["terraform", "opentofu", "hcl", "module", "variable", "resource", "output"],
    },
    {
        "id": "official.typescript.strict",
        "category": "typescript",
        "title": "Prefer strict TypeScript checking for code that changes contracts, data handling, or security-sensitive paths",
        "source_url": "https://www.typescriptlang.org/tsconfig/strict.html",
        "keywords": ["typescript", "tsconfig", "strict", "noimplicitany", "null", "type"],
    },
    {
        "id": "official.react.dangerous-html",
        "category": "react",
        "title": "Treat dangerouslySetInnerHTML and equivalent DOM sinks as security-sensitive review surfaces",
        "source_url": "https://react.dev/reference/react-dom/components/common#dangerously-setting-the-inner-html",
        "keywords": ["react", "dangerouslysetinnerhtml", "xss", "html", "dom", "sanitize"],
    },
    {
        "id": "official.python.secrets",
        "category": "python",
        "title": "Use Python secrets for security randomness instead of random",
        "source_url": "https://docs.python.org/3/library/secrets.html",
        "keywords": ["python", "secrets", "random", "token", "password", "crypto"],
    },
    {
        "id": "official.python.subprocess-security",
        "category": "python",
        "title": "Review Python subprocess usage for shell injection and quoting risks",
        "source_url": "https://docs.python.org/3/library/subprocess.html#security-considerations",
        "keywords": ["python", "subprocess", "shell", "command", "injection", "quote"],
    },
]


def run_command(args: Sequence[str], cwd: Optional[Path] = None, timeout: int = 240) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(args),
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
    )


def parse_github_url(url: str) -> Dict[str, str]:
    match = re.match(r"https://github\.com/([^/]+)/([^/]+)(?:/(.*))?$", url.rstrip("/"))
    if not match:
        raise ValueError(f"Unsupported GitHub URL: {url}")
    owner, repo, rest = match.groups()
    repo = repo.removesuffix(".git")
    ref = ""
    path = ""
    kind = "repo"
    if rest:
        parts = rest.split("/")
        if len(parts) >= 2 and parts[0] in {"tree", "blob"}:
            kind = parts[0]
            ref = parts[1]
            path = "/".join(parts[2:])
    return {
        "owner": owner,
        "repo": repo,
        "full_name": f"{owner}/{repo}",
        "ref": ref,
        "path": path,
        "kind": kind,
        "clone_url": f"https://github.com/{owner}/{repo}.git",
    }


def clone_key(source: Dict[str, str]) -> Tuple[str, str]:
    parsed = parse_github_url(source["url"])
    return parsed["full_name"], parsed["ref"] or "HEAD"


def clone_repo(full_name: str, ref: str, cache_dir: Path, paths: Sequence[str]) -> Tuple[Optional[Path], str]:
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "__", f"{full_name}__{ref or 'HEAD'}")
    dest = cache_dir / safe_name
    if dest.exists():
        return dest, ""

    clone_url = f"https://github.com/{full_name}.git"
    args = ["git", "clone", "--filter=blob:none", "--no-checkout", "--depth", "1"]
    if ref and ref != "HEAD":
        args.extend(["--branch", ref])
    args.extend([clone_url, str(dest)])
    result = run_command(args, timeout=600)
    if result.returncode != 0:
        return None, (result.stderr or result.stdout).strip()

    sparse_paths = {
        "LICENSE*",
        "COPYING*",
        "README*",
        "SKILL.md",
        "skills",
        "commands",
        "agents",
        "scripts",
        "references",
        "examples",
        "mcp",
        ".codex-plugin",
        "package.json",
        "pyproject.toml",
    }
    for path in paths:
        if path:
            sparse_paths.add(path)
            parent = str(PurePosixPath(path).parent)
            if parent and parent != ".":
                sparse_paths.add(parent)
    run_command(["git", "sparse-checkout", "init", "--no-cone"], cwd=dest)
    sparse = run_command(["git", "sparse-checkout", "set", "--no-cone", *sorted(sparse_paths)], cwd=dest)
    if sparse.returncode != 0:
        return dest, (sparse.stderr or sparse.stdout).strip()
    checkout = run_command(["git", "checkout"], cwd=dest, timeout=600)
    if checkout.returncode != 0:
        return dest, (checkout.stderr or checkout.stdout).strip()
    return dest, ""


def git_head(repo_path: Path) -> str:
    result = run_command(["git", "rev-parse", "HEAD"], cwd=repo_path)
    return result.stdout.strip() if result.returncode == 0 else ""


def find_license_file(repo_path: Path) -> Optional[Path]:
    for child in repo_path.iterdir():
        if child.is_file() and child.name.lower().startswith(("license", "copying")):
            return child
    return None


def classify_license(text: str, filename: str = "") -> str:
    lowered = f"{filename}\n{text[:8000]}".lower()
    checks = [
        ("apache-2.0", ["apache license", "version 2.0"]),
        ("mit", ["mit license", "permission is hereby granted"]),
        ("bsd", ["bsd", "redistribution and use in source and binary forms"]),
        ("isc", ["isc license", "permission to use, copy, modify, and/or distribute"]),
        ("mpl-2.0", ["mozilla public license", "version 2.0"]),
        ("cc0", ["creative commons zero", "cc0"]),
        ("unlicense", ["the unlicense", "public domain"]),
    ]
    for key, needles in checks:
        if all(needle in lowered for needle in needles):
            return key
    return "unknown"


def read_text(path: Path, max_chars: int = 12000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:max_chars]
    except OSError:
        return ""


def first_sentence(text: str, fallback: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return fallback
    parts = re.split(r"(?<=[.!?])\s+", normalized)
    return parts[0][:260].strip() or fallback


def extract_frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    raw = text[3:end].strip()
    body = text[end + 4 :].lstrip()
    metadata: Dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip("\"'")
    return metadata, body


def local_candidates(repo_path: Path, source_path: str, kind: str, skill_name: str) -> List[Path]:
    candidates: List[Path] = []
    if source_path:
        target = repo_path / source_path
        if kind == "blob":
            candidates.append(target)
            candidates.append(target.parent)
        else:
            candidates.append(target)
    slug = skill_name.lower()
    for pattern in (
        f"**/{slug}/SKILL.md",
        f"**/{slug}.md",
        f"**/{slug}/README.md",
        f"**/{slug.replace('-', '_')}/SKILL.md",
    ):
        candidates.extend(repo_path.glob(pattern))
    candidates.extend([repo_path / "SKILL.md", repo_path / "README.md"])
    seen = set()
    unique = []
    for item in candidates:
        normalized = str(item)
        if normalized not in seen:
            unique.append(item)
            seen.add(normalized)
    return unique


def choose_skill_document(repo_path: Path, source_path: str, kind: str, skill_name: str) -> Tuple[Optional[Path], str]:
    for candidate in local_candidates(repo_path, source_path, kind, skill_name):
        if candidate.is_dir():
            for name in ("SKILL.md", "skill.md", "README.md", "readme.md"):
                doc = candidate / name
                if doc.exists():
                    return doc, str(doc.parent.relative_to(repo_path)).replace("\\", "/")
        elif candidate.is_file():
            return candidate, str(candidate.parent.relative_to(repo_path)).replace("\\", "/")
    return None, source_path


def list_relative_files(root: Path, names: Iterable[str], limit: int = 20) -> List[str]:
    if not root.exists() or not root.is_dir():
        return []
    results = []
    for name in names:
        for item in root.glob(name):
            if item.is_file():
                results.append(str(item.relative_to(root)).replace("\\", "/"))
            elif item.is_dir():
                for child in item.rglob("*"):
                    if child.is_file():
                        results.append(str(child.relative_to(root)).replace("\\", "/"))
            if len(results) >= limit:
                return sorted(set(results))[:limit]
    return sorted(set(results))[:limit]


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def extract_source_entry(source: Dict[str, str], repo_path: Optional[Path], error: str = "") -> Dict[str, Any]:
    parsed = parse_github_url(source["url"])
    license_key = "unknown"
    license_file = ""
    pinned_commit = ""
    doc_path = ""
    description = ""
    body_excerpt = ""
    agents: List[str] = []
    scripts: List[str] = []
    references: List[str] = []
    examples: List[str] = []
    mcp: List[str] = []

    if repo_path and repo_path.exists():
        pinned_commit = git_head(repo_path)
        license_path = find_license_file(repo_path)
        if license_path:
            license_file = license_path.name
            license_key = classify_license(read_text(license_path, max_chars=10000), license_path.name)
        doc, extracted_root = choose_skill_document(repo_path, parsed["path"], parsed["kind"], source["skill_name"])
        if doc:
            doc_path = str(doc.relative_to(repo_path)).replace("\\", "/")
            text = read_text(doc)
            metadata, body = extract_frontmatter(text)
            description = metadata.get("description") or first_sentence(body, source["skill_name"])
            body_excerpt = re.sub(r"\s+", " ", body).strip()[:1600]
            artifact_root = (repo_path / extracted_root) if extracted_root and extracted_root != "." else repo_path
            agents = list_relative_files(artifact_root, ["agents", "agent*", "*.yaml", "*.yml"], limit=10)
            scripts = list_relative_files(artifact_root, ["scripts", "*.py", "*.sh", "*.ts", "*.js"], limit=12)
            references = list_relative_files(artifact_root, ["references", "reference", "docs"], limit=16)
            examples = list_relative_files(artifact_root, ["examples", "example"], limit=16)
            mcp = [
                path
                for path in list_relative_files(artifact_root, ["mcp", "**/*mcp*", ".codex-plugin"], limit=16)
                if "mcp" in path.lower() or ".codex-plugin" in path
            ]

    compatible = license_key in COMPATIBLE_LICENSES
    if not compatible:
        body_excerpt = ""
        description = source["skill_name"]
    return {
        "skill_name": source["skill_name"],
        "category": source["category"],
        "source_url": source["url"],
        "repo": parsed["full_name"],
        "ref": parsed["ref"] or "",
        "path": parsed["path"],
        "kind": parsed["kind"],
        "pinned_commit": pinned_commit,
        "license": license_key,
        "license_file": license_file,
        "license_compatible": compatible,
        "vendor_status": "metadata-only" if not compatible else "catalog-guidance",
        "document_path": doc_path,
        "description": description,
        "guidance_excerpt": body_excerpt,
        "guidance_hash": content_hash(body_excerpt) if body_excerpt else "",
        "artifacts": {
            "agents": agents,
            "scripts": scripts,
            "references": references,
            "examples": examples,
            "mcp": mcp,
        },
        "error": error,
    }


def keywords_for_entry(entry: Dict[str, Any]) -> List[str]:
    words = set(re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", " ".join([
        str(entry.get("skill_name") or ""),
        str(entry.get("category") or ""),
        str(entry.get("description") or ""),
        str(entry.get("guidance_excerpt") or "")[:900],
    ]).lower()))
    stop = {"and", "the", "with", "for", "from", "that", "this", "when", "into", "using", "skill", "agent"}
    return sorted(word for word in words if word not in stop)[:28]


def build_catalog(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    rules = []
    for entry in entries:
        if entry.get("error") or not entry.get("license_compatible"):
            continue
        rules.append(
            {
                "id": f"skill.{entry['category']}.{entry['skill_name']}",
                "source": entry["skill_name"],
                "category": entry["category"],
                "title": entry.get("description") or entry["skill_name"],
                "source_url": entry["source_url"],
                "repo": entry["repo"],
                "pinned_commit": entry.get("pinned_commit") or "",
                "license": entry.get("license") or "unknown",
                "keywords": keywords_for_entry(entry),
                "guidance_excerpt": entry.get("guidance_excerpt") or "",
                "artifacts": entry.get("artifacts") or {},
            }
        )
    return {
        "catalog_version": 1,
        "generated_by": "tools/build_super_skill_catalog.py",
        "source_count": len(entries),
        "rule_count": len(rules) + len(OFFICIAL_BEST_PRACTICE_RULES),
        "official_best_practice_rules": OFFICIAL_BEST_PRACTICE_RULES,
        "rules": rules,
    }


def group_paths_by_repo(sources: Sequence[Dict[str, str]]) -> Dict[Tuple[str, str], List[str]]:
    grouped: Dict[Tuple[str, str], List[str]] = {}
    for source in sources:
        parsed = parse_github_url(source["url"])
        grouped.setdefault((parsed["full_name"], parsed["ref"] or "HEAD"), [])
        if parsed["path"]:
            grouped[(parsed["full_name"], parsed["ref"] or "HEAD")].append(parsed["path"])
    return grouped


def load_sources(path: Optional[Path]) -> List[Dict[str, str]]:
    if not path or not path.exists():
        return list(DEFAULT_SOURCES)
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("sources") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("source file must contain a list or an object with a sources list")
    return [
        {
            "skill_name": str(item["skill_name"]),
            "category": str(item["category"]),
            "url": str(item.get("source_url") or item["url"]),
        }
        for item in items
    ]


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def remove_readonly(func: Any, path: str, _exc_info: Any) -> None:
    os.chmod(path, stat.S_IWRITE)
    func(path)


def build_sources(
    *,
    sources: Sequence[Dict[str, str]],
    cache_dir: Path,
    clone: bool,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    grouped_paths = group_paths_by_repo(sources)
    repo_paths: Dict[Tuple[str, str], Optional[Path]] = {}
    errors: Dict[Tuple[str, str], str] = {}
    logs: List[str] = []

    if clone:
        cache_dir.mkdir(parents=True, exist_ok=True)
        for key, paths in sorted(grouped_paths.items()):
            full_name, ref = key
            repo_path, error = clone_repo(full_name, ref, cache_dir, paths)
            repo_paths[key] = repo_path
            errors[key] = error
            status = "ok" if repo_path and not error else "partial" if repo_path else "failed"
            logs.append(f"{status}: {full_name}@{ref}")
    else:
        for key in grouped_paths:
            repo_paths[key] = None
            errors[key] = "clone disabled"

    entries = []
    for source in sources:
        key = clone_key(source)
        entries.append(extract_source_entry(source, repo_paths.get(key), errors.get(key, "")))
    return entries, logs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-file", type=Path)
    parser.add_argument("--manifest-output", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--catalog-output", type=Path, default=DEFAULT_CATALOG_PATH)
    parser.add_argument("--cache-dir", type=Path, default=Path(os.environ.get("RUNNER_TEMP", "")) / "gha-agent-super-skill-sources")
    parser.add_argument("--no-clone", action="store_true")
    parser.add_argument("--clean-cache", action="store_true")
    args = parser.parse_args()

    sources = load_sources(args.source_file)
    if args.clean_cache and args.cache_dir.exists():
        shutil.rmtree(args.cache_dir, onerror=remove_readonly)

    entries, logs = build_sources(sources=sources, cache_dir=args.cache_dir, clone=not args.no_clone)
    manifest = {
        "manifest_version": 1,
        "source_count": len(entries),
        "distinct_repo_count": len({entry["repo"] for entry in entries}),
        "compatible_license_count": sum(1 for entry in entries if entry.get("license_compatible")),
        "sources": entries,
    }
    catalog = build_catalog(entries)

    write_json(args.manifest_output, manifest)
    write_json(args.catalog_output, catalog)
    for line in logs:
        print(line)
    print(f"Wrote {args.manifest_output}")
    print(f"Wrote {args.catalog_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
