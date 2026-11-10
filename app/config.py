"""Runtime settings, read from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env_file(path: Path | None = None) -> None:
    """Load KEY=VALUE lines from a local .env file.

    Variables that are already set in the environment take precedence. Intended for
    local development only: in the cloud, the platform provides the environment
    variables and no .env file exists.
    """
    path = path or ROOT / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _float(name: str, default: float) -> float:
    raw = _env(name)
    return float(raw) if raw else default


def _int(name: str, default: int) -> int:
    raw = _env(name)
    return int(raw) if raw else default


def _bool(name: str, default: bool) -> bool:
    raw = _env(name).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


# List prices in USD per 1M tokens (input, output). Used only for the estimated cost shown in the UI.
DEFAULT_PRICES = {
    "azure": (0.25, 2.00),   # example GPT-5 mini list price; verify against the Azure pricing page
    "gemini": (0.0, 0.0),    # free tier
    "mock": (0.0, 0.0),
    "none": (0.0, 0.0),
}


@dataclass
class Settings:
    # Data locations
    db_path: Path = ROOT / "data" / "plantops.duckdb"
    replay_dir: Path = ROOT / "app" / "replays"

    # Model provider: none | mock | gemini | azure
    provider: str = "none"
    gemini_model: str = "gemini-2.5-flash"
    azure_endpoint: str = ""
    azure_api_key: str = field(default="", repr=False)
    azure_deployment: str = ""
    azure_api_version: str = "2025-04-01-preview"
    azure_reasoning_effort: str = ""
    max_output_tokens: int = 2500

    # Prices for the estimated-cost display (USD per 1M tokens)
    price_in_per_m: float = 0.0
    price_out_per_m: float = 0.0

    # Cost and abuse guards for live runs
    live_enabled: bool = True
    daily_max_runs: int = 25
    per_ip_max_runs: int = 3
    daily_budget_usd: float = 0.50
    cooldown_s: float = 15.0
    max_run_tokens: int = 60_000
    run_timeout_s: float = 120.0
    access_code: str = field(default="", repr=False)

    # Display
    github_url: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        load_env_file()
        provider = _env("LLM_PROVIDER", "none").lower()
        if provider not in DEFAULT_PRICES:
            raise ValueError(f"LLM_PROVIDER must be one of {sorted(DEFAULT_PRICES)}, got {provider!r}")
        p_in, p_out = DEFAULT_PRICES[provider]
        return cls(
            db_path=Path(_env("PLANTOPS_DB") or ROOT / "data" / "plantops.duckdb"),
            replay_dir=Path(_env("REPLAY_DIR") or ROOT / "app" / "replays"),
            provider=provider,
            gemini_model=_env("GEMINI_MODEL", "gemini-2.5-flash"),
            azure_endpoint=_env("AZURE_OPENAI_ENDPOINT"),
            azure_api_key=_env("AZURE_OPENAI_API_KEY"),
            azure_deployment=_env("AZURE_OPENAI_DEPLOYMENT"),
            azure_api_version=_env("AZURE_OPENAI_API_VERSION", "2025-04-01-preview"),
            azure_reasoning_effort=_env("AZURE_REASONING_EFFORT"),
            max_output_tokens=_int("MAX_OUTPUT_TOKENS", 2500),
            price_in_per_m=_float("PRICE_IN_PER_M", p_in),
            price_out_per_m=_float("PRICE_OUT_PER_M", p_out),
            live_enabled=_bool("LIVE_ENABLED", True),
            daily_max_runs=_int("DAILY_MAX_RUNS", 25),
            per_ip_max_runs=_int("PER_IP_MAX_RUNS", 3),
            daily_budget_usd=_float("DAILY_BUDGET_USD", 0.50),
            cooldown_s=_float("LIVE_COOLDOWN_S", 15.0),
            max_run_tokens=_int("MAX_RUN_TOKENS", 60_000),
            run_timeout_s=_float("RUN_TIMEOUT_S", 120.0),
            access_code=_env("ACCESS_CODE"),
            github_url=_env("GITHUB_URL"),
        )

    @property
    def model_label(self) -> str:
        if self.provider == "gemini":
            return self.gemini_model
        if self.provider == "azure":
            return f"azure/{self.azure_deployment}"
        if self.provider == "mock":
            return "scripted (no LLM)"
        return "none"

    def estimate_cost(self, prompt_tokens: int, output_tokens: int) -> float:
        return (prompt_tokens * self.price_in_per_m + output_tokens * self.price_out_per_m) / 1_000_000
