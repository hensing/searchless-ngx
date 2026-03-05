import urllib.request
import json
import sys

# Target URL for the Streamable HTTP endpoint
# User specified path is /mcp
URL = "http://localhost:8001/mcp"

# Standard MCP JSON-RPC payload to request the tools list
payload = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
}

data = json.dumps(payload).encode("utf-8")

req = urllib.request.Request(
    URL,
    data=data,
    headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Host": "localhost"
    },
    method="POST"
)

print(f"Sending POST request to {URL} with payload:")
print(json.dumps(payload, indent=2))
print("-" * 40)

try:
    with urllib.request.urlopen(req) as response:
        print(f"Response Status: {response.status} {response.reason}")
        print("Response Headers:")
        for k, v in response.getheaders():
            print(f"  {k}: {v}")
        print("-" * 40)

        # Read the raw response
        # Streamable HTTP might return chunked data or newlines
        raw_body = response.read().decode("utf-8")

        print("RAW RESPONSE BODY (Exact String):")
        print(raw_body)
        print("-" * 40)

        # Attempt to parse and pretty-print if it's valid JSON
        try:
            # It might be JSON-RPC lines or a single JSON object
            lines = raw_body.strip().split('\n')
            for i, line in enumerate(lines):
                if line.strip():
                    parsed = json.loads(line)
                    print(f"PARSED JSON (Line {i+1}):")
                    print(json.dumps(parsed, indent=2))

                    # Validation comments regarding Open WebUI strictly checking inputSchema:
                    print("\n--- VALIDATION CHECK ---")
                    print("Open WebUI strictly requires standard JSON Schema for tool parameters.")
                    print("Check the 'inputSchema' of each tool in the result above:")
                    print("  1. Types must be valid JSON Schema types (e.g., 'string', 'integer', 'boolean', 'object', 'array').")
                    print("     Non-standard types like Python's 'str' or 'dict' will cause Open WebUI to silently drop the tool.")
                    print("  2. If the tool takes no arguments, 'inputSchema' should ideally be valid, e.g., {'type': 'object', 'properties': {}}.")
                    print("     If it is completely empty or missing required fields, it may fail.")
                    print("------------------------\n")

        except json.JSONDecodeError as e:
            print(f"Failed to parse response as JSON: {e}")

except urllib.error.URLError as e:
    print(f"Failed to connect or request failed: {e}")
    sys.exit(1)
