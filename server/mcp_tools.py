import asyncio
import json
from loguru import logger
import re
from datetime import datetime
from typing import Dict, Any, List, Optional
from pydantic import Field
from mcp.server.fastmcp import FastMCP
from google import genai
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

def _get_today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


async def _llm_fuzzy_match(filter_term: str, candidates: List[str]) -> List[str]:
    """
    Use Gemini Flash to fuzzy-match a filter term against a list of candidate names.
    Handles typos, abbreviations, and semantic similarity (e.g. 'DB' → 'Deutsche Bahn').
    Returns the subset of candidates that match. Falls back to empty list on error.
    """
    if not candidates:
        return []

    names_block = "\n".join(candidates)
    prompt = (
        f"From the following list of names, return ONLY the names that are related to "
        f"or could be referred to as \"{filter_term}\".\n"
        f"Consider: typos, abbreviations, alternate spellings, partial names, "
        f"and semantic similarity (e.g. 'DB' matches 'Deutsche Bahn').\n"
        f"Return each matching name on its own line, exactly as written in the list.\n"
        f"If nothing matches, return exactly: NONE\n\n"
        f"List:\n{names_block}"
    )

    def _call() -> str:
        llm = genai.Client(api_key=settings.gemini_api_key)
        resp = llm.models.generate_content(
            model="gemini-flash-latest",
            contents=prompt
        )
        return resp.text.strip()

    try:
        result = await asyncio.to_thread(_call)
        if not result or result.upper() == "NONE":
            return []
        matched = [
            line.strip() for line in result.splitlines()
            if line.strip() and line.strip().upper() != "NONE"
        ]
        # Only return names that actually exist in candidates (guard against hallucination)
        candidate_set = set(candidates)
        return [m for m in matched if m in candidate_set]
    except Exception as e:
        logger.warning(f"LLM fuzzy match failed: {e}")
        return []

