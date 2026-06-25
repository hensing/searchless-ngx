"""Provider seam for embeddings and chat completions.

The embedding and chat axes are selected independently (EMBEDDING_PROVIDER /
CHAT_PROVIDER, each falling back to LLM_PROVIDER). Supported providers:

  mistral  — Mistral API (EU)
  google   — Google Gemini API
  openai   — OpenAI API
  ollama   — local models via Ollama's OpenAI-compatible endpoint

`openai` and `ollama` share one OpenAI-compatible implementation (so it also fits any
other OpenAI-compatible endpoint, e.g. vLLM/TEI/Jina). Keep this module thin — every
provider implements the same small contracts used by vector_store and mcp_tools.
"""
from typing import Dict, Any, Tuple
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from core.config import settings
from loguru import logger

# Per-provider defaults. embedding_dim is informational (used for the collection
# signature stamp); the authoritative mismatch check is provider + model name. For
# self-hosted models (ollama) the dimension depends on the pulled model, so it is 0.
PROVIDER_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "mistral": {
        "embedding_model": "mistral-embed",
        "embedding_dim": 1024,
        "chat_model": "mistral-small-latest",
    },
    "google": {
        "embedding_model": "models/gemini-embedding-001",
        "embedding_dim": 3072,
        "chat_model": "gemini-flash-latest",
    },
    "openai": {
        "embedding_model": "text-embedding-3-small",
        "embedding_dim": 1536,
        "chat_model": "gpt-4o-mini",
        "base_url": "https://api.openai.com/v1",
    },
    "ollama": {
        # Pin an explicit tag: bare "qwen3-embedding" / ":latest" resolves to the 8B
        # model (4096-dim). 0.6B (1024-dim) is the recommended default for a personal
        # archive — small, fast, plenty good.
        "embedding_model": "qwen3-embedding:0.6b",
        "embedding_dim": 1024,
        "chat_model": "mistral-small",
        "base_url": "http://localhost:11434/v1",
    },
}

# Providers served through the shared OpenAI-compatible client.
_OPENAI_COMPATIBLE = ("openai", "ollama")

# Embedding APIs cap batch size; all providers are safe at 100.
_MAX_EMBED_BATCH = 100


def _import_mistral():
    """Return the Mistral client class, supporting both SDK layouts.

    mistralai >=2 namespaces the client under `mistralai.client`; 1.x exposed it at
    the package root.
    """
    try:
        from mistralai.client import Mistral
    except ImportError:
        from mistralai import Mistral
    return Mistral


def _embedding_provider() -> str:
    return settings.resolved_embedding_provider


def _chat_provider() -> str:
    return settings.resolved_chat_provider


def _embedding_model() -> str:
    return settings.embedding_model or PROVIDER_DEFAULTS[_embedding_provider()]["embedding_model"]


def _chat_model() -> str:
    return settings.chat_model or PROVIDER_DEFAULTS[_chat_provider()]["chat_model"]


def _openai_compatible_config(provider: str) -> Tuple[str, str]:
    """Return (api_key, base_url) for an OpenAI-compatible provider."""
    if provider == "openai":
        base_url = settings.openai_base_url or PROVIDER_DEFAULTS["openai"]["base_url"]
        return settings.openai_api_key, base_url
    if provider == "ollama":
        base_url = settings.ollama_base_url or PROVIDER_DEFAULTS["ollama"]["base_url"]
        # Ollama ignores the key, but the OpenAI SDK requires a non-empty string.
        return (settings.ollama_api_key or "ollama"), base_url
    raise ValueError(f"Not an OpenAI-compatible provider: {provider}")


class GeminiEmbeddingFunction(EmbeddingFunction):
    def __init__(self, api_key: str, model_name: str):
        from google import genai
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name

    def __call__(self, input: Documents) -> Embeddings:
        # Google GenAI BatchEmbedContentsRequest has a limit of 100 requests per batch.
        # We need to manually batch if the input exceeds this limit.
        all_embeddings = []
        for i in range(0, len(input), _MAX_EMBED_BATCH):
            batch = input[i : i + _MAX_EMBED_BATCH]
            result = self.client.models.embed_content(
                model=self.model_name,
                contents=batch
            )
            all_embeddings.extend([e.values for e in result.embeddings])
        return all_embeddings


