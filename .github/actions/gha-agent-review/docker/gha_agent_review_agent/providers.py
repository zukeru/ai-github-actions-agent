import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

import boto3


SYSTEM_PROMPT = (
    "You are a strict GHA AI Agent and compliance PR reviewer. You return only valid JSON and "
    "only report concrete, actionable findings tied to the pull request. Critical and high issues "
    "block merge unless they are explicitly compliance advisories or runner warnings. "
    "Compliance advisories and custom runner issues are warnings and must set blocks_merge false."
)

PROVIDER_ALIASES = {
    "auto": "auto",
    "aws": "bedrock",
    "bedrock": "bedrock",
    "anthropic": "anthropic",
    "claude": "anthropic",
    "openai": "openai",
    "azure": "azure-openai",
    "azure-openai": "azure-openai",
    "azure_openai": "azure-openai",
    "google": "google",
    "gemini": "google",
}


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    model_id: str
    aws_region: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    azure_openai_api_key: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_api_version: str = "2024-10-21"
    google_api_key: str = ""


def env_value(env: Mapping[str, str], *names: str) -> str:
    for name in names:
        value = str(env.get(name) or "").strip()
        if value:
            return value
    return ""


def normalize_provider(provider: str) -> str:
    normalized = str(provider or "auto").strip().lower()
    if not normalized:
        normalized = "auto"
    if normalized not in PROVIDER_ALIASES:
        raise ValueError(
            f"Unsupported provider `{provider}`. Use auto, bedrock, anthropic, openai, azure-openai, or google."
        )
    return PROVIDER_ALIASES[normalized]


def resolve_provider(
    *,
    provider: str,
    model_id: str,
    aws_region: str,
    azure_openai_endpoint: str,
    azure_openai_api_version: str,
    env: Optional[Mapping[str, str]] = None,
) -> ProviderConfig:
    env = env or os.environ
    requested_provider = normalize_provider(provider)
    anthropic_key = env_value(
        env,
        "ANTHROPIC_API_KEY",
        "CLAUDE_API_KEY",
        "GHA_AI_AGENT_ANTHROPIC_API_KEY",
        "GHA_AI_AGENT_CLAUDE_API_KEY",
    )
    openai_key = env_value(env, "OPENAI_API_KEY", "GHA_AI_AGENT_OPENAI_API_KEY")
    azure_key = env_value(env, "AZURE_OPENAI_API_KEY", "GHA_AI_AGENT_AZURE_OPENAI_API_KEY")
    google_key = env_value(env, "GOOGLE_API_KEY", "GEMINI_API_KEY", "GHA_AI_AGENT_GOOGLE_API_KEY")
    azure_management_ready = bool(
        env_value(env, "AZURE_ACCESS_TOKEN", "GHA_AI_AGENT_AZURE_ACCESS_TOKEN")
        and env_value(env, "AZURE_SUBSCRIPTION_ID", "GHA_AI_AGENT_AZURE_SUBSCRIPTION_ID")
        and env_value(env, "AZURE_RESOURCE_GROUP", "GHA_AI_AGENT_AZURE_RESOURCE_GROUP")
        and env_value(env, "AZURE_OPENAI_ACCOUNT_NAME", "GHA_AI_AGENT_AZURE_OPENAI_ACCOUNT_NAME")
    )
    azure_endpoint = azure_openai_endpoint.strip() or env_value(
        env,
        "AZURE_OPENAI_ENDPOINT",
        "GHA_AI_AGENT_AZURE_OPENAI_ENDPOINT",
    )
    api_version = (
        azure_openai_api_version.strip()
        or env_value(env, "AZURE_OPENAI_API_VERSION", "GHA_AI_AGENT_AZURE_OPENAI_API_VERSION")
        or "2024-10-21"
    )
    if requested_provider == "auto":
        if (azure_key and azure_endpoint) or azure_management_ready:
            requested_provider = "azure-openai"
        elif anthropic_key:
            requested_provider = "anthropic"
        elif openai_key:
            requested_provider = "openai"
        elif google_key:
            requested_provider = "google"
        else:
            requested_provider = "bedrock"

    model_env_names = {
        "bedrock": ("GHA_AI_AGENT_MODEL_ID", "BEDROCK_MODEL_ID"),
        "anthropic": ("GHA_AI_AGENT_MODEL_ID", "ANTHROPIC_MODEL_ID", "CLAUDE_MODEL_ID", "GHA_AI_AGENT_CLAUDE_MODEL_ID"),
        "openai": ("GHA_AI_AGENT_MODEL_ID", "OPENAI_MODEL_ID"),
        "azure-openai": ("GHA_AI_AGENT_MODEL_ID", "AZURE_OPENAI_DEPLOYMENT", "AZURE_OPENAI_MODEL_ID"),
        "google": ("GHA_AI_AGENT_MODEL_ID", "GOOGLE_MODEL_ID", "GEMINI_MODEL_ID"),
    }
    resolved_model_id = model_id.strip() or env_value(env, *model_env_names[requested_provider])

    if not resolved_model_id:
        raise ValueError("model-id is required for the selected model provider.")
    if requested_provider == "anthropic" and not anthropic_key:
        raise ValueError("ANTHROPIC_API_KEY or CLAUDE_API_KEY is required for provider `anthropic`.")
    if requested_provider == "openai" and not openai_key:
        raise ValueError("OPENAI_API_KEY is required for provider `openai`.")
    if requested_provider == "azure-openai" and (not azure_key or not azure_endpoint) and not azure_management_ready:
        raise ValueError("AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT are required for provider `azure-openai`.")
    if requested_provider == "google" and not google_key:
        raise ValueError("GOOGLE_API_KEY or GEMINI_API_KEY is required for provider `google`.")
    if requested_provider == "bedrock" and not aws_region:
        raise ValueError("aws-region is required for provider `bedrock`.")

    return ProviderConfig(
        provider=requested_provider,
        model_id=resolved_model_id,
        aws_region=aws_region,
        anthropic_api_key=anthropic_key,
        openai_api_key=openai_key,
        azure_openai_api_key=azure_key,
        azure_openai_endpoint=azure_endpoint,
        azure_openai_api_version=api_version,
        google_api_key=google_key,
    )


