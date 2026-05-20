# GHA AI Agent Comprehensive PR Review Rules

Created by Grant Zukel for using Claude skills in a GitHub Action.

Use this file as the generic GHA AI Agent standard for automated pull request review. Review the PR like a senior maintainer, compliance reviewer, software engineer, platform engineer, white-hat tester, and black-hat attacker. Inspect the touched files, their supporting context, tests, package changes, infrastructure definitions, CI/CD changes, and documentation when they affect the changed behavior.

## Severity And Merge Impact

- `critical`: exposed live credentials, arbitrary code execution, authentication bypass, authorization bypass across tenants or privileged objects, destructive data loss, signing/release compromise, unsafe privileged workflow execution, or directly exploitable vulnerable dependencies.
- `high`: exploitable injection, SSRF with meaningful reachability, unsafe deserialization, path traversal with sensitive file access, missing authorization on sensitive actions, unsafe secret handling, broken deployment safety, public cloud exposure of protected services, or risky behavior without meaningful tests.
- `medium`: non-blocking compliance gaps, dependency hygiene, weak hardening, maintainability, reliability, performance, observability, missing documentation, or coverage warnings.
- `low`: minor documentation, clarity, style, future-proofing, and low-risk hardening guidance.

Set `blocks_merge: true` only for concrete `critical` or `high` issues that need to be fixed before merge. Set `blocks_merge: false` for warnings. Do not inflate ordinary bugs into security blockers unless the code shows a realistic attacker path or production-impacting failure.

## Automatic Fix Expectations

- The review bot should automatically try to fix problems it finds when the fix is safe, deterministic, and limited to the cited behavior.
- Include a concrete `suggestion` and `auto_fix: true` only when a single-line or tightly scoped replacement is safe to apply without human judgment.
- Do not auto-fix speculative rewrites, migrations, broad refactors, package upgrades with behavior risk, or security fixes that require design decisions.
- If a README has no Mermaid diagram and the review opens a fix PR, add a small Mermaid architecture or workflow diagram that reflects the target repository.
- If architecture documentation is absent and the review opens a fix PR, add `docs/architecture.md` with repository-specific Markdown sections and Mermaid diagrams that explain runtime flow, trust boundaries, scripts, and operational ownership.
- Auto-fix branches must be named `{branch}-agent-fixes-{short-commit}` and PRs must target the original reviewed branch.
- Never create fix PRs from branches that already match `*-agent-fixes-*`.

## Super Skill Catalog

- Use the bundled Super Skill catalog together with these rules and the compliance catalog.
- The catalog merges pinned public skill-source guidance and official best-practice rules into a self-contained runtime artifact. Runtime reviews must not clone skill repos, install marketplace skills, or execute downloaded scripts.
- Treat catalog agents, MCP descriptors, scripts, examples, and references as review guidance unless this repository explicitly allowlists execution.
- When a finding maps to catalog guidance, include `super_skill_rule_ids`, `super_skill_sources`, and `best_practice_rule_ids`.
- Prefer official best-practice rules over public skill guidance when they conflict.
- The review body must show Super Skill category/source coverage counts in addition to the compliance framework tables.

## Review Method

1. Classify the changed surfaces: CI/CD, IaC, containers, Kubernetes, cloud, application code, tests, docs, packages, and configuration.
2. Build a lightweight threat model: assets, trust boundaries, attacker-controlled inputs, credentials, deployment privileges, and sensitive outputs.
3. Discover concrete candidates from the diff and supporting files. Prefer evidence over generic advice.
4. Validate each candidate with code tracing, tests, config evidence, or bounded reproduction when feasible.
5. Analyze attacker paths and production impact before assigning severity.
6. Separate blockers from warnings and include exact remediation.
7. Check whether test coverage is measurable; warn when it is below 90 percent.

## GitHub Actions And CI/CD

- Use least-privilege `permissions`; flag `write-all`, broad write scopes, or missing explicit permissions when a job writes to the repository, packages, deployments, releases, issues, or pull requests.
- Prefer OIDC and short-lived cloud credentials over long-lived cloud secrets for deployments.
- Do not approve `pull_request_target` workflows that check out or execute untrusted PR code, run install scripts from the PR, or expose secrets to PR-controlled commands.
- Pin third-party actions to immutable versions for sensitive jobs. Flag floating references such as `@main`, `@master`, `@latest`, or untrusted mutable tags.
- Treat self-hosted runners, Docker socket mounts, privileged containers, package publish tokens, deployment credentials, and repository write tokens as high-risk surfaces.
- Do not pass secrets on command lines, echo secrets, write secrets to artifacts, or persist credentials in generated files.
- Flag `curl | bash`, downloaded scripts without checksum/signature verification, mutable package installers in privileged jobs, and shell expressions that interpolate untrusted PR data.
- Require concurrency controls and environment protections for deployment, release, infrastructure, and production-mutation workflows.
- Require artifact integrity, provenance, or attestations for release and package-publish paths when the repository already supports them or the PR touches release logic.

