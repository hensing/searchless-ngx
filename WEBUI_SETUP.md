# Open WebUI Setup Guide: Searchless-ngx

This guide will help you configure Open WebUI to use your Searchless-ngx (paperless-mcp-server) effectively.

## Section 1: One-Click Connection Setup

For the fastest and most reliable setup, use the JSON import feature.

1.  **Open Open WebUI**: Navigate to `http://localhost:8080` and log in.
2.  **Settings**: Click on your profile icon (bottom left) -> **Settings**.
3.  **Connections**: Select **Connections** from the left menu.
4.  **Import**: In the **MCP Servers** section, click the **Import** icon (the folder/upload symbol).
5.  **Select File**: Select the file located at `scripts/webui-connection.json` from the project repository.
6.  **Save**: Click **Save**. Open WebUI will now connect to the `http://mcp-server:8001/mcp` endpoint and discover the tools.

## Section 2: Creating your AI Assistant

1.  **Workspace**: Click on **Workspace** in the sidebar, then select **Models**.
2.  **Create Model**: Click the **+** (Create a model) button.
3.  **Basic Details**:
    *   **Name**: `Searchless-ngx Assistant`
    *   **Base Model**: Choose a smart model (e.g., `gemini-1.5-pro`, `gpt-4o`, or `llama3.1`).
4.  **Enable Tools**:
    *   Find the **Tools** section.
    *   Enable all tools starting with `paperless-mcp-server_` (e.g., `search_paperless_metadata`).
5.  **Citations**: Ensure citations are **enabled** in the model settings to correctly render the interactive document "cards".

## Section 3: The Optimized System Prompt

Copy and paste the following text into the **System Prompt** field:

```text
You are the Searchless-ngx Assistant, a highly precise AI managing the user's documents via Paperless-ngx.

You have access to:
- `search_paperless_metadata`: Primary tool for exact matches (Correspondents, Tags) or listing latest docs.
- `semantic_search_with_filters`: Best for conceptual queries ("software subs", "travel receipts").
- `get_document_details`: MANDATORY if snippets lack specific data (total sums, invoice numbers).
- `get_paperless_master_data`: To resolve human names to integer IDs.

RULES:
1. NO HALLUCINATIONS. If tools return nothing, say you found nothing.
2. RECENCY MATTERS: Always prioritize newer documents based on the `Created` date.
3. PROACTIVE SEARCH: If a search with specific filters (like dates or correspondents) returns nothing, you MUST automatically try a broader search (e.g., remove the date range) and inform the user.
4. ALWAYS cite your sources at the end of your response under a "**Sources:**" header. The tools provide pre-formatted Markdown "Cards" for each result (starting with `---` and `### 📄` and ending with `---`). You MUST include these cards EXACTLY as they are returned by the tool. Do not reformat, shorten, or summarize them.
```

## Section 4: Advanced Formatting Tips

Searchless-ngx is designed to output search results in a **Card-Style** format. This includes:
- **Linked Headers**: Click the title to open the document directly in Paperless.
- **Linked Metadata**: Click the correspondent or tag to filter for related documents.
- **Blockquotes**: Document snippets are clearly separated using Markdown blockquotes (`>`).

If results look like raw JSON, verify that you are using the latest version of Open WebUI and that the **MCP Streamable HTTP** transport is selected in your connection settings.
