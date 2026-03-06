import json
from loguru import logger
import re
from datetime import datetime
from typing import Dict, Any, List
from pydantic import Field
from mcp.server.fastmcp import FastMCP
from api.paperless_client import PaperlessAPIClient
from semantic.vector_store import vector_store
from semantic.metadata_cache import metadata_cache
from core.config import settings

# Create the FastMCP instance
# We disable transport security (host validation) by explicitly passing a dictionary
# configuring it to not require TLS or specific hosts, because we are running inside
# a Docker network. We also set host="0.0.0.0" so it binds properly.
import os

mcp = FastMCP(
    "paperless-mcp-server",
    stateless_http=True,
    json_response=True,
    host="0.0.0.0",
    port=8001,
    transport_security={
        "require_tls": False,
        "allowed_hosts": [
            "mcp-server",
            "mcp-server:8001",
            "localhost",
            "127.0.0.1"
        ]
    }
)

# Since FastMCP abstracts transport, we only define the tools.

# We will initialize the client when tools are called, or via dependency injection if preferred
client = PaperlessAPIClient()

@mcp.tool()
async def search_paperless_metadata(
    query: str = Field(default="", description="The search keyword. Leave empty to list the most recent documents."),
    page_size: int = Field(default=5, description="Number of results to return (max 50)."),
    tags: str = Field(default="", description="Comma separated tag IDs"),
    correspondent: int = Field(default=0, description="Correspondent ID"),
    document_type: int = Field(default=0, description="Document type ID"),
    created_after: str = Field(default="", description="Date YYYY-MM-DD"),
    created_before: str = Field(default="", description="Date YYYY-MM-DD")
) -> str:
    """
    Perform an exact keyword and metadata search in Paperless-ngx. Results are sorted NEWEST FIRST.

    IMPORTANT RULES:
    - USE THIS TOOL PRIMARILY when you know the EXACT Correspondent, Tag, or Document Type.
    - To list the LATEST documents, leave the 'query' parameter empty.
    - IF you need to calculate sums, costs, or find specific details, and the 'Custom Fields' or 'Snippet' do NOT contain the final amounts, you MUST subsequently call `get_document_details` using the found Document IDs to read the full OCR text! Do not give up.
    - If you see a 'Cancellation' (Kündigung) that is newer than a 'Contract' (Vertrag), you MUST reason that the contract is cancelled. Newer documents trump older ones.
    - Date parameters must be YYYY-MM-DD.
    - If the user asks for a specific correspondent or document type, call `get_paperless_master_data` FIRST to find integer IDs.
    - Do NOT pass string names to `correspondent`, `tags`, or `document_type`, only integer IDs.
    """
    params = {"ordering": "-created", "page_size": min(page_size, 50)}

    if query:
        params["query"] = query
    if tags:
        params["tags__id__in"] = tags
    if correspondent and correspondent > 0:
        params["correspondent__id"] = correspondent
    if document_type and document_type > 0:
        params["document_type__id"] = document_type
    if created_after:
        params["created__date__gte"] = created_after
    if created_before:
        params["created__date__lte"] = created_before

    try:
        await metadata_cache.refresh_if_needed(client)
        response = await client.get_documents(params=params)
        results = response.get("results", [])

        if not results:
            return "No documents found via metadata search."

        output = [f"Found {len(results)} exact matches via Paperless API:"]
        base_url = settings.public_url.rstrip('/')

        for r in results[:10]:
            doc_id = r.get("id")
            title = r.get("title", "Unknown")
            corr_id = r.get("correspondent")
            corr_name = metadata_cache.get_correspondent_name(corr_id) if corr_id else "Unknown"

            # 1. Cleaner Snippet with preserved structure (max 7 lines)
            raw_content = r.get("content", "")
            clean_text = re.sub(r'[ \t]+', ' ', raw_content) # Collapse spaces
            clean_text = re.sub(r'\n\s*\n\s*\n+', '\n\n', clean_text).strip() # Normalize vertical space

            # Preserve structure but limit to 7 lines
            lines = clean_text.split("\n")
            if len(lines) > 7:
                snippet = "\n".join(lines[:7]) + "..."
            else:
                snippet = clean_text

            # 2. Reformat as "Card" with links
            source_url = f"{base_url}/documents/{doc_id}/details"

            output.append("\n---")
            # Header with linked Title
            output.append(f"### 📄 [{title}]({source_url})")

            # Correspondent & Metadata line
            metadata_parts = []
            if corr_id:
                corr_url = f"{base_url}/documents?correspondent__id__in={corr_id}&sort=created&reverse=1&page=1"
                metadata_parts.append(f"**Correspondent:** [{corr_name}]({corr_url})")
            else:
                metadata_parts.append(f"**Correspondent:** Unknown")

            metadata_parts.append(f"**Created:** {r.get('created')}")
            output.append(" | ".join(metadata_parts))

            # Tags
            doc_tags = r.get("tags", [])
            if doc_tags:
                tag_links = []
                for tid in doc_tags:
                    t_path = metadata_cache.get_tag_path(tid)
                    t_url = f"{base_url}/documents?tags__id__all={tid}&sort=created&reverse=1&page=1"
                    tag_links.append(f"[`{t_path}`]({t_url})")
                output.append(f"**Tags:** {', '.join(tag_links)}")

            # Custom Fields
            cfs = r.get("custom_fields", [])
            if cfs:
                cf_strs = []
                for cf in cfs:
                    name = metadata_cache.get_custom_field_name(cf['field'])
                    cf_strs.append(f"`{name}`: {cf['value']}")
                output.append(f"**Custom Fields:** {', '.join(cf_strs)}")

            # Snippet in blockquote
            indented_snippet = "\n".join([f"> {line}" for line in snippet.split("\n")])
            output.append(f"\n{indented_snippet}")
            output.append("---")

        return "\n".join(output)
    except Exception as e:
        logger.error(f"Error in search_paperless_metadata: {e}")
        return f"Error executing exact metadata search: {str(e)}"

