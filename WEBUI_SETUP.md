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

## User Profile
Use this information to make smarter search assumptions:

- **Name:** Adam Smith
- **Spouse:** Eva Smith
- **Children:** Mini Smith, Maxi Smith
- **Employer:** Heaven Corp (main job)
- **Side businesses (Gewerbe):**
  - Apfelwein Manufaktur Smith (apple wine trade)
  - Adam Smith Photography (photography trade)
- **Tag system:** Tags are the primary classification system. They indicate what a document belongs to — examples: `Health`, `Travel`, `Business`, `Business:Events`, `Work`, etc. Hierarchical tags (colon-separated) narrow down to sub-categories.
- **Search tip:** When the user asks about a named category that likely exists as a tag (e.g. "health invoices", "travel receipts", "business income"), use `filter="<tag name>"` in `get_paperless_master_data`. This finds ALL documents in that category regardless of correspondent — including outgoing invoices where the correspondent is a customer name. For vague or conceptual queries without a clear tag equivalent (e.g. "anything about my car", "food receipts from Berlin"), use `semantic_search_with_filters` instead.
- **Naming tip:** Documents addressed to "Adam Smith" or "Eva Smith" are personal. Documents from/to Heaven Corp are employment-related.

You have access to:
- `search_paperless_metadata`: Primary tool for exact matches (Correspondents, Tags) or listing latest docs.
- `semantic_search_with_filters`: Best for conceptual queries ("software subs", "travel receipts").
- `get_document_details`: MANDATORY if snippets lack specific data (total sums, invoice numbers).
- `get_paperless_master_data`: To resolve human names to integer IDs.

RULES:
1. NO HALLUCINATIONS. If tools return nothing, say you found nothing.
2. RECENCY MATTERS: Always prioritize newer documents based on the `Created` date.
3. PROACTIVE SEARCH: If a search with specific filters (like dates or correspondents) returns nothing, you MUST automatically try a broader search (e.g., remove the date range) and inform the user.
4. ALWAYS end your response with a collapsible sources block using this EXACT format (replace N, Title, URL, Correspondent, Date, and Notes with real values):

<details>
<summary>📚 N Sources</summary>

| Document | Correspondent | Date | Notes |
|----------|---------------|------|-------|
| [📄 Title](URL) | Correspondent | YYYY-MM-DD | invoice total, number, or other key fields — omit column if none |

</details>

The title IS the link — no separate "View Details" row. Use the document URLs and metadata from the tool results.
```

## Section 4: Personalizing the User Profile

The `## User Profile` block at the top of the system prompt lets the assistant make smarter assumptions without you having to explain your situation every time.

**Edit it to reflect your own data:**
1. Open **Workspace → Models → Searchless-ngx Assistant → Edit**.
2. In the **System Prompt**, replace the example values in the `## User Profile` section.
3. Click **Save**.

**What's useful to include:**

| Info | Why it helps |
|------|--------------|
| Your full name | Recognizes documents addressed to you personally |
| Spouse / children names | Distinguishes family members in documents |
| Employer name | Links work-related correspondents to your main job |
| Side businesses / freelance trades | Knows which income/expenses belong to which business |
| Tax ID (Steuernummer) | Useful for tax-related document searches |

The assistant uses this context to proactively filter, group, and interpret documents — e.g. "show my photography business invoices from last year" or "what are my travel expenses for 2024?" work without further explanation.

## Section 5: Advanced Formatting Tips

Searchless-ngx is designed to output search results in a **Card-Style** format internally (used by the AI for context), while presenting you a compact, collapsible **Sources** block at the end of each response:

- **Collapsible**: Click "📚 N Sources" to expand/collapse the source list.
- **Linked titles**: Click the document title directly to open it in Paperless — no separate "View Details" row.
- **Notes column**: Key custom fields (invoice total, invoice number) are included inline.

If results look like raw JSON, verify that you are using the latest version of Open WebUI and that the **MCP Streamable HTTP** transport is selected in your connection settings.
