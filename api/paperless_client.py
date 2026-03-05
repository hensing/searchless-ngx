import httpx
from typing import Dict, Any, List, Optional
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from loguru import logger
from core.config import settings

class PaperlessClientError(Exception):
    """Base exception for Paperless API errors."""
    pass

class PaperlessAPIClient:
    def __init__(self):
        self.base_url = settings.paperless_url.rstrip('/')
        self.headers = {
            "Authorization": f"Token {settings.paperless_token}",
            # Request API v9 to ensure compatibility with custom fields and new metadata
            "Accept": "application/json; version=9"
        }
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self.headers,
            timeout=30.0
        )

    async def close(self):
        await self.client.aclose()

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.RequestError, httpx.HTTPStatusError)),
        reraise=True,
        before_sleep=lambda retry_state: logger.warning(
            f"Retrying Paperless API call: attempt {retry_state.attempt_number} after error: {retry_state.outcome.exception()}"
        )
    )
    async def _get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Perform a robust GET request to the Paperless API."""
        url = f"/api/{endpoint.lstrip('/')}"
        logger.debug(f"GET {url} with params {params}")

        response = await self.client.get(url, params=params)
        response.raise_for_status()
        return response.json()

    # --- Read-Only Endpoints ---

    async def get_documents(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Fetch documents. Use params for filtering (e.g., tags, query).
        """
        return await self._get("documents/", params=params)

    async def get_document(self, document_id: int) -> Dict[str, Any]:
        """Fetch a specific document by its ID."""
        return await self._get(f"documents/{document_id}/")

    async def get_document_notes(self, document_id: int) -> List[Dict[str, Any]]:
        """Fetch notes for a specific document."""
        response = await self._get(f"documents/{document_id}/notes/")
        # Paperless returns a list of notes directly for this endpoint
        return response if isinstance(response, list) else response.get("results", [])

    async def get_tags(self) -> Dict[str, Any]:
        """Fetch all tags."""
        return await self._get("tags/")

    async def get_correspondents(self) -> Dict[str, Any]:
        """Fetch all correspondents."""
        return await self._get("correspondents/")

    async def get_document_types(self) -> Dict[str, Any]:
        """Fetch all document types."""
        return await self._get("document_types/")

    async def get_custom_fields(self) -> Dict[str, Any]:
        """Fetch all custom fields."""
        return await self._get("custom_fields/")

# Initialize a global instance if needed, or instantiate per request
# depending on FastAPI lifecycle hooks.
