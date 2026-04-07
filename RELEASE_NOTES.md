# Release Notes - v0.1.6 🧠

This release introduces **Intelligent Entity Resolution & Natural-Language Time Ranges**,
collapsing what previously required multiple tool calls into a single, typo-tolerant lookup.

## Key Improvements in v0.1.6

### 🧠 LLM-Powered Fuzzy Entity Matching
`get_paperless_master_data` is now a full "find and return docs" tool in one call:
- **Substring match first**: fast path for exact/partial name matches.
- **Gemini Flash fallback**: if nothing matches, an LLM resolves typos, abbreviations,
  and semantic equivalences (e.g. "DB" → "Deutsche Bahn", "armazzon" → "Amazon").
- **Parallel document search**: matched entity IDs are searched concurrently; results are
  deduplicated and returned as a markdown table with Custom Fields inline.
- **Zero extra tool calls**: combine `filter` + `time_range` in one call to get documents
  directly — no separate `get_current_date` or `search_paperless_metadata` needed.

### 🗓️ Natural-Language Time Ranges
Both `get_paperless_master_data` and `semantic_search_with_filters` now accept a
`time_range` parameter:
- Supported expressions: `"last year"`, `"this year"`, `"last month"`, `"this month"`,
  `"last quarter"`, or a 4-digit year like `"2024"`.
- German variants supported: `"letztes Jahr"`, `"diesen Monat"`, etc.
- Automatically resolved to `created_after`/`created_before` date pairs.

### 📅 New `get_current_date` Tool
Returns today's date in a structured format for use in precise date arithmetic when
`time_range` doesn't cover the expression.

### 🔍 Improved Search Guidance
- `search_paperless_metadata` now warns the LLM that Paperless uses **AND logic**: all
  words in `query` must appear in the document. Guidance: one keyword per call; use
  multiple calls for OR semantics.
- Every result block now opens with a `> **Search method:**` header so the LLM and user
  can see exactly which filters were applied.
- Snippet preview expanded from 7 to 10 lines.

### 🧪 Verified
Tested end-to-end via MCP tool calls against a live Paperless-ngx instance.

---

# Release Notes - v0.1.5 🧭

This release introduces **Search Resilience & Smart Fallback Strategies**, making the agent much more proactive when initial search results are empty.

## Key Improvements in v0.1.5

### 🧭 Smart Search Fallbacks
The search tools now include explicit "Retry Logic" for the LLM. If a narrow search (e.g., within a specific date range) yields no results, the agent is now instructed to:
- **Relax Filters**: Automatically try broader criteria, such as removing date boundaries or broadening the query.
- **Contextual Retries**: Inform the user if results are found in a different timeframe than requested.

### 💬 Descriptive Empty-Result Feedback
Search results are no longer a silent "No results". The tools now return detailed context:
- **Applied Filters**: Lists all parameters (IDs, dates, query) that were used, helping the LLM reason about its next search attempt.
- **Clear Guidance**: Provides direct recommendations to the LLM on how to broaden the search.

### 🆔 Strict Metadata ID Enforcement
To prevent the LLM from "hallucinating" or guessing correspondent/tag IDs:
- **Mandatory Lookup**: The `get_paperless_master_data` tool now explicitly warns against guessing IDs and requires using it for lookup first.

### 🧪 Verified Stability
- **Raw Protocol Checks**: This release has been verified using the raw MCP protocol checker.
- **Test Suite**: Verified by the full suite of **18 automated tests**.

---

# Release Notes - v0.1.4 🛡️

This release focuses on **Stability and Large Document Support**, ensuring that Searchless-ngx can handle even the most extensive document libraries without hitting API limits.

## Key Improvements in v0.1.4

### 📦 Smart Embedding Batching
The Gemini Embedding API has a hard limit of 100 requests per batch. Searchless-ngx now automatically detects large documents and splits them into compliant batches. This prevents the `INVALID_ARGUMENT` errors previously encountered with documents exceeding 100 chunks.

### ✂️ Configurable Document Truncation
To prevent resource exhaustion and ensure high-quality search results, we've introduced a configurable chunk limit:
- **`MAX_CHUNKS_PER_DOC`**: New environment variable (Default: `100`).
- **Capacity**: 100 chunks cover approximately **25 DIN-A4 pages** of text.
- **Graceful Handling**: Documents exceeding this limit are truncated at the end, and a warning is logged.

### 🧪 Enhanced Reliability
- **Automated Batching Tests**: We've added a new mocked test suite to verify the batching logic without requiring internet access.
- **Expanded Test Coverage**: This release is verified by **18 automated tests**, ensuring core stability.

---

# Release Notes - v0.1.3 🚀

We are proud to announce the **Initial Release of Searchless-ngx (v0.1.3)**, the first production-ready version of our Agentic RAG MCP Server for Paperless-ngx.

## What is Searchless-ngx?
Searchless-ngx transforms your Paperless-ngx instance from a static archive into an intelligent, conversational agent. By leveraging the Model Context Protocol (MCP) and Agentic RAG, it allows modern LLMs (like Gemini or GPT-4) to natively search, filter, and reason over your personal documents.

## Key Features in this Release

### 🎴 Professional Markdown "Cards"
Search results are now presented as high-quality interactive cards designed specifically for **Open WebUI**:
- **Linked Headers**: Document titles link directly to the document detail view in Paperless.
- **Dynamic Deep-Linking**: Correspondent names and Tags are now clickable links that filter for related documents.
- **Structural Preservation**: OCR snippets now respect original line breaks and paragraph structure.
- **Concise Layout**: Strict 7-line snippet limits keep your chat clean and readable.

### 🔍 Advanced Hybrid Search
- **Exact Metadata API**: Leverage the full power of Paperless-ngx filtering (correspondents, tags, dates).
- **Semantic Vector Search**: Use ChromaDB and Gemini embeddings to find documents by *meaning* (e.g., "Find food receipts from Berlin").
- **Custom Field Visibility**: Custom fields are beautifully integrated and resolved into readable names.

### 🏗️ Enterprise-Grade Reliability
- **Paginated Cache**: Efficiently handles large libraries with hundreds of tags and correspondents.
- **Strict JSON Schema**: 100% compatible with strict MCP parsers (no `anyOf` or `null` types).
- **Comprehensive Verification**: This release is verified by a full suite of **automated tests** covering all core components.

## Installation
For detailed installation and Open WebUI setup instructions, please refer to the [README.md](README.md) and [WEBUI_SETUP.md](WEBUI_SETUP.md).

Thank you for choosing Searchless-ngx!
