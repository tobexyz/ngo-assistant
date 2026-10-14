#!/usr/bin/env bash
# Pull the Ollama models into the compose stack's model volume.
# Usage: scripts/pull-models.sh [extra-model ...]   e.g. scripts/pull-models.sh llama3.2:3b
# Requires: `docker compose up -d ollama` already running.
set -euo pipefail

cd "$(dirname "$0")/.."

chat_model="${NGO_CHAT_MODEL:-llama3.2:1b}"
embed_model="${NGO_EMBED_MODEL:-bge-m3}"

if ! docker compose ps --status running --services 2>/dev/null | grep -qx ollama; then
  echo "error: the ollama service is not running. Start it with: docker compose up -d ollama" >&2
  exit 1
fi

for model in "$chat_model" "$embed_model" "$@"; do
  echo "pulling ${model}"
  docker compose exec -T ollama ollama pull "$model"
done

echo "done. installed models:"
docker compose exec -T ollama ollama list