def _date_to_timestamp(date_str: str) -> int:
    """Converts YYYY-MM-DD to Unix timestamp for ChromaDB filtering."""
    if not date_str:
        return 0
    try:
        # Expected format YYYY-MM-DD from LLM
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        return int(dt.timestamp())
    except (ValueError, TypeError):
        return 0

@mcp.tool()
async def semantic_search_with_filters(
    query: str = Field(..., description="The conceptual search query."),
    document_id: int = Field(default=0, description="Specific document ID to search within"),
    created_after: str = Field(default="", description="Created after date (YYYY-MM-DD)"),
    created_before: str = Field(default="", description="Created before date (YYYY-MM-DD)"),
    added_after: str = Field(default="", description="Added to paperless after date (YYYY-MM-DD)"),
    added_before: str = Field(default="", description="Added to paperless before date (YYYY-MM-DD)")
) -> str:
    """
    Perform a highly powerful semantic/vector search over document contents.
    - USE THIS TOOL INSTEAD OF metadata search when the user asks conceptual questions (e.g., "What are my cancellation terms?", "receipts for food", "software subscriptions") OR when you don't have an exact correspondent/tag match.
    - This search finds meaning, not just exact keywords.
    - If the snippets returned do not contain the specific answer (e.g., a specific price or clause), use `get_document_details` on the most relevant Document IDs to read the full text.
    - You can combine the semantic `query` with strict date boundaries.
    - If the user asks for a timeframe (e.g., "in 2023"), you MUST use `created_after="2023-01-01"` and `created_before="2023-12-31"`.
    - Date formats MUST be ISO format (YYYY-MM-DD).
    """
    try:
        where_filter = {}
        conditions = []

        if document_id and document_id > 0:
            conditions.append({"document_id": document_id})

        if created_after and isinstance(created_after, str) and not hasattr(created_after, "default"):
            ts = _date_to_timestamp(created_after)
            if ts:
                conditions.append({"created": {"$gte": ts}})
        if created_before and isinstance(created_before, str) and not hasattr(created_before, "default"):
            ts = _date_to_timestamp(created_before)
            if ts:
                conditions.append({"created": {"$lte": ts}})

        if added_after and isinstance(added_after, str) and not hasattr(added_after, "default"):
            ts = _date_to_timestamp(added_after)
            if ts:
                conditions.append({"added": {"$gte": ts}})
        if added_before and isinstance(added_before, str) and not hasattr(added_before, "default"):
            ts = _date_to_timestamp(added_before)
            if ts:
                conditions.append({"added": {"$lte": ts}})

        if len(conditions) == 1:
            where_filter = conditions[0]
        elif len(conditions) > 1:
            where_filter = {"$and": conditions}

        results = vector_store.search(
            query=query,
            n_results=5,
            where_filter=where_filter if where_filter else None
        )

        # Robust result extraction
        docs_list = results.get("documents", [])
        docs = docs_list[0] if docs_list else []

        metas_list = results.get("metadatas", [])
        metas = metas_list[0] if metas_list else []

        dists_list = results.get("distances", [])
        distances = dists_list[0] if dists_list else []

        if not docs:
            return "No relevant semantic chunks found matching your criteria."

        output = ["Semantic Search Results:"]
        base_url = settings.public_url.rstrip('/')

        for doc, meta, dist in zip(docs, metas, distances):
            doc_id = meta.get("document_id", "Unknown")
            title = meta.get("title", "Unknown")
            corr_id = meta.get("correspondent_id")
            corr_name = meta.get("correspondent", "Unknown")
            created_str = meta.get("created_str") or meta.get("created", "Unknown")

            # 1. Cleaner Chunk with preserved structure (limit to 7 lines)
            clean_text = re.sub(r'[ \t]+', ' ', doc)
            clean_text = re.sub(r'\n\s*\n\s*\n+', '\n\n', clean_text).strip()

            lines = clean_text.split("\n")
            if len(lines) > 7:
                snippet = "\n".join(lines[:7]) + "..."
            else:
                snippet = clean_text

            # 2. Reformat as "Card"
            source_url = f"{base_url}/documents/{doc_id}/details"

            output.append("\n---")
            output.append(f"### 📄 [{title}]({source_url})")

            # Correspondent & Metadata line
            metadata_parts = [f"**Relevance:** {1-dist:.2%}"]
            if corr_id:
                corr_url = f"{base_url}/documents?correspondent__id__in={corr_id}&sort=created&reverse=1&page=1"
                metadata_parts.append(f"**Correspondent:** [{corr_name}]({corr_url})")
            else:
                metadata_parts.append(f"**Correspondent:** {corr_name}")

            metadata_parts.append(f"**Created:** {created_str}")
            output.append(" | ".join(metadata_parts))

            # Snippet in blockquote
            indented_snippet = "\n".join([f"> {line}" for line in snippet.split("\n")])
            output.append(f"\n{indented_snippet}")
            output.append("---")

        return "\n".join(output)
    except Exception as e:
        logger.error(f"Error in semantic_search_with_filters: {e}")
        return f"Error executing semantic search: {str(e)}"

