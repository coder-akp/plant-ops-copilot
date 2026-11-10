"""Model factory: selects the LLM used by the agents.

provider = gemini  -> Gemini API (free tier available), native ADK integration
provider = azure   -> Azure OpenAI / Microsoft Foundry deployment through LiteLLM
provider = mock    -> scripted, deterministic stand-in (tests and offline development)
provider = none    -> live runs disabled (the web app serves recordings only)
"""
from __future__ import annotations

from google.genai import types

from app.config import Settings


def build_model(settings: Settings):
    """Return the object to pass as ``model=`` to an ADK LlmAgent."""
    provider = settings.provider
    if provider == "gemini":
        return settings.gemini_model
    if provider == "azure":
        missing = [
            name
            for name, value in {
                "AZURE_OPENAI_ENDPOINT": settings.azure_endpoint,
                "AZURE_OPENAI_API_KEY": settings.azure_api_key,
                "AZURE_OPENAI_DEPLOYMENT": settings.azure_deployment,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError(f"provider 'azure' needs these environment variables: {', '.join(missing)}")
        from google.adk.models.lite_llm import LiteLlm

        kwargs: dict = {
            "api_base": settings.azure_endpoint,
            "api_key": settings.azure_api_key,
            "api_version": settings.azure_api_version,
            "drop_params": True,  # drop parameters the model does not support (for example, temperature on GPT-5)
        }
        if settings.azure_reasoning_effort:
            kwargs["reasoning_effort"] = settings.azure_reasoning_effort
        return LiteLlm(model=f"azure/{settings.azure_deployment}", **kwargs)
    if provider == "mock":
        from app.mock_llm import ScriptedLlm

        return ScriptedLlm(model="scripted-v1")
    raise RuntimeError(f"no model available for provider {provider!r}")


def generation_config(settings: Settings) -> types.GenerateContentConfig:
    """Return shared generation settings: deterministic output with a token cap."""
    kwargs: dict = {"temperature": 0.0, "max_output_tokens": settings.max_output_tokens}
    if settings.provider == "gemini" and "2.5-flash" in settings.gemini_model:
        # Disable thinking tokens: lower cost and latency, and the output limit applies to the answer only
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    return types.GenerateContentConfig(**kwargs)
