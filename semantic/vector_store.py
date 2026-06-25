import chromadb
from chromadb.api.models.Collection import Collection
from core.config import settings
from core import providers
# Re-exported for backward compatibility (tests import it from here).
from core.providers import GeminiEmbeddingFunction
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential
from typing import List, Dict, Any, Optional

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

        # Embedding function for the configured provider (mistral default, google fallback).
        self.embedding_function = providers.get_embedding_function()
        signature = providers.embedding_signature()

        # Get or create the main document collection. The signature is stamped on
        # creation; on an existing collection ChromaDB returns the stored metadata.
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            embedding_function=self.embedding_function,
            metadata={"description": "Paperless-ngx parsed documents and notes", **signature}
        )
        self._verify_embedding_signature(signature)
        logger.info(f"Initialized VectorStore. Collection: {self.collection_name} loaded.")

    def _verify_embedding_signature(self, current: Dict[str, Any]):
        """Refuse to operate on a collection built with a different embedding provider/model.

        Switching providers changes the vector space (and usually the dimension), so the
        existing vectors are unusable. We fail loudly with a clear remediation instead of
        letting ChromaDB throw an opaque dimension-mismatch error on the first upsert.
        """
        stored = self.collection.metadata or {}
        stored_provider = stored.get("embedding_provider")
        stored_model = stored.get("embedding_model")
        if stored_provider is None and stored_model is None:
            # Legacy collection created before signatures existed — can't verify.
            logger.warning(
                "Vector collection predates embedding-provider stamping. If you have "
                "switched providers, wipe the 'chroma_data' volume and run a full re-sync."
            )
            return
        if (stored_provider, stored_model) != (current["embedding_provider"], current["embedding_model"]):
            raise RuntimeError(
                f"Embedding provider/model mismatch: collection holds "
                f"'{stored_provider}/{stored_model}' but configured provider is "
                f"'{current['embedding_provider']}/{current['embedding_model']}'. "
                f"Embeddings from different models are not comparable. Wipe the "
                f"'chroma_data' volume and run a full re-sync (POST /sync/all?force=true)."
            )

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
            logger.debug(f"Successfully upserted {len(chunks)} chunks for document {document_id}.")
        except Exception as e:
            logger.error(f"Failed to upsert chunks for document {document_id}: {e}")
            raise

    def delete_document(self, document_id: int):
        """
        Delete all chunks associated with a specific document_id.
        """
        self._ensure_initialized()
        try:
            existing = self.collection.get(
                where={"document_id": document_id},
                limit=1
            )
            if existing and existing.get("ids"):
                self.collection.delete(
                    where={"document_id": document_id}
                )
                logger.debug(f"Deleted chunks for document {document_id}.")
            else:
                logger.debug(f"No chunks to delete for document {document_id}.")
        except Exception as e:
            logger.error(f"Failed to delete chunks for document {document_id}: {e}")

    def scan_chroma_state(self) -> Dict[str, Any]:
        """
        Single ChromaDB pass (no embeddings) — returns everything sync needs.

        Returns:
          chroma_ids:       set of all doc_ids currently in ChromaDB
          latest_added_str: ISO added string of the newest doc, or None if empty
          incomplete_ids:   set of doc_ids missing chunk_0 (interrupted sync)
          doc_modified:     {doc_id: modified_str} for full-delta comparisons
        """
        self._ensure_initialized()
        try:
            result = self.collection.get(include=["metadatas"])
            chunk_ids: List[str] = result.get("ids", [])
            metas: List[Dict] = result.get("metadatas", [])

            chroma_ids: set = set()
            doc_modified: Dict[int, str] = {}
            chunk_zero_seen: set = set()
            best_ts: float = -1.0
            latest_added_str: Optional[str] = None

            for chunk_id, meta in zip(chunk_ids, metas):
                doc_id = meta.get("document_id")
                if doc_id is None:
                    continue
                chroma_ids.add(doc_id)
                if doc_id not in doc_modified:
                    doc_modified[doc_id] = meta.get("modified", "")
                    ts = meta.get("added", 0)
                    if isinstance(ts, (int, float)) and ts > best_ts:
                        best_ts = ts
                        latest_added_str = meta.get("added_str") or None
                if chunk_id == f"doc_{doc_id}_chunk_0":
                    chunk_zero_seen.add(doc_id)

            incomplete_ids = chroma_ids - chunk_zero_seen

            logger.info(
                f"ChromaDB: {len(chroma_ids)} docs, "
                f"latest added: {latest_added_str or 'none'}, "
                f"{len(incomplete_ids)} incomplete."
            )
            return {
                "chroma_ids": chroma_ids,
                "latest_added_str": latest_added_str,
                "incomplete_ids": incomplete_ids,
                "doc_modified": doc_modified,
            }
        except Exception as e:
            logger.error(f"scan_chroma_state failed: {e}")
            return {"chroma_ids": set(), "latest_added_str": None, "incomplete_ids": set(), "doc_modified": {}}

    def get_document_metadata(self, document_id: int) -> Optional[Dict[str, Any]]:
        """
        Return stored metadata for the first chunk of a document, or None if not found.
        Uses collection.get() — no embeddings required, safe during Gemini outages.
        """
        self._ensure_initialized()
        try:
            result = self.collection.get(
                where={"document_id": document_id},
                limit=1,
                include=["metadatas"]
            )
            metas = result.get("metadatas", [])
            return metas[0] if metas else None
        except Exception as e:
            logger.error(f"get_document_metadata failed for document {document_id}: {e}")
            return None

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
