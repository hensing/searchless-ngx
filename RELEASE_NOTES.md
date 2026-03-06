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
- **Comprehensive Verification**: This release is verified by a full suite of **17 automated tests** covering all core components.

## Installation
For detailed installation and Open WebUI setup instructions, please refer to the [README.md](README.md) and [WEBUI_SETUP.md](WEBUI_SETUP.md).

Thank you for choosing Searchless-ngx!