@mcp.tool()
async def get_document_details(
    document_id: int = Field(default=0, description="The integer ID of the document to fetch.")
) -> str:
    """
    Retrieve the COMPLETE parsed text and notes of a single document by its ID.
    - CRITICAL: You MUST call this tool if the snippets from the search tools do not contain the specific information the user asked for (like total invoice amounts, specific paragraphs, or contract details).
    - It is perfectly fine to call this tool multiple times in a row for different Document IDs to extract financial data before answering the user.
    """
    try:
        doc = await client.get_document(document_id)
        notes = await client.get_document_notes(document_id)

        # Resolve metadata names
        corr_id = doc.get("correspondent")
        corr_name = metadata_cache.get_correspondent_name(corr_id) if corr_id else "None"

        doc_type_id = doc.get("document_type")
        doc_type_name = metadata_cache.get_document_type_name(doc_type_id) if doc_type_id else "None"

        tag_ids = doc.get("tags", [])
        tag_names = [metadata_cache.get_tag_path(tid) for tid in tag_ids]

        output = [
            f"=== Document ID: {doc.get('id')} ===",
            f"Title: {doc.get('title')}",
            f"Correspondent: {corr_name}",
            f"Document Type: {doc_type_name}",
            f"Created: {doc.get('created')}",
            f"Added: {doc.get('added')}",
            f"Tags: {', '.join(tag_names)}",
        ]

        # Custom Fields
        custom_fields = doc.get("custom_fields", [])
        if custom_fields:
            output.append("\n=== Custom Fields ===")
            for cf in custom_fields:
                field_id = cf.get("field")
                field_name = metadata_cache.get_custom_field_name(field_id)
                output.append(f"{field_name}: {cf.get('value')}")

        output.append("\n=== OCR Content ===")
        output.append(doc.get("content", "No parsed content available."))

        if notes:
            output.append("\n=== User Notes ===")
            for n in notes:
                output.append(f"- {n.get('created')} | User: {n.get('user')}\n  {n.get('note')}")

        return "\n".join(output)
    except Exception as e:
        logger.error(f"Error in get_document_details for ID {document_id}: {e}")
        return f"Error fetching document details: {str(e)}"

@mcp.tool()
async def get_paperless_master_data(
    mode: str = Field(..., description="Always pass the string 'all' to this parameter.")
) -> str:
    """
    Fetch the master list mapping of all Correspondents, Tags, and Document Types to their integer IDs.
    CRITICAL: Call this FIRST if the user asks for a specific sender, category, or document type (like 'Invoice' or 'Contract') to get the correct integer IDs.
    """
    try:
        await metadata_cache.refresh_if_needed(client)

        output = ["=== Correspondents ==="]
        # Sort by name for better readability
        sorted_corrs = sorted(metadata_cache.correspondents.items(), key=lambda x: x[1].lower())
        for c_id, c_name in sorted_corrs:
            output.append(f"ID: {c_id} | Name: {c_name}")

        output.append("\n=== Tags ===")
        # Use tag paths for clarity and sort by path
        sorted_tags = sorted(metadata_cache.tags.items(), key=lambda x: x[1]["path"].lower())
        for t_id, t_info in sorted_tags:
            output.append(f"ID: {t_id} | Name: {t_info['path']}")

        output.append("\n=== Document Types ===")
        sorted_dtypes = sorted(metadata_cache.document_types.items(), key=lambda x: x[1].lower())
        for dt_id, dt_name in sorted_dtypes:
            output.append(f"ID: {dt_id} | Name: {dt_name}")

        return "\n".join(output)
    except Exception as e:
        logger.error(f"Error in get_paperless_master_data: {e}")
        return f"Error fetching master data lists: {str(e)}"

@mcp.tool()
async def refresh_paperless_metadata() -> str:
    """
    Force an immediate refresh of the internal metadata cache (Correspondents, Tags, Document Types).
    Use this if you have recently added or renamed items in Paperless-ngx and they are not showing up yet.
    """
    try:
        await metadata_cache._force_refresh(client)
        return "Metadata cache successfully refreshed from Paperless-ngx API."
    except Exception as e:
        logger.error(f"Error refreshing metadata cache: {e}")
        return f"Error refreshing metadata cache: {str(e)}"
