#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
python_bin="${DECOR_PYTHON:-.venv/bin/python}"
"$python_bin" scripts/export_public.py
if [[ "${1:-}" == "--build-only" ]]; then
  exit 0
fi
# Authentication is handled by Wrangler OAuth or a scoped token in the environment.
npx --yes wrangler@4.154.0 deploy --config "${DECOR_WRANGLER_CONFIG:-wrangler.public.jsonc}"
