from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator
from typing import Optional

class Settings(BaseSettings):
    paperless_url: str
    paperless_token: str

    # Umbrella default provider used for any axis that is not overridden below.
    # Supported: "mistral", "google", "openai", "ollama". Best-of-breed setups can
    # split the two axes:
    #   EMBEDDING_PROVIDER → vector-store embeddings (retrieval quality)
    #   CHAT_PROVIDER      → fuzzy-match chat call
    # Each falls back to LLM_PROVIDER when left unset.
    llm_provider: str = "mistral"
    embedding_provider: Optional[str] = None
    chat_provider: Optional[str] = None
    mistral_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    # Base URL override for the "openai" provider (e.g. another OpenAI-compatible host).
    openai_base_url: Optional[str] = None
    # Ollama's OpenAI-compatible endpoint. In Docker use http://host.docker.internal:11434/v1
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_api_key: Optional[str] = None
    # Optional model overrides. When None, the provider default is used
    # (see core/providers.py: PROVIDER_DEFAULTS).
    embedding_model: Optional[str] = None
    chat_model: Optional[str] = None

    # Optional parameters with defaults
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8001
    chroma_host: str = "chromadb"
    chroma_port: int = 8000
    log_level: str = "INFO"
    bulk_sync_limit: Optional[int] = None
    paperless_public_url: Optional[str] = None
    # Maximum chunks per document (100 chunks ≈ 25 DIN-A4 pages)
    max_chunks_per_doc: int = 100
    # Periodic background sync interval in minutes (0 = disabled)
    sync_interval_minutes: int = 15

    @property
    def public_url(self) -> str:
        return self.paperless_public_url or self.paperless_url

    @property
    def resolved_embedding_provider(self) -> str:
        return (self.embedding_provider or self.llm_provider or "mistral").lower()

    @property
    def resolved_chat_provider(self) -> str:
        return (self.chat_provider or self.llm_provider or "mistral").lower()

    @model_validator(mode="after")
    def _check_provider_keys(self) -> "Settings":
        valid = ("mistral", "google", "openai", "ollama")
        for axis, provider in (
            ("EMBEDDING_PROVIDER", self.resolved_embedding_provider),
            ("CHAT_PROVIDER", self.resolved_chat_provider),
        ):
            if provider not in valid:
                raise ValueError(
                    f"{axis} must resolve to one of {valid}, got '{provider}'."
                )
        # API keys are required only for the cloud providers actually in use.
        # ollama is local and needs no key.
        required_keys = {
            "mistral": ("mistral_api_key", "MISTRAL_API_KEY"),
            "google": ("gemini_api_key", "GEMINI_API_KEY"),
            "openai": ("openai_api_key", "OPENAI_API_KEY"),
        }
        in_use = {self.resolved_embedding_provider, self.resolved_chat_provider}
        for provider in in_use:
            if provider in required_keys:
                attr, env_name = required_keys[provider]
                if not getattr(self, attr):
                    raise ValueError(
                        f"Provider '{provider}' is in use but {env_name} is not set."
                    )
        return self


    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
