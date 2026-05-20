import json
import re
from pathlib import PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


WORKFLOW_EXTENSIONS = {".yml", ".yaml"}
IAC_EXTENSIONS = {".tf", ".tfvars", ".hcl", ".bicep", ".arm", ".json", ".yml", ".yaml"}
K8S_KINDS = {
    "pod",
    "deployment",
    "statefulset",
    "daemonset",
    "job",
    "cronjob",
    "serviceaccount",
    "role",
    "clusterrole",
    "rolebinding",
    "clusterrolebinding",
    "networkpolicy",
    "ingress",
}
PUBLIC_RUNNER_PREFIXES = ("ubuntu-", "windows-", "macos-")
KNOWN_LOCKFILES = {
    "package.json": {"package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb"},
    "pyproject.toml": {"poetry.lock", "uv.lock", "pdm.lock"},
    "requirements.txt": {"requirements.lock", "constraints.txt"},
    "Pipfile": {"Pipfile.lock"},
}
ARCHITECTURE_DOC_NAMES = {
    "architecture.md",
    "platform-architecture.md",
    "technical-architecture.md",
}


def path_suffix(path: str) -> str:
    return PurePosixPath(path).suffix.lower()


def is_workflow(path: str) -> bool:
    return path.startswith(".github/workflows/") and path_suffix(path) in WORKFLOW_EXTENSIONS