@mcp.tool()
async def get_current_date() -> str:
    """
    Returns today's date. Use this for precise date math (specific months, quarters, custom ranges).
    For common relative expressions like 'last year' or 'this year', you can instead pass
    time_range="last year" directly to get_paperless_master_data — no separate call needed.
    """
    today = datetime.now()
    return f"Today: {today.strftime('%Y-%m-%d')} ({today.strftime('%A, %B %d, %Y')})"

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
    The tool output always includes TODAY'S DATE so you can correctly resolve relative time expressions.

    IMPORTANT RULES:
    - USE THIS TOOL when you know the EXACT Correspondent, Tag, or Document Type ID.
    - To list the LATEST documents, leave the 'query' parameter empty.
    - If the snippet or Custom Fields do NOT contain the needed detail, call `get_document_details`
      on those Document IDs to read the full OCR text. Do not give up early.
    - Date parameters must be YYYY-MM-DD.
    - Always call `get_paperless_master_data` first to resolve names to integer IDs.
    - Do NOT pass string names to `correspondent`, `tags`, or `document_type` — only integer IDs.

    QUERY SYNTAX (CRITICAL):
    - The Paperless full-text search uses AND logic: every word must appear in the document.
    - NEVER pass multiple synonyms as one query ("fuel gas diesel" only matches docs containing ALL three).
    - Use ONE precise keyword per call. For OR logic across terms, call this tool multiple times.
    - Prefer `correspondent` or `tags` filters over a text `query` whenever possible.

    FALLBACK STRATEGY:
    - If no documents found: retry with broader filters (e.g. remove date range).
    - If still nothing: report which filters were applied and switch to `semantic_search_with_filters`.
    - Never stay silent. Never ask the user for clarification before exhausting both search methods.
    """
    params = {"ordering": "-created", "page_size": min(page_size, 50)}

    applied_filters = []
    if query:
        params["query"] = query
        applied_filters.append(f"query='{query}'")
    if tags:
        params["tags__id__in"] = tags
        applied_filters.append(f"tags={tags}")
    if correspondent and correspondent > 0:
        params["correspondent__id"] = correspondent
        applied_filters.append(f"correspondent_id={correspondent}")
    if document_type and document_type > 0:
        params["document_type__id"] = document_type
        applied_filters.append(f"document_type_id={document_type}")
    if created_after:
        params["created__date__gte"] = created_after
        applied_filters.append(f"created_after='{created_after}'")
    if created_before:
        params["created__date__lte"] = created_before
        applied_filters.append(f"created_before='{created_before}'")

    try:
        await metadata_cache.refresh_if_needed(client)
        response = await client.get_documents(params=params)
        results = response.get("results", [])

        # Build search method label with resolved names for transparent reporting
        method_parts = []
        if correspondent and correspondent > 0:
            corr_label = metadata_cache.get_correspondent_name(correspondent)
            method_parts.append(f"correspondent — {corr_label}")
        if tags:
            tag_names_resolved = [
                metadata_cache.get_tag_path(int(tid.strip()))
                for tid in tags.split(",") if tid.strip().isdigit()
            ]
            method_parts.append(f"tags — {', '.join(tag_names_resolved)}")
        if document_type and document_type > 0:
            dtype_label = metadata_cache.get_document_type_name(document_type)
            method_parts.append(f"document type — {dtype_label}")
        if query:
            method_parts.append(f'keyword "{query}"')
        search_method = " + ".join(method_parts) if method_parts else "unfiltered listing"

        if not results:
            filters_str = ", ".join(applied_filters) if applied_filters else "None"
            return (
                f"> **Search method:** metadata — {search_method}\n"
                f"> **Today:** {_get_today_str()}\n\n"
                f"No documents found. Filters applied: {filters_str}.\n"
                "Retry with broader criteria (e.g. remove date range) or switch to `semantic_search_with_filters`."
            )

        output = [
            f"> **Search method:** metadata — {search_method}",
            f"> **Today:** {_get_today_str()} | **Results:** {len(results)}",
        ]
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

            # Preserve structure but limit to 10 lines
            lines = clean_text.split("\n")
            if len(lines) > 10:
                snippet = "\n".join(lines[:10]) + "..."
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
    n_results: int = Field(default=10, description="Number of results to return (default 10, max 25)."),
    time_range: str = Field(default="", description="Natural language time period: 'last year', 'this year', 'last month', 'this month', 'last quarter', or '2024'. Use this instead of created_after/before for common expressions."),
    document_id: int = Field(default=0, description="Specific document ID to search within"),
    created_after: str = Field(default="", description="Created after date (YYYY-MM-DD). Use time_range for common expressions."),
    created_before: str = Field(default="", description="Created before date (YYYY-MM-DD). Use time_range for common expressions."),
    added_after: str = Field(default="", description="Added to paperless after date (YYYY-MM-DD)"),
    added_before: str = Field(default="", description="Added to paperless before date (YYYY-MM-DD)")
) -> str:
    """
    Semantic/vector search over document contents. Finds documents by meaning, not exact keywords.

    - USE THIS TOOL for conceptual questions without a named entity (no correspondent/tag to look up).
    - For named entities (Amazon, DB, Vodafone) or categories (mobility, insurance), prefer
      get_paperless_master_data(filter=..., time_range=...) — it returns more complete results.
    - Finds meaning via vector similarity — synonyms work naturally.
    - Results include Custom Fields. If they contain the needed detail, skip `get_document_details`.
    - Pass time_range="last year" directly — no prior get_current_date call needed.
    - For queries requiring complete coverage (tax, contracts), increase n_results to 20+.

    QUERY FORMULATION:
    - Write a natural language sentence describing what you are looking for, NOT a keyword list.
    - GOOD: "fuel receipt at a gas station"
    - BAD:  "fuel gas diesel receipt station"
    - GOOD: "mobile phone bill or telephone invoice"
    - BAD:  "phone mobile cellular bill invoice"
    - One focused concept per query. Run separate queries for unrelated categories.

    TAGS AND CUSTOM FIELDS:
    - If you already have tag IDs (from get_paperless_master_data), prefer
      search_paperless_metadata(tags="id1,id2") over semantic search — it is faster and exact.
    - Example: documents tagged "urgent" → search_paperless_metadata(tags="45")
    - Custom field values are returned in result cards (e.g. "Betrag: 49.90").
      If the amount or field value you need is visible there, skip get_document_details.
    - Custom fields example: "invoices with a total amount field" →
      semantic_search_with_filters(query="invoice with total amount in euros")

    FALLBACK STRATEGY:
    - If no results: retry without date filters. If still nothing, report filters applied.
    - Never stay silent. Never ask the user for clarification before exhausting all search options.
    """
    try:
        # Resolve time_range to explicit dates if not already provided
        if time_range and not (created_after or created_before):
            created_after, created_before = _resolve_time_range(time_range)

        where_filter = {}
        conditions = []
        applied_filters = [f"query='{query}'"]

        if document_id and document_id > 0:
            conditions.append({"document_id": document_id})
            applied_filters.append(f"document_id={document_id}")

        if created_after and isinstance(created_after, str) and not hasattr(created_after, "default"):
            ts = _date_to_timestamp(created_after)
            if ts:
                conditions.append({"created": {"$gte": ts}})
                applied_filters.append(f"created_after='{created_after}'")
        if created_before and isinstance(created_before, str) and not hasattr(created_before, "default"):
            ts = _date_to_timestamp(created_before)
            if ts:
                conditions.append({"created": {"$lte": ts}})
                applied_filters.append(f"created_before='{created_before}'")

        if added_after and isinstance(added_after, str) and not hasattr(added_after, "default"):
            ts = _date_to_timestamp(added_after)
            if ts:
                conditions.append({"added": {"$gte": ts}})
                applied_filters.append(f"added_after='{added_after}'")
        if added_before and isinstance(added_before, str) and not hasattr(added_before, "default"):
            ts = _date_to_timestamp(added_before)
            if ts:
                conditions.append({"added": {"$lte": ts}})
                applied_filters.append(f"added_before='{added_before}'")

        if len(conditions) == 1:
            where_filter = conditions[0]
        elif len(conditions) > 1:
            where_filter = {"$and": conditions}

        results = vector_store.search(
            query=query,
            n_results=min(n_results, 25),
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
            filters_str = ", ".join(applied_filters)
            return (
                f"> **Search method:** vector/semantic\n"
                f"> **Today:** {_get_today_str()}\n\n"
                f"No relevant documents found. Filters applied: {filters_str}.\n"
                "Retry without date filters, or broaden the query concept."
            )

        output = [
            f"> **Search method:** vector/semantic",
            f"> **Today:** {_get_today_str()} | **Results:** {len(docs)}",
        ]
        base_url = settings.public_url.rstrip('/')

        for doc, meta, dist in zip(docs, metas, distances):
            doc_id = meta.get("document_id", "Unknown")
            title = meta.get("title", "Unknown")
            corr_id = meta.get("correspondent_id")
            corr_name = meta.get("correspondent", "Unknown")
            created_str = meta.get("created_str") or meta.get("created", "Unknown")

            # 1. Cleaner Chunk with preserved structure (limit to 10 lines)
            clean_text = re.sub(r'[ \t]+', ' ', doc)
            clean_text = re.sub(r'\n\s*\n\s*\n+', '\n\n', clean_text).strip()

            lines = clean_text.split("\n")
            if len(lines) > 10:
                snippet = "\n".join(lines[:10]) + "..."
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

            # Custom Fields from ChromaDB metadata (cf_* keys)
            cf_parts = []
            for key, val in meta.items():
                if key.startswith("cf_") and val not in ("", 0, 0.0, None):
                    field_name = key[3:].replace("_", " ").title()
                    cf_parts.append(f"`{field_name}`: {val}")
            if cf_parts:
                output.append(f"**Custom Fields:** {', '.join(cf_parts)}")

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
    Call this when snippets or Custom Fields do not contain the needed detail
    (invoice total, contract clause, tax ID in recipient section, cancellation date, etc.).
    Calling this tool multiple times for different document IDs is expected and correct.
    """
    try:
        doc = await client.get_document(document_id)
        notes = await client.get_document_notes(document_id)

        corr_id = doc.get("correspondent")
        corr_name = metadata_cache.get_correspondent_name(corr_id) if corr_id else "None"
        doc_type_id = doc.get("document_type")
        doc_type_name = metadata_cache.get_document_type_name(doc_type_id) if doc_type_id else "None"
        tag_ids = doc.get("tags", [])
        tag_names = [metadata_cache.get_tag_path(tid) for tid in tag_ids]
        base_url = settings.public_url.rstrip('/')
        source_url = f"{base_url}/documents/{doc.get('id')}/details"

        output = [
            f"### 📄 [{doc.get('title')}]({source_url})",
            f"**Correspondent:** {corr_name} | **Type:** {doc_type_name} | "
            f"**Created:** {doc.get('created')}",
        ]
        if tag_names:
            output.append(f"**Tags:** {', '.join(f'`{t}`' for t in tag_names)}")

        custom_fields = doc.get("custom_fields", [])
        if custom_fields:
            output.append("\n#### Custom Fields")
            for cf in custom_fields:
                field_name = metadata_cache.get_custom_field_name(cf.get("field"))
                output.append(f"- **{field_name}:** {cf.get('value')}")

        output.append("\n#### OCR Content")
        output.append("```")
        output.append(doc.get("content", "No parsed content available."))
        output.append("```")

        if notes:
            output.append("\n#### User Notes")
            for n in notes:
                output.append(f"- *{n.get('created')}* — {n.get('note')}")

        return "\n".join(output)
    except Exception as e:
        logger.error(f"Error in get_document_details for ID {document_id}: {e}")
        return f"Error fetching document details: {str(e)}"

