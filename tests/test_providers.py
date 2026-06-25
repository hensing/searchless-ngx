import pytest
from unittest.mock import MagicMock
import core.providers as providers
from core.config import Settings


# --- Mistral embedding function batching -----------------------------------

def test_mistral_embedding_function_batching():
    """MistralEmbeddingFunction batches inputs at 100 like the Gemini one."""
    embedding_fn = providers.MistralEmbeddingFunction(api_key="test", model_name="mistral-embed")
    mock_client = MagicMock()
    embedding_fn.client = mock_client

    def mock_create(model, inputs):
        result = MagicMock()
        # 1024-dim vectors, one per input
        result.data = [MagicMock(embedding=[0.0] * 1024) for _ in inputs]
        return result

    mock_client.embeddings.create.side_effect = mock_create

    # 250 inputs -> 3 calls (100, 100, 50)
    results = embedding_fn(["text"] * 250)
    assert len(results) == 250
    assert mock_client.embeddings.create.call_count == 3
    calls = mock_client.embeddings.create.call_args_list
    assert len(calls[0].kwargs["inputs"]) == 100
    assert len(calls[2].kwargs["inputs"]) == 50
    assert len(results[0]) == 1024


# --- chat_complete provider dispatch ---------------------------------------

def _reset_chat_cache():
    providers._chat_client = None
    providers._chat_client_provider = None


def test_chat_complete_mistral(monkeypatch):
    monkeypatch.setattr(providers.settings, "llm_provider", "mistral")
    _reset_chat_cache()

    mock_client = MagicMock()
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content="  Deutsche Bahn  "))]
    mock_client.chat.complete.return_value = resp
    # Pre-seed the cache so we don't construct a real SDK client.
    providers._chat_client = mock_client
    providers._chat_client_provider = "mistral"

    out = providers.chat_complete("match DB")
    assert out == "Deutsche Bahn"
    kwargs = mock_client.chat.complete.call_args.kwargs
    assert kwargs["model"] == "mistral-small-latest"
    assert kwargs["temperature"] == 0
    _reset_chat_cache()


def test_chat_complete_google(monkeypatch):
    monkeypatch.setattr(providers.settings, "llm_provider", "google")
    _reset_chat_cache()

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = MagicMock(text="Amazon\n")
    providers._chat_client = mock_client
    providers._chat_client_provider = "google"

    out = providers.chat_complete("match amazn")
    assert out == "Amazon"
    assert mock_client.models.generate_content.call_args.kwargs["model"] == "gemini-flash-latest"
    _reset_chat_cache()


# --- embedding signature ----------------------------------------------------

def test_embedding_signature(monkeypatch):
    monkeypatch.setattr(providers.settings, "llm_provider", "mistral")
    monkeypatch.setattr(providers.settings, "embedding_model", None)
    sig = providers.embedding_signature()
    assert sig == {
        "embedding_provider": "mistral",
        "embedding_model": "mistral-embed",
        "embedding_dim": 1024,
    }


# --- config validation ------------------------------------------------------

def test_config_requires_mistral_key(monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    with pytest.raises(ValueError, match="MISTRAL_API_KEY"):
        Settings(llm_provider="mistral", mistral_api_key=None)


def test_config_requires_gemini_key():
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        Settings(llm_provider="google", gemini_api_key=None)


def test_config_rejects_unknown_provider():
    with pytest.raises(ValueError, match="must resolve to one of"):
        Settings(llm_provider="bogus", mistral_api_key="x")


# --- split embedding/chat providers ----------------------------------------

def test_split_provider_resolution():
    s = Settings(
        embedding_provider="google",
        chat_provider="mistral",
        gemini_api_key="g",
        mistral_api_key="m",
    )
    assert s.resolved_embedding_provider == "google"
    assert s.resolved_chat_provider == "mistral"


def test_split_falls_back_to_umbrella():
    s = Settings(llm_provider="google", gemini_api_key="g")
    # Neither axis overridden → both resolve to the umbrella provider.
    assert s.resolved_embedding_provider == "google"
    assert s.resolved_chat_provider == "google"


def test_split_requires_both_keys():
    # google embeddings + mistral chat needs both keys present.
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        Settings(
            embedding_provider="google",
            chat_provider="mistral",
            gemini_api_key=None,
            mistral_api_key="m",
        )


def test_openai_compatible_embedding_batching():
    """OpenAICompatibleEmbeddingFunction batches at 100 and reads .data[].embedding."""
    fn = providers.OpenAICompatibleEmbeddingFunction(
        api_key="x", base_url="http://localhost:11434/v1", model_name="qwen3-embedding"
    )
    mock_client = MagicMock()
    fn.client = mock_client

    def mock_create(model, input):
        result = MagicMock()
        result.data = [MagicMock(embedding=[0.0] * 1024) for _ in input]
        return result

    mock_client.embeddings.create.side_effect = mock_create

    results = fn(["text"] * 150)
    assert len(results) == 150
    assert mock_client.embeddings.create.call_count == 2
    assert len(mock_client.embeddings.create.call_args_list[0].kwargs["input"]) == 100


def test_chat_complete_ollama(monkeypatch):
    monkeypatch.setattr(providers.settings, "chat_provider", "ollama")
    monkeypatch.setattr(providers.settings, "chat_model", None)
    _reset_chat_cache()

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=" Deutsche Bahn "))]
    )
    providers._chat_client = mock_client
    providers._chat_client_provider = "ollama"

    assert providers.chat_complete("match DB") == "Deutsche Bahn"
    kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "mistral-small"
    assert kwargs["temperature"] == 0
    _reset_chat_cache()


def test_ollama_embedding_signature(monkeypatch):
    monkeypatch.setattr(providers.settings, "embedding_provider", "ollama")
    monkeypatch.setattr(providers.settings, "embedding_model", None)
    sig = providers.embedding_signature()
    assert sig["embedding_provider"] == "ollama"
    assert sig["embedding_model"] == "qwen3-embedding:0.6b"
    assert sig["embedding_dim"] == 1024


def test_config_ollama_needs_no_key():
    # ollama is local — no API key required even with all cloud keys absent.
    s = Settings(
        embedding_provider="ollama",
        chat_provider="ollama",
        mistral_api_key=None,
        gemini_api_key=None,
        openai_api_key=None,
    )
    assert s.resolved_embedding_provider == "ollama"


def test_config_openai_requires_key():
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        Settings(embedding_provider="openai", chat_provider="ollama", openai_api_key=None)


def test_split_dispatch(monkeypatch):
    """Embeddings use one provider while chat uses the other."""
    monkeypatch.setattr(providers.settings, "embedding_provider", "google")
    monkeypatch.setattr(providers.settings, "chat_provider", "mistral")
    monkeypatch.setattr(providers.settings, "embedding_model", None)
    monkeypatch.setattr(providers.settings, "chat_model", None)

    sig = providers.embedding_signature()
    assert sig["embedding_provider"] == "google"
    assert sig["embedding_model"] == "models/gemini-embedding-001"

    _reset_chat_cache()
    mock_client = MagicMock()
    mock_client.chat.complete.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="ok"))]
    )
    providers._chat_client = mock_client
    providers._chat_client_provider = "mistral"
    assert providers.chat_complete("q") == "ok"
    assert mock_client.chat.complete.call_args.kwargs["model"] == "mistral-small-latest"
    _reset_chat_cache()
