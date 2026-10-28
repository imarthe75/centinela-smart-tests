#!/usr/bin/env bash
# Host wrapper. Usage:
#   scripts/smart-tests.sh <command> <args.json> [--env-file /path/.env] [--package /path/pkg.zip] [--ci /path/reports] [--out /path/out] [--dev]
# Secrets (VAULT_ADDR, VAULT_TOKEN, VAULT_NAMESPACE, SMART_TESTS_INGEST_URL, SMART_TESTS_INGEST_TOKEN) are read from the env file
# and passed to the container on STDIN, never in argv or environment variables. --dev mounts the working tree (no rebuild).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CMD="$1"; ARGS_FILE="$2"; shift 2
ENV_FILE=""; PKG=""; CI=""; OUT="$ROOT/out"; DEV=0
while [ $# -gt 0 ]; do
  case "$1" in
    --env-file) ENV_FILE="$2"; shift 2;;
    --package) PKG="$2"; shift 2;;
    --ci) CI="$2"; shift 2;;
    --out) OUT="$2"; shift 2;;
    --dev) DEV=1; shift;;
    *) echo "argumento desconocido: $1" >&2; exit 2;;
  esac
done
[ -n "$ENV_FILE" ] || { echo "falta --env-file" >&2; exit 2; }
mkdir -p "$OUT"; chmod 777 "$OUT"
MOUNTS=(-v "$OUT":/out)
[ -n "$PKG" ] && MOUNTS+=(-v "$(realpath "$PKG")":"/pkg/package.${PKG##*.}":ro)   # fixed name inside: the args use /pkg/package.<ext>
[ -n "$CI" ] && MOUNTS+=(-v "$(realpath "$CI")":/ci:ro)              # ci-report reads /ci (JUnit/JaCoCo XML)
[ "$DEV" = "1" ] && MOUNTS+=(-v "$ROOT/smart_tests":/app/smart_tests:ro)
python3 - "$ENV_FILE" "$CMD" "$ARGS_FILE" <<'PY' | docker run -i --rm --network aura-network --memory 2g --cpus 2 "${MOUNTS[@]}" centinela-smart-tests:dev
import json, sys
from dotenv import dotenv_values
env = dotenv_values(sys.argv[1])
secrets = {"vault_addr": env.get("VAULT_ADDR", ""), "vault_token": env.get("VAULT_TOKEN", ""), "vault_namespace": env.get("VAULT_NAMESPACE", ""),
           "ingest_url": env.get("SMART_TESTS_INGEST_URL", ""), "ingest_token": env.get("SMART_TESTS_INGEST_TOKEN", "")}
print(json.dumps({"command": sys.argv[2], "secrets": secrets, "args": json.load(open(sys.argv[3]))}))
PY
