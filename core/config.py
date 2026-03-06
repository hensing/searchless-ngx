from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    paperless_url: str
    paperless_token: str
    gemini_api_key: str

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

    @property
    def public_url(self) -> str:
        return self.paperless_public_url or self.paperless_url


    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
