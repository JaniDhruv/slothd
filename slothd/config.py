"""Configuration and settings for slothd."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field


class SlothdConfig(BaseModel):
    """Main configuration for slothd."""

    # Target directories to organize
    target_dirs: list[Path] = Field(
        default_factory=lambda: [Path.home() / "Downloads"],
        description="Directories to scan and organize",
    )

    # Output base directory (organized files go here)
    output_dir: Path | None = Field(
        default=None,
        description="Base directory for organized files. If None, organizes in-place.",
    )

    # Ollama settings
    ollama_host: str = Field(
        default="http://localhost:11434",
        description="Ollama API host URL",
    )
    ollama_model: str = Field(
        default="gemma3",
        description="Ollama model for vision/text classification",
    )
    embed_model: str = Field(
        default="nomic-embed-text",
        description="Ollama model for generating embeddings",
    )

    # Idle detection
    idle_threshold_seconds: int = Field(
        default=300,
        description="System idle time (seconds) before daemon activates",
    )

    # Database (Tiger Data pgvector)
    db_url: str = Field(
        default="postgresql://slothd:slothd@localhost:5432/slothd",
        description="PostgreSQL connection string for Tiger Data pgvector",
    )

    # SQLite for operation logs (local, no setup needed)
    ops_db_path: Path = Field(
        default_factory=lambda: Path.home() / ".slothd" / "operations.db",
        description="Path to SQLite database for operation logs / undo history",
    )

    # SerpApi (optional, --enrich-online)
    serpapi_key: str | None = Field(
        default=None,
        description="SerpApi API key for optional web grounding",
    )

    # Sentry (optional)
    sentry_dsn: str | None = Field(
        default=None,
        description="Sentry DSN for agent tracing",
    )

    # ElevenLabs (optional)
    elevenlabs_api_key: str | None = Field(
        default=None,
        description="ElevenLabs API key for voice summaries",
    )
    elevenlabs_voice_id: str = Field(
        default="JBFqnCBsd6RMkjVDRZzb",
        description="ElevenLabs voice ID (default: George / warm narrator)",
    )

    # File processing limits
    max_file_size_mb: int = Field(
        default=50,
        description="Maximum file size to process (MB)",
    )
    batch_size: int = Field(
        default=20,
        description="Number of files to process per batch",
    )
    dry_run: bool = Field(
        default=True,
        description="If True, only preview changes without moving files",
    )

    @classmethod
    def from_env(cls) -> SlothdConfig:
        """Load configuration from environment variables (including .env file)."""
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass

        kwargs: dict = {}
        if target := os.getenv("SLOTHD_TARGET_DIRS"):
            kwargs["target_dirs"] = [Path(p.strip()) for p in target.split(",")]
        if output := os.getenv("SLOTHD_OUTPUT_DIR"):
            kwargs["output_dir"] = Path(output)
        if host := os.getenv("SLOTHD_OLLAMA_HOST"):
            kwargs["ollama_host"] = host
        if model := os.getenv("SLOTHD_OLLAMA_MODEL"):
            kwargs["ollama_model"] = model
        if db := os.getenv("SLOTHD_DB_URL"):
            kwargs["db_url"] = db
        if key := os.getenv("SERPAPI_KEY"):
            kwargs["serpapi_key"] = key
        if dsn := os.getenv("SENTRY_DSN"):
            kwargs["sentry_dsn"] = dsn
        if el_key := os.getenv("ELEVENLABS_API_KEY"):
            kwargs["elevenlabs_api_key"] = el_key
        if el_voice := os.getenv("ELEVENLABS_VOICE_ID"):
            kwargs["elevenlabs_voice_id"] = el_voice
        if embed := os.getenv("SLOTHD_EMBED_MODEL"):
            kwargs["embed_model"] = embed
        return cls(**kwargs)