def _resolve_time_range(time_range: str) -> tuple[str, str]:
    """
    Convert a natural language time range to (created_after, created_before) date strings.
    Returns ("", "") if the expression is not recognized.
    """
    from calendar import monthrange
    today = datetime.now()
    tr = time_range.strip().lower()

    if not tr:
        return "", ""

    # Explicit year: "2024", "2023", etc.
    import re as _re
    year_match = _re.fullmatch(r"(20\d{2})", tr)
    if year_match:
        y = year_match.group(1)
        return f"{y}-01-01", f"{y}-12-31"

    if "last year" in tr or "letztes jahr" in tr or "vorjahr" in tr:
        y = today.year - 1
        return f"{y}-01-01", f"{y}-12-31"

    if "this year" in tr or "dieses jahr" in tr or "aktuelles jahr" in tr:
        return f"{today.year}-01-01", today.strftime("%Y-%m-%d")

    if "last month" in tr or "letzten monat" in tr or "letzter monat" in tr:
        if today.month == 1:
            lm_year, lm_month = today.year - 1, 12
        else:
            lm_year, lm_month = today.year, today.month - 1
        last_day = monthrange(lm_year, lm_month)[1]
        return f"{lm_year}-{lm_month:02d}-01", f"{lm_year}-{lm_month:02d}-{last_day}"

    if "this month" in tr or "diesen monat" in tr or "aktueller monat" in tr:
        return f"{today.year}-{today.month:02d}-01", today.strftime("%Y-%m-%d")

    if "last quarter" in tr or "letztes quartal" in tr:
        q = (today.month - 1) // 3  # current quarter index (0-based)
        if q == 0:
            q_year, q_start = today.year - 1, 10
        else:
            q_year, q_start = today.year, (q - 1) * 3 + 1
        q_end_month = q_start + 2
        q_end_day = monthrange(q_year, q_end_month)[1]
        return f"{q_year}-{q_start:02d}-01", f"{q_year}-{q_end_month:02d}-{q_end_day}"

    return "", ""


