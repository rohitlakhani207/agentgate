"""Settings, read from the environment (or .env) with the AGENTGATE_ prefix."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Provider = Literal["ollama", "groq", "gemini"]
GateMode = Literal["two_step", "decider", "clef", "llm_judge", "classifier", "keyword", "none"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENTGATE_", env_file=".env", extra="ignore", populate_by_name=True
    )

    # Agent LLM
    llm_provider: Provider = "ollama"
    llm_small_model: str = "qwen3.5:4b"
    llm_large_model: str = "gemma4:12b"
    ollama_url: str = "http://localhost:11434"
    groq_api_key: str = Field(default="", validation_alias="GROQ_API_KEY")
    google_api_key: str = Field(default="", validation_alias="GOOGLE_API_KEY")

    # LLM-as-judge baseline; empty means "same as the agent, large model".
    judge_provider: Provider | Literal[""] = ""
    judge_model: str = ""

    # Decision models
    decider_url: str = "http://localhost:8001"
    clef_url: str = "http://localhost:8002"
    # local: a llama-server at clef_url. cloudflare: Cloudflare Workers AI (free tier).
    clef_backend: Literal["local", "cloudflare"] = "local"
    cloudflare_account_id: str = Field(default="", validation_alias="CLOUDFLARE_ACCOUNT_ID")
    cloudflare_api_token: str = Field(default="", validation_alias="CLOUDFLARE_API_TOKEN")
    cloudflare_clef_model: str = "@cf/cloudflare/clef-flash"
    decider_threshold: float = 0.9
    clef_threshold: float = 0.5
    step2: Literal["clef", "llm_judge"] = "clef"
    gate: GateMode = "two_step"
    router: bool = True
    systemone_timeout_s: float = 30.0

    # Phone approval
    server_url: str = "http://localhost:8080"
    token: str = ""
    token_file: Path = Path("./var/token")
    approval_timeout_s: float = 60.0

    # Sandbox, audit, email
    sandbox_dir: Path = Path("./sandbox")
    audit_db: Path = Path("./var/audit.sqlite")
    outbox_dir: Path = Path("./var/outbox")
    classifier_path: Path = Path("./models/classifier.joblib")
    email_mode: Literal["outbox", "smtp"] = "outbox"
    email_self: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""

    def resolve_token(self) -> str:
        """The shared secret: AGENTGATE_TOKEN, or one generated once and kept in var/token,
        so the server, the agent and the phone agree without any setup."""
        if self.token:
            return self.token
        if self.token_file.exists():
            return self.token_file.read_text().strip()
        import secrets

        token = secrets.token_urlsafe(18)
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(token)
        self.token_file.chmod(0o600)
        return token

    def clef_client(self):
        """The step-2 System One client, wherever Clef-flash is served from."""
        from .systemone import SystemOneClient, cloudflare_client

        if self.clef_backend == "cloudflare":
            if not (self.cloudflare_account_id.strip() and self.cloudflare_api_token.strip()):
                raise ValueError(
                    "AGENTGATE_CLEF_BACKEND=cloudflare needs CLOUDFLARE_ACCOUNT_ID and "
                    "CLOUDFLARE_API_TOKEN in .env"
                )
            return cloudflare_client(
                self.cloudflare_account_id.strip(),
                self.cloudflare_api_token.strip(),
                self.cloudflare_clef_model,
                timeout_s=self.systemone_timeout_s,
            )
        return SystemOneClient(self.clef_url, timeout_s=self.systemone_timeout_s)

    @property
    def clef_location(self) -> str:
        if self.clef_backend == "cloudflare":
            return f"Cloudflare Workers AI ({self.cloudflare_clef_model})"
        return self.clef_url

    @property
    def effective_judge_provider(self) -> Provider:
        return self.judge_provider or self.llm_provider

    @property
    def effective_judge_model(self) -> str:
        return self.judge_model or self.llm_large_model


@lru_cache
def get_settings() -> Settings:
    return Settings()
