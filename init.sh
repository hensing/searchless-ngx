#!/bin/bash
set -e

echo "Starting Paperless-ngx Semantic Ingestion..."
docker compose run --rm mcp-server uv run python -m semantic.bulk_sync
echo "Bulk sync finished."
