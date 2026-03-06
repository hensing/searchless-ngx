import re
from datetime import datetime
from typing import List, Dict, Any
from loguru import logger
from api.paperless_client import PaperlessAPIClient
from semantic.vector_store import vector_store
from semantic.metadata_cache import metadata_cache

class SyncJob:
    def __init__(self, client: PaperlessAPIClient):
        self.client = client
        self.chunk_size = 1000  # Approximating tokens via characters
        self.chunk_overlap = 200

    def _chunk_text(self, text: str) -> List[str]:
        """Simple character-based overlap chunking."""
        if not text:
            return []

        # Clean text slightly (remove excessive whitespace)
        text = re.sub(r'\s+', ' ', text).strip()

        chunks = []
        start = 0
        text_length = len(text)

        while start < text_length:
            end = min(start + self.chunk_size, text_length)
            chunks.append(text[start:end])
            if end >= text_length:
                break
            start += (self.chunk_size - self.chunk_overlap)

        return chunks

    async def _get_document_metadata_map(self) -> Dict[int, Any]:
        """
        Helper to fetch and map correspondents, tags, etc.
        In a production system you'd cache this to prevent repetitive API calls.
        """
        # We assume the document details contain correspondent ID and tag IDs.
        return {}

    def _date_to_timestamp(self, date_str: str) -> int:
        """Converts an ISO date string to a Unix timestamp (integer)."""
        if not date_str:
            return 0
        try:
            # Paperless-ngx usually provides ISO format: 2024-02-15T12:00:00Z or 2024-02-15
            # We take only the date part for simplicity if it's long, or use fromisoformat
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return int(dt.timestamp())
        except (ValueError, TypeError):
            try:
                # Fallback for simple YYYY-MM-DD
                dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
                return int(dt.timestamp())
            except (ValueError, TypeError):
                return 0

    def _format_custom_field_value(self, data_type: str, value: Any) -> Any:
        """Safely casts custom field values into ChromaDB compatible types (str, int, float, bool)."""
        if value is None:
            return ""

        if data_type == "boolean":
            return bool(value)
        elif data_type == "integer":
            try:
                return int(value)
            except (ValueError, TypeError):
                return 0
        elif data_type in ["float", "monetary"]:
            try:
                return float(value)
            except (ValueError, TypeError):
                return 0.0
        elif data_type == "date":
            # Store date custom fields as timestamps too for filtering
            return self._date_to_timestamp(str(value))
        else:
            # For string, url, documentlink, etc.
            return str(value)

    async def sync_document(self, document_id: int, force: bool = False):
        """
        Syncs a single document (content + notes) into the VectorStore.
        If `force` is False, it skips syncing if the `modified` timestamp matches existing chunks.
        """
        logger.info(f"Starting sync for document ID: {document_id}")

        try:
            # Refresh metadata cache if needed
            await metadata_cache.refresh_if_needed(self.client)

            # 1. Fetch document metadata and content
            doc = await self.client.get_document(document_id)
            content = doc.get("content", "")
            modified_date = doc.get("modified", "")

            # --- Lifecycle Skip Check ---
            if not force:
                existing = vector_store.search(
                    query="dummy", # Query text is required but irrelevant here due to filter
                    n_results=1,
                    where_filter={"document_id": document_id}
                )
                metas = existing.get("metadatas", [[]])[0]
                if metas and metas[0].get("modified") == modified_date:
                    logger.info(f"Document {document_id} is unmodified. Skipping sync.")
                    return

            if not content:
                logger.warning(f"Document {document_id} has no parsed content. Skipping content chunking.")

            # 2. Fetch notes
            notes = await self.client.get_document_notes(document_id)
            notes_content = " ".join([n.get("note", "") for n in notes if n.get("note")])

            # Combine content and notes
            full_text = content
            if notes_content:
                full_text += f"\n\n[NOTES]\n{notes_content}"

            if not full_text.strip():
                logger.warning(f"Document {document_id} is completely empty (no content, no notes).")
                return

            # 3. Chunking
            chunks = self._chunk_text(full_text)

            # 4. Prepare Metadata (Human readable strings)
            # Resolve tags to hierarchical paths
            resolved_tags = [metadata_cache.get_tag_path(tid) for tid in doc.get("tags", [])]
            tags_str = ", ".join(resolved_tags)

            # Resolve type and correspondent
            doc_type_id = doc.get("document_type")
            doc_type_str = metadata_cache.get_document_type_name(doc_type_id) if doc_type_id else "Unknown"

            corr_id = doc.get("correspondent")
            corr_str = metadata_cache.get_correspondent_name(corr_id) if corr_id else "Unknown"

            created = doc.get("created", "")
            added_date = doc.get("added", "")

            # Resolve Custom Fields
            custom_fields = doc.get("custom_fields", [])
            cf_metadata = {}
            for field in custom_fields:
                cf_id = field.get("field")
                cf_val = field.get("value")
                cf_name, cf_type = metadata_cache.get_custom_field_info(cf_id)

                # ChromaDB requires primitive types. Prefix with cf_ to avoid collisions
                key = f"cf_{cf_name.replace(' ', '_').lower()}"
                cf_metadata[key] = self._format_custom_field_value(cf_type, cf_val)

            metadatas = []
            chunk_ids = []

            base_meta = {
                "document_id": document_id,
                "title": doc.get("title", ""),
                "tags": tags_str,
                "document_type": doc_type_str,
                "correspondent": corr_str,
                "correspondent_id": corr_id if corr_id else 0,
                # Store both string for display and integer for filtering
                "created": self._date_to_timestamp(created),
                "created_str": created,
                "added": self._date_to_timestamp(added_date),
                "added_str": added_date,
                "modified": modified_date
            }
            # Merge custom fields into base metadata
            base_meta.update(cf_metadata)

            for i, chunk in enumerate(chunks):
                chunk_id = f"doc_{document_id}_chunk_{i}"
                chunk_ids.append(chunk_id)
                metadatas.append(base_meta)

            # 5. Update VectorStore
            # First delete old chunks (Smart Housekeeping)
            vector_store.delete_document(document_id)

            # Upsert new chunks
            vector_store.add_chunks(
                document_id=document_id,
                chunks=chunks,
                chunk_ids=chunk_ids,
                metadatas=metadatas
            )
            logger.info(f"Successfully synced document ID: {document_id}")

        except Exception as e:
            logger.error(f"Failed to sync document ID {document_id}: {e}")

    async def delete_document(self, document_id: int):
        """Removes orphan vector chunks for a deleted document."""
        logger.info(f"Deleting vector chunks for orphaned document ID: {document_id}")
        vector_store.delete_document(document_id)
