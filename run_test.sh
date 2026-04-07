#!/bin/bash
set -e

echo "Building Docker image ..."
docker build -t searchless-ngx-test -f docker/Dockerfile .

echo "Starting pytest in docker ..."
docker run --rm -e PAPERLESS_URL=http://mock -e PAPERLESS_TOKEN=mock -e GEMINI_API_KEY=mock searchless-ngx-test uv run pytest -vv
echo "pytest finished."