def post_json(url: str, headers: Dict[str, str], payload: Dict[str, Any]) -> Dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Provider request failed: {exc.code} {url}: {details}") from exc


def response_text_from_openai(data: Dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    output_parts = []
    for output in data.get("output") or []:
        for content in output.get("content") or []:
            text = content.get("text")
            if isinstance(text, str):
                output_parts.append(text)
    return "\n".join(output_parts)


def response_text_from_anthropic(data: Dict[str, Any]) -> str:
    return "\n".join(
        str(part.get("text") or "")
        for part in data.get("content") or []
        if isinstance(part, dict) and part.get("type") == "text"
    )


def response_text_from_google(data: Dict[str, Any]) -> str:
    texts = []
    for candidate in data.get("candidates") or []:
        content = candidate.get("content") or {}
        for part in content.get("parts") or []:
            text = part.get("text")
            if isinstance(text, str):
                texts.append(text)
    return "\n".join(texts)


def invoke_bedrock(config: ProviderConfig, prompt: str, max_tokens: int) -> str:
    client = boto3.client("bedrock-runtime", region_name=config.aws_region)
    response = client.converse(
        modelId=config.model_id,
        system=[{"text": SYSTEM_PROMPT}],
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": max_tokens, "temperature": 0},
    )
    content = response["output"]["message"]["content"]
    return "\n".join(part.get("text", "") for part in content if "text" in part)


def invoke_anthropic(config: ProviderConfig, prompt: str, max_tokens: int) -> str:
    data = post_json(
        "https://api.anthropic.com/v1/messages",
        {
            "x-api-key": config.anthropic_api_key,
            "anthropic-version": "2023-06-01",
        },
        {
            "model": config.model_id,
            "max_tokens": max_tokens,
            "temperature": 0,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": prompt}],
        },
    )
    return response_text_from_anthropic(data)


def invoke_openai(config: ProviderConfig, prompt: str, max_tokens: int) -> str:
    data = post_json(
        "https://api.openai.com/v1/responses",
        {"Authorization": f"Bearer {config.openai_api_key}"},
        {
            "model": config.model_id,
            "instructions": SYSTEM_PROMPT,
            "input": prompt,
            "max_output_tokens": max_tokens,
        },
    )
    return response_text_from_openai(data)


def invoke_azure_openai(config: ProviderConfig, prompt: str, max_tokens: int) -> str:
    endpoint = config.azure_openai_endpoint.rstrip("/")
    deployment = urllib.parse.quote(config.model_id, safe="")
    api_version = urllib.parse.quote(config.azure_openai_api_version, safe="")
    data = post_json(
        f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}",
        {"api-key": config.azure_openai_api_key},
        {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": 0,
        },
    )
    choices = data.get("choices") or []
    if not choices:
        return ""
    return str(((choices[0].get("message") or {}).get("content")) or "")


def invoke_google(config: ProviderConfig, prompt: str, max_tokens: int) -> str:
    model = urllib.parse.quote(config.model_id, safe="")
    data = post_json(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        {"x-goog-api-key": config.google_api_key},
        {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": 0,
            },
        },
    )
    return response_text_from_google(data)


def invoke_provider(config: ProviderConfig, prompt: str, max_tokens: int = 4096) -> str:
    if config.provider == "bedrock":
        return invoke_bedrock(config, prompt, max_tokens)
    if config.provider == "anthropic":
        return invoke_anthropic(config, prompt, max_tokens)
    if config.provider == "openai":
        return invoke_openai(config, prompt, max_tokens)
    if config.provider == "azure-openai":
        return invoke_azure_openai(config, prompt, max_tokens)
    if config.provider == "google":
        return invoke_google(config, prompt, max_tokens)
    raise ValueError(f"Unsupported provider `{config.provider}`.")
