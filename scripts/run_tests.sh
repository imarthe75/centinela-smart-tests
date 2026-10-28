#!/usr/bin/env bash
# Runs the unit suite inside the project image (has Playwright, openpyxl, centinela-core). The repo is mounted read-only and copied to a
# writable temp dir inside the container, so nothing root-owned is left in the working tree. Browser-dependent tests are not here (they
# need a live app). Runs as root only to install pytest and copy; it never writes back to the mounted source.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
docker build -q -t centinela-smart-tests:dev "$ROOT" >/dev/null
exec docker run --rm --user root -v "$ROOT":/src:ro --entrypoint bash centinela-smart-tests:dev -c '
  cp -r /src /tmp/work && cd /tmp/work && pip install -q --root-user-action=ignore pytest >/dev/null 2>&1
  python -m pytest -q -rs -p no:cacheprovider "${@:-tests/}"' _ "$@"
