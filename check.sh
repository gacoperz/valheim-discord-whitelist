#!/bin/sh
# Lint and test in a throwaway container (nothing is installed on the host). Run from anywhere.
set -e
cd "$(dirname "$0")"
docker run --rm -v "$PWD":/src:ro -w /src -e PYTHONDONTWRITEBYTECODE=1 -e RUFF_NO_CACHE=true python:3.13-slim sh -c '
  pip install -q --root-user-action=ignore -r requirements.txt pytest ruff 2>&1 | grep -v "notice" || true
  ruff check --no-cache . host/bin/valheim-botdb-snapshot && python -m pytest -q -p no:cacheprovider'