@mcp.tool()
async def get_paperless_master_data(
    filter: str = Field(default="", description="Search term: correspondent or tag name, category, or concept (e.g. 'Amazon', 'mobility', 'insurance')."),
    time_range: str = Field(default="", description="Natural language time period: 'last year', 'this year', 'last month', 'this month', 'last quarter', or a 4-digit year like '2024'. Leave empty if you need all time."),
    created_after: str = Field(default="", description="Explicit date override (YYYY-MM-DD). Use time_range instead for common expressions."),
    created_before: str = Field(default="", description="Explicit date override (YYYY-MM-DD). Use time_range instead for common expressions."),
    page_size: int = Field(default=25, description="Max documents to return per matched correspondent/tag (max 50).")
) -> str:
    """
    Find documents by resolving a search term to matching correspondents/tags, then
    searching for actual documents. Handles typos, abbreviations, and semantic similarity
    (e.g. "DB" → "Deutsche Bahn", "armazzon" → "Amazon").

    SINGLE CALL — no prior tool call needed:
    - "How much did I spend on mobility last year?"
      → get_paperless_master_data(filter="mobility", time_range="last year")
    - "Show Amazon invoices from 2024"
      → get_paperless_master_data(filter="amazon", time_range="2024")
    - "What are my latest insurance documents?"
      → get_paperless_master_data(filter="insurance")

    WHEN TO USE:
    - For ANY question about documents from a named entity or category.
    - With time_range for date-scoped queries — no separate get_current_date needed.
    - Without time_range: returns all matching documents (no date filter) and IDs.
    - ALWAYS call with a specific filter. Without filter, only counts are returned.

    AFTER THIS CALL:
    - If amounts appear in Custom Fields in the table, you can answer directly.
    - If amounts are missing, call get_document_details for specific Doc IDs.
    - For concept searches with no named entity, use semantic_search_with_filters instead.

    REASONING RULES:
    - Recency: for current-state questions (address, IBAN) use the NEWEST document only.
    - Contract status: cancellation after contract = terminated; recent invoices = active.
    - Source awareness: on invoices, user data is in the "bill to" section.
    """
    try:
        await metadata_cache.refresh_if_needed(client)

        # Resolve time_range to explicit dates if not already provided
        if time_range and not (created_after or created_before):
            created_after, created_before = _resolve_time_range(time_range)
            if not created_after and not created_before:
                logger.warning(f"Could not parse time_range='{time_range}' — ignoring")

        filter_lower = filter.strip().lower() if filter else ""

        # No filter → counts only
        if not filter_lower:
            n_corr = len(metadata_cache.correspondents)
            n_tags = len(metadata_cache.tags)
            n_types = len(metadata_cache.document_types)
            return (
                f"Master data summary: {n_corr} correspondents, {n_tags} tags, {n_types} document types.\n"
                "Call this tool again with filter='<specific name>' to get IDs."
            )

        # Build sorted name lists for matching
        sorted_corrs  = sorted(metadata_cache.correspondents.items(), key=lambda x: x[1].lower())
        sorted_tags   = sorted(metadata_cache.tags.items(),           key=lambda x: x[1]["path"].lower())
        sorted_dtypes = sorted(metadata_cache.document_types.items(), key=lambda x: x[1].lower())

        # Pass 1: substring match
        corrs_matched  = [(cid, name) for cid, name in sorted_corrs  if filter_lower in name.lower()]
        tags_matched   = [(tid, info) for tid, info in sorted_tags   if filter_lower in info["path"].lower()]
        dtypes_matched = [(did, name) for did, name in sorted_dtypes if filter_lower in name.lower()]

        # Pass 2: LLM fuzzy match for anything not found via substring
        if not corrs_matched and not tags_matched and not dtypes_matched:
            logger.info(f"No substring match for '{filter}' — trying LLM fuzzy match")
            all_corr_names = [name for _, name in sorted_corrs]
            all_tag_names  = [info["path"] for _, info in sorted_tags]

            matched_corr_names, matched_tag_names = await asyncio.gather(
                _llm_fuzzy_match(filter, all_corr_names),
                _llm_fuzzy_match(filter, all_tag_names),
            )

            corr_name_set = set(matched_corr_names)
            tag_name_set  = set(matched_tag_names)
            corrs_matched = [(cid, name) for cid, name in sorted_corrs if name in corr_name_set]
            tags_matched  = [(tid, info) for tid, info in sorted_tags  if info["path"] in tag_name_set]

        corr_ids = [str(cid) for cid, _ in corrs_matched]
        tag_ids  = [str(tid) for tid, _ in tags_matched]

        # Still nothing → semantic search fallback
        if not corrs_matched and not tags_matched and not dtypes_matched:
            return (
                f"No match for '{filter}' (substring or semantic).\n"
                f"Call semantic_search_with_filters with query=\"documents related to {filter}\" "
                "and date filters if applicable."
            )

        # --- DATE MODE: run searches in parallel and return document table ---
        if created_after or created_before:
            date_label = f"{created_after or '…'} → {created_before or '…'}"
            base_params: Dict[str, Any] = {"ordering": "-created", "page_size": min(page_size, 50)}
            if created_after:
                base_params["created__date__gte"] = created_after
            if created_before:
                base_params["created__date__lte"] = created_before

            # Build parallel search tasks
            search_tasks = []
            task_labels  = []

            for cid, cname in corrs_matched:
                p = {**base_params, "correspondent__id": cid}
                search_tasks.append(client.get_documents(params=p))
                task_labels.append(f"correspondent:{cname}")

            if tag_ids:
                p = {**base_params, "tags__id__in": ",".join(tag_ids)}
                search_tasks.append(client.get_documents(params=p))
                task_labels.append(f"tags:{','.join(tag_ids)}")

            raw_results = await asyncio.gather(*search_tasks, return_exceptions=True)

            # Deduplicate by document ID
            seen: Dict[int, Dict[str, Any]] = {}
            for result, label in zip(raw_results, task_labels):
                if isinstance(result, Exception):
                    logger.warning(f"Search failed for {label}: {result}")
                    continue
                for doc in result.get("results", []):
                    doc_id = doc.get("id")
                    if doc_id and doc_id not in seen:
                        seen[doc_id] = doc

            all_docs = sorted(seen.values(), key=lambda d: d.get("created", ""), reverse=True)

            if not all_docs:
                matched_names = ", ".join(
                    [name for _, name in corrs_matched] +
                    [info["path"] for _, info in tags_matched]
                )
                return (
                    f"> **Search method:** entity lookup — filter=\"{filter}\" | {date_label}\n\n"
                    f"No documents found for '{filter}' in this date range.\n"
                    f"Matched entities: {matched_names}\n"
                    "Try calling semantic_search_with_filters with the same date range."
                )

            base_url = settings.public_url.rstrip('/')
            output = [
                f"> **Search method:** entity lookup — filter=\"{filter}\" | {date_label}",
                f"> **Matched:** {', '.join([name for _, name in corrs_matched] + [info['path'] for _, info in tags_matched])}",
                f"> **Documents found:** {len(all_docs)} (deduplicated)",
                "",
                "| Doc ID | Title | Correspondent | Date | Custom Fields |",
                "|--------|-------|---------------|------|---------------|",
            ]

            for doc in all_docs:
                doc_id   = doc.get("id", "")
                title    = doc.get("title", "Unknown")
                corr_id  = doc.get("correspondent")
                corr_name = metadata_cache.get_correspondent_name(corr_id) if corr_id else "—"
                created  = (doc.get("created") or "")[:10]

                # Custom fields — compact key:value pairs
                cfs = doc.get("custom_fields", [])
                cf_str = ""
                if cfs:
                    parts = []
                    for cf in cfs:
                        cf_name = metadata_cache.get_custom_field_name(cf.get("field"))
                        val = cf.get("value")
                        if val not in (None, "", 0, 0.0):
                            parts.append(f"{cf_name}: {val}")
                    cf_str = "; ".join(parts)

                doc_url = f"{base_url}/documents/{doc_id}/details"
                title_link = f"[{title}]({doc_url})"
                output.append(f"| {doc_id} | {title_link} | {corr_name} | {created} | {cf_str} |")

            output.append("")
            output.append(
                "If the amounts or details you need are not visible in Custom Fields above, "
                "call `get_document_details` for the specific Doc IDs."
            )
            return "\n".join(output)

        # --- ID-ONLY MODE: no dates given, return IDs + NEXT ACTION ---
        output = []
        if corr_ids:
            output.append(f"**Correspondent IDs:** {', '.join(corr_ids)}")
            for cid, name in corrs_matched:
                output.append(f"  - ID {cid}: {name}")
        if tag_ids:
            output.append(f"**Tag IDs:** {','.join(tag_ids)}")
            for tid, info in tags_matched:
                output.append(f"  - ID {tid}: {info['path']}")
        if dtypes_matched:
            output.append("**Document Types:**")
            for did, name in dtypes_matched:
                output.append(f"  - ID {did}: {name}")

        next_steps = ["**NEXT ACTION (execute now):**"]
        if corr_ids:
            next_steps.append(
                f"- For each correspondent ID ({', '.join(corr_ids)}): "
                "call search_paperless_metadata(correspondent=<id>, page_size=50) with date filters."
            )
        if tag_ids:
            next_steps.append(
                f"- For tags: call search_paperless_metadata(tags=\"{','.join(tag_ids)}\", "
                "page_size=50) with date filters."
            )
        next_steps.append(
            f"- Also call semantic_search_with_filters(query=\"{filter} related documents\", "
            "n_results=20) with date filters to catch untagged documents."
        )
        next_steps.append("DO NOT STOP HERE — execute these calls now.")
        output.append("")
        output.extend(next_steps)

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
