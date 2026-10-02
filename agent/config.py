"""Load local settings without showing secret values."""

import os
from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseModel):
    """Keep API keys and bounded request settings in one place."""

    model_config = ConfigDict(frozen=True)
    news_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    fred_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    sec_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    openai_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    langsmith_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    request_timeout: float = Field(default=15, ge=1, le=60)
    yahoo_timeout: float = Field(default=45, ge=1, le=120)
    max_retries: int = Field(default=0, ge=0, le=2)
    openai_model: str = Field(default="gpt-4.1-nano", min_length=1)
    llm_timeout: float = Field(default=30, ge=1, le=120)
    llm_max_tokens: int = Field(default=1200, ge=200, le=3000)
    llm_input_chars: int = Field(default=24000, ge=4000, le=50000)
    news_candidate_limit: int = Field(default=20, ge=5, le=100)
    news_lookback_days: int = Field(default=14, ge=1, le=30)
    news_article_limit: int = Field(default=3, ge=1, le=5)
    news_text_chars: int = Field(default=1200, ge=200, le=2500)
    max_revisions: int = Field(default=1, ge=0, le=2)
    evaluation_threshold: int = Field(default=4, ge=1, le=5)
    memory_path: Path = ROOT / "memory" / "notes.json"
    langsmith_tracing: bool = False
    langsmith_project: str = "AAI520-multi-agent-financial-analyst"

    @model_validator(mode="after")
    def check_news_limits(self):
        """Keep retrieval large enough for the analysis selection."""
        if self.news_candidate_limit < self.news_article_limit:
            raise ValueError("News candidate limit is below analysis limit.")
        return self

    @classmethod
    def load(
        cls,
        env_file: Path | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> "Settings":
        """Read one explicit file. Process settings take priority."""
        path = env_file if env_file is not None else ROOT / ".env"
        values = dict(dotenv_values(path, interpolate=False))
        values.update(os.environ if environ is None else environ)
        selected = {
            field: values[field.upper()].strip()
            for field in cls.model_fields
            if values.get(field.upper()) and values[field.upper()].strip()
        }
        return cls(**selected)