## Infrastructure As Code

- Apply these rules to Terraform, OpenTofu, Pulumi, CloudFormation, CDK, ARM, Bicep, Helm, Kustomize, Ansible, Kubernetes YAML, and similar IaC files.
- Do not embed credentials, tokens, private keys, static cloud access keys, connection strings, or customer data in templates, variables, state examples, or generated configuration.
- Use least-privilege IAM/RBAC. Flag wildcard actions/resources, broad administrative roles, public principals, and trust policies that allow unintended identity assumption.
- Preserve deployment safety: idempotency, rollback behavior, environment scoping, tagging, drift visibility, change review, and clear failure behavior.
- Keep secrets in the correct cloud secret manager, parameter store, Kubernetes Secret, encrypted variable store, or runtime identity mechanism; do not place plaintext secrets in ConfigMaps, values files, state, or logs.
- Require network exposure to be intentional. Flag public ingress to management ports, unrestricted database/cache access, public storage buckets, and missing TLS controls on internet-facing services.
- Prefer reusable modules and typed configuration when the repository already has them, but do not invent organization-specific private modules or required project layouts.

## Kubernetes

- Follow Kubernetes Pod Security Standards and the security checklist when reviewing manifests, Helm charts, operators, and admission policies.
- Flag privileged pods, host networking/PID/IPC, hostPath mounts, added Linux capabilities, writable root filesystems, root users, missing seccomp/AppArmor where expected, and disabled service-account token restrictions.
- Require resource requests/limits, health probes for long-running services, explicit namespaces, safe image pull policies, immutable image references for production, and least-privilege service accounts.
- Check RBAC for wildcard verbs/resources, cluster-admin grants, broad subjects, and token exposure.
- Require NetworkPolicy or equivalent isolation when workloads handle sensitive data or are reachable from untrusted networks.
- Do not approve Kubernetes Secrets committed with plaintext sensitive values.

## Docker And Containers

- Prefer minimal, maintained base images pinned by digest or immutable version for production images.
- Avoid running as root; add a non-root user and set `USER` unless the image has a documented reason.
- Do not copy secrets, `.env`, credentials, SSH keys, package tokens, or cloud config into images.
- Avoid `latest`, remote `ADD`, unverified downloads, `curl | bash`, package installs from mutable URLs, and broad build contexts that ignore `.dockerignore`.
- Keep build and runtime stages separate; remove package-manager caches and build tools from final runtime images where feasible.
- Flag exposed debug ports, embedded test data, disabled TLS verification, and images that require privileged runtime.

## Cloud Patterns

- AWS: apply Well-Architected security guidance, least-privilege IAM, CloudTrail/auditability, encryption, secure parameters, safe CloudFormation/CDK changes, drift/change-set awareness, and public access controls.
- Azure: apply Well-Architected security guidance, managed identities where feasible, Key Vault for secrets, least-privilege RBAC, private endpoints for sensitive services, secure diagnostics, and safe deployment scopes.
- Google Cloud: apply the Architecture Framework security guidance, service-account least privilege, Workload Identity/OIDC where feasible, Secret Manager, audit logging, perimeter/network controls, and safe public IAM bindings.
- For all clouds, flag hardcoded account identifiers only when they create access, data exposure, or deployment risk; do not treat harmless examples as blockers.

## Application Security

- Review against OWASP Top 10, OWASP ASVS-style controls, and OWASP Code Review guidance.
- Flag injection, command execution, path traversal, SSRF, XSS, CSRF on sensitive state changes, open redirects with attacker-controlled destinations, unsafe deserialization, insecure random generation, auth bypass, authorization bypass, sensitive data exposure, and unsafe file upload/serving.
- Authentication must use explicit, consistent checks. Review login, token validation, session handling, password storage, OAuth/OIDC/SAML flows, webhook validation, API keys, and service-to-service identity.
- Authorization must be enforced server-side per object, tenant, role, scope, and sensitive field. Never rely on frontend-only gates.
- Treat all boundary input as untrusted: HTTP requests, webhooks, queue messages, files, archives, documents, CLI args, environment variables, browser storage, postMessage payloads, and package install scripts.
- Logs, metrics, traces, errors, and review comments must not expose secrets, tokens, PII, payment data, customer data, or sensitive internal topology.

## JavaScript, TypeScript, And React

- Prefer strict TypeScript settings, explicit null/error handling, safe async control flow, and framework-safe APIs.
- Flag `eval`, `new Function`, string timers, unsafe `child_process`, unsafe dynamic imports, prototype pollution, and unbounded regex or recursive parsing.
- For React, rely on escaping by default. Flag unsafe `dangerouslySetInnerHTML`, direct DOM sinks, unsafe URL schemes, untrusted markdown/rich text rendering, frontend-only authorization, token storage in `localStorage`, and permissive `postMessage`.
- For Node/Express-style code, check request validation, CORS, cookies, sessions, CSRF, body limits, file serving, SQL/NoSQL injection, SSRF, command injection, production debug modes, and dependency hygiene.
- Do not approve package additions that introduce install scripts, native code, abandoned packages, or new transitive security risk without justification.