def is_dockerfile(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return name == "dockerfile" or name.startswith("dockerfile.") or path_suffix(path) == ".dockerfile"


def is_kubernetes_manifest(path: str, text: str) -> bool:
    lower_path = path.lower()
    if not (path_suffix(path) in WORKFLOW_EXTENSIONS or lower_path.endswith(".tpl")):
        return False
    if any(part in lower_path for part in ("k8s", "kubernetes", "helm", "charts", "manifests")):
        return True
    kind = re.search(r"(?im)^\s*kind:\s*([A-Za-z]+)\s*$", text)
    return bool(kind and kind.group(1).lower() in K8S_KINDS)


def is_iac(path: str, text: str) -> bool:
    lower = path.lower()
    suffix = path_suffix(path)
    if suffix in {".tf", ".tfvars", ".hcl", ".bicep", ".arm"}:
        return True
    if any(part in lower for part in ("terraform", "opentofu", "pulumi", "cloudformation", "cdk", "bicep", "infra")):
        return suffix in IAC_EXTENSIONS or suffix in {".ts", ".tsx", ".js", ".jsx", ".py"}
    return bool(
        suffix in {".json", ".yml", ".yaml"}
        and re.search(r"(?i)AWSTemplateFormatVersion|Resources:|Microsoft\.|resource\s+\w+\s+'", text)
    )


def is_architecture_doc_path(path: str) -> bool:
    normalized = path.lower().replace("\\", "/")
    name = PurePosixPath(normalized).name
    return (
        name in ARCHITECTURE_DOC_NAMES
        or normalized in {"docs/architecture.md", "docs/platform-architecture.md"}
        or ("docs/" in normalized and any(part in name for part in ("architecture", "design", "technical-overview")))
    )


def line_number_for(text: str, pattern: str, flags: int = 0) -> Optional[int]:
    regex = re.compile(pattern, flags)
    for index, line in enumerate(text.splitlines(), start=1):
        if regex.search(line):
            return index
    return None


def line_text_for(text: str, line_number: Optional[int]) -> str:
    if not line_number:
        return ""
    lines = text.splitlines()
    if line_number < 1 or line_number > len(lines):
        return ""
    return lines[line_number - 1]


def add_finding(
    findings: List[Dict[str, Any]],
    *,
    path: Optional[str],
    line: Optional[int],
    severity: str,
    rule_id: str,
    title: str,
    body: str,
    suggestion: Optional[str] = None,
    blocks_merge: Optional[bool] = None,
    warning_type: Optional[str] = None,
    auto_fix: bool = False,
) -> None:
    finding: Dict[str, Any] = {
        "path": path,
        "line": line,
        "severity": severity,
        "rule_id": rule_id,
        "title": title,
        "body": body,
        "suggestion": suggestion,
        "blocks_merge": blocks_merge,
        "warning_type": warning_type,
    }
    if auto_fix:
        finding["auto_fix"] = True
    findings.append(finding)


def parse_json_content(text: str) -> Dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def is_public_runner(value: str) -> bool:
    cleaned = value.strip().strip("\"'")
    if not cleaned:
        return True
    lowered = cleaned.lower()
    if "self-hosted" in lowered:
        return False
    if "${{" in lowered:
        return False
    if lowered.startswith("["):
        labels = [part.strip().strip("\"'").lower() for part in lowered.strip("[]").split(",")]
        return bool(labels) and all(label.startswith(PUBLIC_RUNNER_PREFIXES) for label in labels if label)
    return lowered.startswith(PUBLIC_RUNNER_PREFIXES)


def is_gha_agent_review_self_test(context: Dict[str, Any], path: str) -> bool:
    repository = str(context.get("repository") or "")
    return repository.endswith("/ai-github-actions-agent") and path == ".github/workflows/gha-agent-review.yml"


def check_hardcoded_secrets(path: str, text: str, findings: List[Dict[str, Any]]) -> None:
    secret_patterns = [
        r"AKIA[0-9A-Z]{16}",
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
        r"(?i)\b[A-Z0-9_-]*(password|passwd|secret|token|api[_-]?key|access[_-]?key|client[_-]?secret)\b\s*[:=]\s*[\"'][^\"'${}\s]{8,}[\"']",
    ]
    for pattern in secret_patterns:
        line = line_number_for(text, pattern)
        if not line:
            continue
        current = line_text_for(text, line)
        if any(safe in current for safe in ("secrets.", "os.environ", "process.env", "getenv", "SecretValue", "${{")):
            continue
        add_finding(
            findings,
            path=path,
            line=line,
            severity="critical",
            rule_id="security.secrets.hardcoded",
            title="Remove hardcoded credential material",
            body=(
                "Credential-like material is committed in source. Move it to a secret manager or CI secret, "
                "rotate the exposed value, and keep only a reference in the repository."
            ),
            suggestion=None,
            blocks_merge=True,
        )
        return


def check_workflow_runners(path: str, text: str, findings: List[Dict[str, Any]]) -> None:
    for index, line in enumerate(text.splitlines(), start=1):
        match = re.search(r"runs-on:\s*(.+)", line)
        if not match:
            continue
        runner_value = match.group(1).strip()
        if is_public_runner(runner_value):
            continue
        add_finding(
            findings,
            path=path,
            line=index,
            severity="medium",
            rule_id="github-actions.runner.self-hosted",
            title="Review self-hosted runner exposure",
            body=(
                "Self-hosted or dynamic runners can expose persistent credentials, network access, and host state. "
                "Use them only with explicit isolation and do not run untrusted PR code with secrets."
            ),
            blocks_merge=False,
            warning_type="public-runner",
        )


def check_workflow_permissions(path: str, text: str, findings: List[Dict[str, Any]]) -> None:
    if re.search(r"(?im)^\s*permissions:\s*write-all\s*$", text):
        line = line_number_for(text, r"(?im)^\s*permissions:\s*write-all\s*$") or 1
        add_finding(
            findings,
            path=path,
            line=line,
            severity="high",
            rule_id="github-actions.permissions.write-all",
            title="Avoid write-all workflow permissions",
            body="`write-all` grants broad repository authority. Set only the scopes the job needs.",
            suggestion=None,
            blocks_merge=True,
        )
    if "pull-requests: write" in text or "contents: write" in text or "id-token: write" in text:
        if not re.search(r"(?im)^\s*permissions:\s*$", text):
            add_finding(
                findings,
                path=path,
                line=1,
                severity="medium",
                rule_id="github-actions.permissions.explicit",
                title="Declare workflow permissions explicitly",
                body=(
                    "This workflow uses write or OIDC permissions. Declare the permission block explicitly so "
                    "reviewers can verify least privilege."
                ),
                blocks_merge=False,
                warning_type="supply-chain",
            )


def check_workflow_triggers(path: str, text: str, findings: List[Dict[str, Any]]) -> None:
    if "pull_request_target" not in text:
        return
    risky = re.search(r"(?is)pull_request_target.*(?:actions/checkout|npm install|npm ci|pip install|python|bash|sh )", text)
    if not risky:
        return
    line = line_number_for(text, r"pull_request_target") or 1
    add_finding(
        findings,
        path=path,
        line=line,
        severity="high",
        rule_id="github-actions.pull-request-target",
        title="Do not execute untrusted PR code in pull_request_target",
        body=(
            "`pull_request_target` runs with base-repository privileges. Checking out or executing PR-controlled "
            "code in that context can expose secrets or write tokens to an attacker."
        ),
        blocks_merge=True,
    )


def check_workflow_action_refs(path: str, text: str, findings: List[Dict[str, Any]]) -> None:
    for index, line in enumerate(text.splitlines(), start=1):
        match = re.search(r"uses:\s*([^@\s\"']+)@([^\s\"']+)", line)
        if not match:
            continue
        action_ref = match.group(1)
        version = match.group(2)
        if action_ref.startswith("./"):
            continue
        if action_ref == "zukeru/ai-github-actions-agent/.github/actions/gha-agent-review":
            continue
        if version.lower() in {"main", "master", "latest", "head"}:
            add_finding(
                findings,
                path=path,
                line=index,
                severity="high",
                rule_id="github-actions.action-ref.floating",
                title="Pin third-party actions to immutable references",
                body=(
                    f"`{action_ref}@{version}` is mutable. Use a trusted version tag or commit SHA, especially "
                    "for jobs with secrets, cloud credentials, or write permissions."
                ),
                blocks_merge=True,
            )


def check_workflow_secrets_and_commands(
    path: str,
    text: str,
    context: Dict[str, Any],
    findings: List[Dict[str, Any]],
) -> None:
    for index, line in enumerate(text.splitlines(), start=1):
        if re.search(r"\bgithub[-_]token:\s*", line):
            if is_gha_agent_review_self_test(context, path) and "secrets.GITHUB_TOKEN_NOT_OEPNER" in line:
                continue
            if "secrets.GHA_AI_AGENT_GIT_TOKEN" in line and "github.token" not in line:
                continue
            indent = re.match(r"^(\s*)", line).group(1)
            add_finding(
                findings,
                path=path,
                line=index,
                severity="high",
                rule_id="github-actions.git-token",
                title="Use GHA_AI_AGENT_GIT_TOKEN for GHA AI Agent review access",
                body=(
                    "The GHA AI Agent review action needs a dedicated repository or organization token for PR "
                    "review and fix-PR operations. Do not use `github.token` or unrelated secrets for this input."
                ),
                suggestion=f'{indent}github-token: "${{{{ secrets.GHA_AI_AGENT_GIT_TOKEN }}}}"',
                blocks_merge=True,
                auto_fix=True,
            )
        if re.search(r"(?i)(curl|wget)\b.*\|\s*(bash|sh|python|pwsh|powershell)\b", line):
            add_finding(
                findings,
                path=path,
                line=index,
                severity="high",
                rule_id="github-actions.remote-script-pipe",
                title="Verify downloaded scripts before execution",
                body=(
                    "Piping a mutable remote script directly into an interpreter is a supply-chain risk. Pin the "
                    "source and verify checksums or signatures before execution."
                ),
                blocks_merge=True,
            )
        if "/var/run/docker.sock" in line:
            add_finding(
                findings,
                path=path,
                line=index,
                severity="high",
                rule_id="github-actions.docker-socket",
                title="Protect Docker socket access",
                body=(
                    "Mounting the Docker socket gives containerized code host-level control. Do not expose it to "
                    "untrusted PR code or jobs with attacker-controlled inputs."
                ),
                blocks_merge=True,
            )


def check_workflow_cloud_auth(path: str, text: str, findings: List[Dict[str, Any]]) -> None:
    if (
        "aws-actions/configure-aws-credentials" in text
        and "aws-access-key-id" in text
        and "role-to-assume" not in text
    ):
        line = line_number_for(text, r"aws-actions/configure-aws-credentials") or 1
        add_finding(
            findings,
            path=path,
            line=line,
            severity="medium",
            rule_id="github-actions.cloud-auth.oidc",
            title="Prefer OIDC for cloud deployment credentials",
            body=(
                "Long-lived cloud access keys in CI increase rotation and exfiltration risk. Prefer GitHub OIDC "
                "with a scoped cloud role when the provider and repository support it."
            ),
            blocks_merge=False,
            warning_type="supply-chain",
        )


def check_dockerfile(path: str, text: str, findings: List[Dict[str, Any]]) -> None:
    lines = text.splitlines()
    for index, line in enumerate(lines, start=1):
        if re.search(r"(?i)^\s*FROM\s+[^#\s:]+:latest\b", line):
            add_finding(
                findings,
                path=path,
                line=index,
                severity="medium",
                rule_id="docker.base.latest",
                title="Avoid mutable latest container tags",
                body="Use an immutable base image version or digest so builds are reproducible and auditable.",
                blocks_merge=False,
                warning_type="supply-chain",
            )
        if re.search(r"(?i)^\s*ADD\s+https?://", line):
            add_finding(
                findings,
                path=path,
                line=index,
                severity="medium",
                rule_id="docker.remote-add",
                title="Do not ADD remote URLs directly",
                body="Remote ADD downloads are mutable and difficult to verify. Download explicitly with checksum/signature verification.",
                blocks_merge=False,
                warning_type="supply-chain",
            )
        if re.search(r"(?i)(curl|wget)\b.*\|\s*(bash|sh|python)\b", line):
            add_finding(
                findings,
                path=path,
                line=index,
                severity="high",
                rule_id="docker.remote-script-pipe",
                title="Verify downloaded install scripts",
                body="Do not execute mutable remote scripts in image builds without checksum or signature verification.",
                blocks_merge=True,
            )
    if not re.search(r"(?im)^\s*USER\s+([1-9][0-9]*|[A-Za-z_][A-Za-z0-9_-]*)\s*$", text):
        add_finding(
            findings,
            path=path,
            line=1,
            severity="medium",
            rule_id="docker.non-root-user",
            title="Run containers as a non-root user",
            body="Production containers should set a non-root USER unless root is required and documented.",
            blocks_merge=False,
            warning_type="supply-chain",
        )


def check_kubernetes(path: str, text: str, findings: List[Dict[str, Any]]) -> None:
    for index, line in enumerate(text.splitlines(), start=1):
        if re.search(r"privileged:\s*true", line):
            indent = re.match(r"^(\s*)", line).group(1)
            add_finding(
                findings,
                path=path,
                line=index,
                severity="high",
                rule_id="kubernetes.pod-security.privileged",
                title="Do not run privileged containers by default",
                body="Privileged containers bypass key Kubernetes isolation controls. Use least privilege and only add specific capabilities that are required.",
                suggestion=f"{indent}privileged: false",
                blocks_merge=True,
                auto_fix=True,
            )
        if re.search(r"runAsUser:\s*0\b", line):
            add_finding(
                findings,
                path=path,
                line=index,
                severity="high",
                rule_id="kubernetes.pod-security.root-user",
                title="Avoid running workloads as root",
                body="Kubernetes workloads should run as a non-root user unless root is required and documented.",
                blocks_merge=True,
            )
        if re.search(r"host(Path|Network|PID|IPC):\s*true|hostPath:", line):
            add_finding(
                findings,
                path=path,
                line=index,
                severity="high",
                rule_id="kubernetes.pod-security.host-access",
                title="Review host-level Kubernetes access",
                body="Host networking, namespaces, or hostPath mounts can break workload isolation and expose node resources.",
                blocks_merge=True,
            )
        if re.search(r"(?i)image:\s*[^#\s]+:latest\b", line):
            add_finding(
                findings,
                path=path,
                line=index,
                severity="medium",
                rule_id="kubernetes.image.latest",
                title="Avoid mutable latest images",
                body="Use immutable image tags or digests for deployable Kubernetes workloads.",
                blocks_merge=False,
                warning_type="supply-chain",
            )


def check_iac(path: str, text: str, findings: List[Dict[str, Any]]) -> None:
    for index, line in enumerate(text.splitlines(), start=1):
        if re.search(r"0\.0\.0\.0/0|::/0", line) and re.search(r"22|3389|ssh|rdp|management|admin", text, re.IGNORECASE):
            add_finding(
                findings,
                path=path,
                line=index,
                severity="high",
                rule_id="iac.network.public-management",
                title="Restrict public management access",
                body="Public ingress to management ports or admin services exposes privileged interfaces. Scope access to trusted networks or private connectivity.",
                blocks_merge=True,
            )
        if (
            re.search(r"Action\s*[:=]\s*[\"']\*|actions\s*=\s*\[\s*[\"']\*[\"']|Resource\s*[:=]\s*[\"']\*", line)
            or ("Action" in line and '"*"' in line)
            or ("Action" in line and '\\"*\\"' in line)
        ):
            add_finding(
                findings,
                path=path,
                line=index,
                severity="high",
                rule_id="iac.iam.wildcard",
                title="Avoid wildcard IAM permissions",
                body="Wildcard IAM actions or resources violate least privilege and can turn small mistakes into account-wide compromise.",
                blocks_merge=True,
            )
        if re.search(r"(?i)(publicAccessBlock|allowBlobPublicAccess|allUsers|allAuthenticatedUsers).*false|Principal\s*[:=]\s*[\"']\*[\"']", line):
            add_finding(
                findings,
                path=path,
                line=index,
                severity="high",
                rule_id="iac.public-access",
                title="Review public cloud resource access",
                body="Public principals or disabled public-access controls can expose storage, data, or control-plane resources.",
                blocks_merge=True,
            )


def package_files_from_context(context: Dict[str, Any]) -> Set[str]:
    files = context.get("files") or []
    names = {str(item.get("filename") or "") for item in files if item.get("filename")}
    names.update(str(path) for path in (context.get("file_contents") or {}))
    names.update(str(path) for path in (context.get("head_tree_paths") or []))
    return names


def check_package_hygiene(context: Dict[str, Any], file_contents: Dict[str, str], findings: List[Dict[str, Any]]) -> None:
    all_paths = package_files_from_context(context)
    changed_paths = {str(item.get("filename") or "") for item in (context.get("files") or []) if item.get("filename")}

    for manifest, lockfiles in KNOWN_LOCKFILES.items():
        changed_manifest = any(path == manifest or path.endswith("/" + manifest) for path in changed_paths)
        if not changed_manifest:
            continue
        manifest_path = next(path for path in changed_paths if path == manifest or path.endswith("/" + manifest))
        directory = manifest_path.rsplit("/", 1)[0] + "/" if "/" in manifest_path else ""
        expected_locks = {directory + lock for lock in lockfiles}
        if not (expected_locks & all_paths):
            add_finding(
                findings,
                path=manifest_path,
                line=1,
                severity="medium",
                rule_id="packages.lockfile.missing",
                title="Keep package manifests and lockfiles together",
                body="Package manifest changes should include a matching lockfile when the ecosystem supports one so dependency resolution is reproducible.",
                blocks_merge=False,
                warning_type="dependency",
            )

    package_text = file_contents.get("package.json")
    if package_text:
        package_json = parse_json_content(package_text)
        scripts = package_json.get("scripts") if isinstance(package_json.get("scripts"), dict) else {}
        for name, command in scripts.items():
            if str(name) in {"preinstall", "install", "postinstall", "prepare"} and re.search(r"(?i)(curl|wget|bash|sh|node\s+-e)", str(command)):
                add_finding(
                    findings,
                    path="package.json",
                    line=line_number_for(package_text, rf'"{re.escape(str(name))}"\s*:') or 1,
                    severity="high",
                    rule_id="packages.install-script.remote-exec",
                    title="Review package install script execution",
                    body="Lifecycle scripts that execute downloaded or inline code can run during CI and developer installs. Pin and verify the source or remove the script.",
                    blocks_merge=True,
                )


def parse_coverage_summary_json(text: str) -> Optional[float]:
    data = parse_json_content(text)
    total = data.get("total") if isinstance(data.get("total"), dict) else {}
    for key in ("lines", "statements", "branches", "functions"):
        value = total.get(key)
        if isinstance(value, dict) and isinstance(value.get("pct"), (int, float)):
            return float(value["pct"])
    return None


def parse_lcov(text: str) -> Optional[float]:
    found = 0
    hit = 0
    for line in text.splitlines():
        if line.startswith("LF:"):
            found += int(line[3:] or 0)
        elif line.startswith("LH:"):
            hit += int(line[3:] or 0)
    if found <= 0:
        return None
    return (hit / found) * 100


def parse_cobertura_xml(text: str) -> Optional[float]:
    match = re.search(r'line-rate="([0-9.]+)"', text)
    if not match:
        return None
    value = float(match.group(1))
    return value * 100 if value <= 1 else value


def parse_fail_under(text: str) -> Optional[float]:
    match = re.search(r"(?im)^\s*fail_under\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*$", text)
    return float(match.group(1)) if match else None


def parse_js_threshold(text: str) -> Optional[float]:
    numbers: List[float] = []
    for pattern in (
        r"coverageThreshold\s*:\s*{[^}]*?(?:lines|statements|branches|functions)\s*:\s*([0-9]+)",
        r"thresholds\s*:\s*{[^}]*?(?:lines|statements|branches|functions)\s*:\s*([0-9]+)",
        r'"(?:lines|statements|branches|functions)"\s*:\s*([0-9]+)',
    ):
        for match in re.finditer(pattern, text, re.DOTALL):
            numbers.append(float(match.group(1)))
    return min(numbers) if numbers else None


def coverage_measurements(file_contents: Dict[str, str]) -> List[Tuple[str, float, str]]:
    measurements: List[Tuple[str, float, str]] = []
    for path, text in file_contents.items():
        name = PurePosixPath(path).name.lower()
        lower = path.lower()
        value: Optional[float] = None
        label = "coverage"
        if name == "coverage-summary.json":
            value = parse_coverage_summary_json(text)
            label = "coverage summary"
        elif name == "lcov.info":
            value = parse_lcov(text)
            label = "lcov line coverage"
        elif lower.endswith("coverage.xml") or "cobertura" in lower:
            value = parse_cobertura_xml(text)
            label = "cobertura line coverage"
        elif name in {".coveragerc", "setup.cfg", "tox.ini", "pyproject.toml"}:
            value = parse_fail_under(text)
            label = "configured Python coverage threshold"
        elif name in {"package.json", "jest.config.js", "jest.config.ts", "vitest.config.js", "vitest.config.ts", "vite.config.js", "vite.config.ts"}:
            value = parse_js_threshold(text)
            label = "configured JavaScript coverage threshold"
        if value is not None:
            measurements.append((path, value, label))
    return measurements


def check_coverage(context: Dict[str, Any], file_contents: Dict[str, str], findings: List[Dict[str, Any]]) -> None:
    threshold = float(context.get("coverage_warning_threshold") or 90)
    for path, value, label in coverage_measurements(file_contents):
        if value >= threshold:
            continue
        add_finding(
            findings,
            path=path,
            line=1,
            severity="medium",
            rule_id="tests.coverage.below-threshold",
            title="Coverage is below the GHA AI Agent threshold",
            body=f"The {label} is {value:.1f} percent, below the configured {threshold:.1f} percent warning threshold.",
            blocks_merge=False,
            warning_type="coverage",
        )


def check_readme_diagram(file_contents: Dict[str, str], findings: List[Dict[str, Any]]) -> None:
    readme_path = next((path for path in file_contents if PurePosixPath(path).name.lower() == "readme.md"), None)
    if not readme_path:
        return
    readme_text = file_contents[readme_path]
    if "```mermaid" in readme_text.lower():
        return
    add_finding(
        findings,
        path=readme_path,
        line=1,
        severity="low",
        rule_id="documentation.readme.mermaid",
        title="Add a Mermaid diagram to the README",
        body="The repository README does not include a Mermaid diagram. The GHA AI Agent can add a concise architecture or workflow diagram in an automatic fix PR.",
        blocks_merge=False,
        warning_type="documentation",
    )


def check_architecture_documentation(
    context: Dict[str, Any],
    file_contents: Dict[str, str],
    findings: List[Dict[str, Any]],
) -> None:
    head_tree_paths = {str(path) for path in (context.get("head_tree_paths") or [])}
    has_readme_context = any(PurePosixPath(path).name.lower() == "readme.md" for path in file_contents)
    if not head_tree_paths and not has_readme_context:
        return
    paths = set(str(path) for path in file_contents)
    paths.update(head_tree_paths)
    architecture_paths = sorted(path for path in paths if is_architecture_doc_path(path))
    if not architecture_paths:
        add_finding(
            findings,
            path="docs/architecture.md",
            line=1,
            severity="low",
            rule_id="documentation.architecture.missing",
            title="Add architecture documentation with diagrams",
            body=(
                "The repository does not include a Markdown architecture document. Add `docs/architecture.md` "
                "or an equivalent architecture/design document with Mermaid diagrams so reviewers can understand "
                "runtime flow, scripts, trust boundaries, and operational ownership."
            ),
            blocks_merge=False,
            warning_type="documentation",
        )
        return

    captured = [(path, file_contents[path]) for path in architecture_paths if path in file_contents]
    if captured and not any("```mermaid" in text.lower() for _path, text in captured):
        add_finding(
            findings,
            path=captured[0][0],
            line=1,
            severity="low",
            rule_id="documentation.architecture.mermaid",
            title="Add Mermaid diagrams to architecture documentation",
            body=(
                "Architecture documentation should include Mermaid diagrams for system flow, trust boundaries, "
                "or operational workflows so reviewers can reason about the platform quickly."
            ),
            blocks_merge=False,
            warning_type="documentation",
        )


def merge_policy_findings(result: Dict[str, Any], policy_findings: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    merged = dict(result)
    findings = list(merged.get("findings") or [])
    findings.extend(policy_findings)
    merged["findings"] = findings
    return merged


def evaluate_policy(context: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    file_contents = {str(path): str(text) for path, text in (context.get("file_contents") or {}).items()}

    for path, text in file_contents.items():
        check_hardcoded_secrets(path, text, findings)
        if is_workflow(path):
            check_workflow_runners(path, text, findings)
            check_workflow_permissions(path, text, findings)
            check_workflow_triggers(path, text, findings)
            check_workflow_action_refs(path, text, findings)
            check_workflow_secrets_and_commands(path, text, context, findings)
            check_workflow_cloud_auth(path, text, findings)
        if is_dockerfile(path):
            check_dockerfile(path, text, findings)
        if is_kubernetes_manifest(path, text):
            check_kubernetes(path, text, findings)
        if is_iac(path, text):
            check_iac(path, text, findings)

    check_package_hygiene(context, file_contents, findings)
    check_coverage(context, file_contents, findings)
    check_readme_diagram(file_contents, findings)
    check_architecture_documentation(context, file_contents, findings)
    return findings
