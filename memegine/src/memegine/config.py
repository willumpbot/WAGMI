from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_prefix="MEMEGINE_",
        extra="ignore",
    )

    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")

    ideation_model: str = "claude-opus-4-7"
    utility_model: str = "claude-sonnet-4-6"

    data_dir: Path = REPO_ROOT / "data"
    codex_path: Path = REPO_ROOT / "data" / "codex" / "style.md"
    references_dir: Path = REPO_ROOT / "data" / "references"
    outputs_dir: Path = REPO_ROOT / "data" / "outputs"
    logs_dir: Path = REPO_ROOT / "data" / "logs"

    def ensure_dirs(self) -> None:
        for p in [self.data_dir, self.codex_path.parent, self.references_dir, self.outputs_dir, self.logs_dir]:
            p.mkdir(parents=True, exist_ok=True)


settings = Settings()