## Python

- Use `secrets` for security randomness, not `random`.
- Avoid unsafe `pickle`, `marshal`, `yaml.load` without a safe loader, dynamic imports from untrusted input, `eval`, `exec`, unsafe `subprocess` shell usage, path joins without normalization, and broad exception swallowing that hides security failures.
- For web frameworks, check schema validation, auth dependencies/middleware, object authorization, CSRF for cookie-authenticated state changes, CORS, host header handling, upload limits, static file safety, debug mode, and production reload settings.
- Require parameterized database access and safe ORM APIs.
- Flag dependency and packaging risks in `requirements*.txt`, `pyproject.toml`, `poetry.lock`, `Pipfile.lock`, and generated dependency reports.

## Dependencies, Packages, And Supply Chain

- Review manifests and lockfiles together. Manifest changes should normally include matching lockfile changes.
- Flag vulnerable, malicious, typosquatted, deprecated, abandoned, or unnecessary packages when visible from the PR context.
- Prefer pinned or bounded versions for production and privileged tooling. Avoid mutable global installs in CI.
- Check package scripts, lifecycle hooks, postinstall behavior, registry changes, package manager config, provenance, signatures, SBOM generation, and release attestation paths.
- Do not auto-approve major version jumps that touch auth, crypto, parsers, serialization, build systems, or deployment tooling without tests and migration evidence.

## Code Quality, Bugs, And Performance

- Analyze changed code for broken control flow, unreachable branches, missing returns, async races, deadlocks, recursive loops, unbounded loops, memory leaks, N+1 queries, excessive allocations, blocking I/O on hot paths, and exception handling gaps.
- Check backwards compatibility, API contracts, migrations, config defaults, data integrity, rollback behavior, and feature flags.
- Require meaningful tests for new user-facing behavior, bug fixes, CI/CD logic, infrastructure behavior, dependencies, and security controls.
- Do not approve skipped, placeholder, import-only, impossible-to-fail, or non-deterministic tests as real coverage.
- Warn when measured project coverage is below 90 percent. Treat missing tests on risky security or deployment behavior as a blocker even when total coverage is unknown.

## Architecture Documentation

- Repositories should include architecture documentation such as `docs/architecture.md`, `ARCHITECTURE.md`, `docs/platform-architecture.md`, or an equivalent Markdown design document.
- Architecture documentation must include Mermaid diagrams for system flow, trust boundaries, CI/CD flow, or deployment/runtime ownership.
- The document should explain system purpose, repository layout, runtime path, scripts, provider dependencies, infrastructure surfaces, security boundaries, compliance evidence, and operational responsibilities.
- Missing architecture documentation is a non-blocking documentation warning by default, but risky platform, security, or infrastructure changes should update the documentation or explain why it remains accurate.

## Compliance Review

- Apply compliance generically based on visible repository obligations, PR text, data handled, and configuration.
- Use the bundled infrastructure compliance catalog when available. It includes GDPR, HIPAA, HITRUST CSF, ISO 27001, NIST AI RMF, NIST SP 800-53 Rev. 5, PCI DSS v4.0.1, and SOC 2 rule IDs.
- For every compliance-relevant finding, map the issue to all applicable framework keys in `compliance_frameworks` and all applicable catalog rule IDs in `compliance_rule_ids`.
- The review body must show one violation-count table per loaded framework, including total loaded rules, violating findings, blocking findings, warnings, severity counts, and distinct violated rule IDs.
- Check access control, separation of duties, audit trails, change traceability, encryption, retention, privacy boundaries, incident visibility, logging controls, secure defaults, and evidence generation.
- Map findings to visible frameworks or control families when useful, including NIST SSDF, CIS Controls, SLSA, OWASP, privacy requirements, and industry-specific controls.
- Report advisory compliance issues with `warning_type: "compliance"` unless the change creates a concrete security or data-protection risk.

## Review Output Expectations

- Return findings for blockers and explicit warnings only.
- Prefer precise changed-line comments.
- Include `rule_id`, `severity`, `blocks_merge`, and `warning_type` when relevant.
- Include `compliance_frameworks` and `compliance_rule_ids` when a finding maps to bundled framework rules.
- Include `super_skill_rule_ids`, `super_skill_sources`, and `best_practice_rule_ids` when a finding maps to bundled Super Skill or official best-practice rules.
- Explain the exploit path, operational risk, compliance concern, or correctness impact.
- Include `suggestion` and `auto_fix: true` only for safe deterministic replacements.
- If a finding cannot map to a changed line, include it in the summary with a clear path.
- Approve only when no blocking findings remain. Warnings may remain on a passing review.
