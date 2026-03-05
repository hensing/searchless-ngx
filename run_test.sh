#!/bin/bash
set -e

echo "Starting pytest in docker ..."
docker run --rm -e PAPERLESS_URL=http://mock -e PAPERLESS_TOKEN=mock -e GEMINI_API_KEY=mock searchless-ngx-test pytest -vv
echo "pytest finished."

