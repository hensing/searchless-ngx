import pytest
from unittest.mock import MagicMock
from semantic.vector_store import GeminiEmbeddingFunction

def test_gemini_embedding_function_batching():
    """
    Test that GeminiEmbeddingFunction correctly batches requests when input exceeds 100.
    This test uses mocks and does not require internet access or real API keys.
    """
    api_key = "test_key"
    model_name = "models/gemini-embedding-001"

    # Create a mock client
    mock_client = MagicMock()

    # Instantiate the function
    embedding_fn = GeminiEmbeddingFunction(api_key=api_key, model_name=model_name)
    # Manually inject the mock client to avoid real API calls
    embedding_fn.client = mock_client

    # Prepare mock responses for the batches
    def mock_embed_content(model, contents):
        mock_result = MagicMock()
        # Return a number of embeddings equal to the length of the input batch
        mock_result.embeddings = [MagicMock(values=[0.1, 0.2, 0.3] * 256) for _ in contents]
        return mock_result

    mock_client.models.embed_content.side_effect = mock_embed_content

    # Case 1: Exactly 100 chunks (should be 1 call)
    input_100 = ["text"] * 100
    results_100 = embedding_fn(input_100)
    assert len(results_100) == 100
    assert mock_client.models.embed_content.call_count == 1

    mock_client.models.embed_content.reset_mock()

    # Case 2: 250 chunks (should be 3 calls: 100, 100, 50)
    input_250 = ["text"] * 250
    results_250 = embedding_fn(input_250)
    assert len(results_250) == 250
    assert mock_client.models.embed_content.call_count == 3

    # Verify the calls were made with the correct batch sizes
    calls = mock_client.models.embed_content.call_args_list
    assert len(calls[0].kwargs['contents']) == 100
    assert len(calls[1].kwargs['contents']) == 100
    assert len(calls[2].kwargs['contents']) == 50

    mock_client.models.embed_content.reset_mock()

    # Case 3: 5 chunks (should be 1 call)
    input_5 = ["text"] * 5
    results_5 = embedding_fn(input_5)
    assert len(results_5) == 5
    assert mock_client.models.embed_content.call_count == 1