class MistralEmbeddingFunction(EmbeddingFunction):
    def __init__(self, api_key: str, model_name: str):
        Mistral = _import_mistral()
        self.client = Mistral(api_key=api_key)
        self.model_name = model_name

    def __call__(self, input: Documents) -> Embeddings:
        all_embeddings = []
        for i in range(0, len(input), _MAX_EMBED_BATCH):
            batch = input[i : i + _MAX_EMBED_BATCH]
            result = self.client.embeddings.create(
                model=self.model_name,
                inputs=batch
            )
            all_embeddings.extend([d.embedding for d in result.data])
        return all_embeddings


class OpenAICompatibleEmbeddingFunction(EmbeddingFunction):
    """Embeddings via any OpenAI-compatible endpoint (OpenAI, Ollama, vLLM, TEI, ...)."""

    def __init__(self, api_key: str, base_url: str, model_name: str):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model_name = model_name

    def __call__(self, input: Documents) -> Embeddings:
        all_embeddings = []
        for i in range(0, len(input), _MAX_EMBED_BATCH):
            batch = input[i : i + _MAX_EMBED_BATCH]
            result = self.client.embeddings.create(
                model=self.model_name,
                input=batch
            )
            all_embeddings.extend([d.embedding for d in result.data])
        return all_embeddings


def get_embedding_function() -> EmbeddingFunction:
    """Return the ChromaDB embedding function for the configured embedding provider."""
    provider = _embedding_provider()
    model = _embedding_model()
    if provider == "mistral":
        return MistralEmbeddingFunction(api_key=settings.mistral_api_key, model_name=model)
    if provider == "google":
        return GeminiEmbeddingFunction(api_key=settings.gemini_api_key, model_name=model)
    if provider in _OPENAI_COMPATIBLE:
        api_key, base_url = _openai_compatible_config(provider)
        return OpenAICompatibleEmbeddingFunction(api_key=api_key, base_url=base_url, model_name=model)
    raise ValueError(f"Unknown embedding provider: {provider}")


def embedding_signature() -> Dict[str, Any]:
    """Flat metadata identifying which embeddings a collection holds.

    Stamped into the ChromaDB collection on creation and compared on every open so a
    provider/model switch is caught loudly instead of corrupting the vector space.
    """
    provider = _embedding_provider()
    return {
        "embedding_provider": provider,
        "embedding_model": _embedding_model(),
        "embedding_dim": PROVIDER_DEFAULTS[provider].get("embedding_dim", 0),
    }


# Cache the chat client across calls (the fuzzy matcher is called repeatedly).
_chat_client = None
_chat_client_provider = None


def chat_complete(prompt: str) -> str:
    """Single deterministic text completion for the fuzzy-match helper.

    Synchronous on purpose — callers wrap it in asyncio.to_thread.
    """
    global _chat_client, _chat_client_provider
    provider = _chat_provider()

    if _chat_client is None or _chat_client_provider != provider:
        if provider == "mistral":
            Mistral = _import_mistral()
            _chat_client = Mistral(api_key=settings.mistral_api_key)
        elif provider == "google":
            from google import genai
            _chat_client = genai.Client(api_key=settings.gemini_api_key)
        elif provider in _OPENAI_COMPATIBLE:
            from openai import OpenAI
            api_key, base_url = _openai_compatible_config(provider)
            _chat_client = OpenAI(api_key=api_key, base_url=base_url)
        else:
            raise ValueError(f"Unknown chat provider: {provider}")
        _chat_client_provider = provider

    if provider == "mistral":
        resp = _chat_client.chat.complete(
            model=_chat_model(),
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        return (resp.choices[0].message.content or "").strip()

    if provider in _OPENAI_COMPATIBLE:
        resp = _chat_client.chat.completions.create(
            model=_chat_model(),
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        return (resp.choices[0].message.content or "").strip()

    resp = _chat_client.models.generate_content(
        model=_chat_model(),
        contents=prompt,
    )
    return (resp.text or "").strip()
