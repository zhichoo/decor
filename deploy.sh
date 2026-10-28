#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
umask 077
docker compose version >/dev/null
if [[ ! -f .env.docker ]]; then
  command -v openssl >/dev/null || { echo 'Install openssl to generate deployment passwords.' >&2; exit 1; }
  # Only generate for a new deployment; never rotate an existing database password.
  db_password="$(openssl rand -hex 24)"
  admin_password="$(openssl rand -hex 24)"
  while IFS= read -r line || [[ -n "$line" ]]; do
    case "$line" in
      POSTGRES_PASSWORD=*) printf 'POSTGRES_PASSWORD=%s\n' "$db_password" ;;
      ADMIN_PASSWORD=*) printf 'ADMIN_PASSWORD=%s\n' "$admin_password" ;;
      *) printf '%s\n' "$line" ;;
    esac
  done < .env.docker.example > .env.docker
  echo 'Created private .env.docker. Set your API key there; use its ADMIN_PASSWORD to log in.'
fi
chmod 600 .env.docker
if [[ $# -eq 0 ]]; then
  docker compose --env-file .env.docker -f compose.deploy.yaml up -d --build
  echo 'Started. Default address: http://127.0.0.1:4189 (or DECOR_PORT in .env.docker).'
else
  exec docker compose --env-file .env.docker -f compose.deploy.yaml "$@"
fi
