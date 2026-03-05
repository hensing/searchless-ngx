import chromadb
from google import genai
from chromadb.api.models.Collection import Collection
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from core.config import settings
from loguru import logger
from typing import List, Dict, Any, Optional

class GeminiEmbeddingFunction(EmbeddingFunction):
    def __init__(self, api_key: str, model_name: str):
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name

    def __call__(self, input: Documents) -> Embeddings:
        # Use the new google-genai SDK
        result = self.client.models.embed_content(
            model=self.model_name,
            contents=input
        )
        # Extract embeddings and return as list of lists
        return [e.values for e in result.embeddings]

class VectorStore:
    def __init__(self):
        self.client = None
        self.collection_name = "paperless_documents"
        self.collection: Optional[Collection] = None

    def _ensure_initialized(self):
        """Lazy initialization of ChromaDB client to allow safe import during tests."""
        if self.client is not None and self.collection is not None:
            return

        # Initialize the ChromaDB client pointing to the remote/Docker service
        self.client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)

        # Configure Google GenAI embedding function using the new SDK
        self.embedding_function = GeminiEmbeddingFunction(
            api_key=settings.gemini_api_key,
            model_name="models/gemini-embedding-001"
        )

        # Get or create the main document collection
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            embedding_function=self.embedding_function,
            metadata={"description": "Paperless-ngx parsed documents and notes"}
        )
        logger.info(f"Initialized VectorStore. Collection: {self.collection_name} loaded.")

    from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

    @retry(
        stop=stop_after_attempt(7),
        wait=wait_exponential(multiplier=2, min=4, max=60),
        reraise=True,
        before_sleep=lambda retry_state: logger.warning(
            f"Rate limited by Embedding API. Retrying in {retry_state.next_action.sleep}s... (Attempt {retry_state.attempt_number})"
        )
    )
    def add_chunks(
        self,
        document_id: int,
        chunks: List[str],
        chunk_ids: List[str],
        metadatas: List[Dict[str, Any]]
    ):
        """
        Add text chunks for a specific document to ChromaDB.
        Wrapped with Tenacity retry logic to handle Google GenAI API rate limits.
        """
        self._ensure_initialized()
        try:
            self.collection.upsert(
                documents=chunks,
                ids=chunk_ids,
                metadatas=metadatas
            )
            logger.info(f"Successfully upserted {len(chunks)} chunks for document {document_id}.")
        except Exception as e:
            logger.error(f"Failed to upsert chunks for document {document_id}: {e}")
            raise

    def delete_document(self, document_id: int):
        """
        Delete all chunks associated with a specific document_id.
        """
        self._ensure_initialized()
        try:
            # Check if document exists first to provide better logging
            existing = self.collection.get(
                where={"document_id": document_id},
                limit=1
            )
            if existing and existing.get("ids"):
                self.collection.delete(
                    where={"document_id": document_id}
                )
                logger.info(f"Existing chunks found and deleted for document {document_id}.")
            else:
                logger.debug(f"No existing chunks to delete for document {document_id}.")
        except Exception as e:
            logger.error(f"Failed to delete chunks for document {document_id}: {e}")

    def search(
        self,
        query: str,
        n_results: int = 5,
        where_filter: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Perform a semantic search, optionally using metadata filters.
        """
        self._ensure_initialized()
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=n_results,
                where=where_filter,
                include=["documents", "metadatas", "distances"]
            )
            return results
        except Exception as e:
            logger.error(f"Semantic search failed for query '{query}': {e}")
            return {"documents": [], "metadatas": [], "distances": []}

vector_store = VectorStore()
