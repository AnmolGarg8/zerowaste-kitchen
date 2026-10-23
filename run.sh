#!/usr/bin/env bash
set -eo pipefail

# Ensure the server binds ZW_HOST=0.0.0.0 on port 8000 and uses DynamoDB storage
export ZW_HOST="0.0.0.0"
export ZW_PORT="8000"
export ZW_STORE="dynamodb"

# Run the FastMCP server on port 8000 (forwarded by AWS Lambda Web Adapter)
exec python -m zerowaste.server
