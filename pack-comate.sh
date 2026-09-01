#!/usr/bin/env bash
# Pack the Comate install zip: SKILL.md + scripts/ only.
# Tests, fixtures, README, and CHANGELOG stay in git; they timeout Comate's
# security-audit LLM (504 / 500102) if included.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  VERSION="$(awk '/^## v[0-9]/{sub(/^## v/, ""); print; exit}' "$ROOT/CHANGELOG.md")"
fi
if [[ -z "$VERSION" ]]; then
  echo "Could not infer version from CHANGELOG.md; pass it as arg 1." >&2
  exit 1
fi

DEST="${2:-}"
if [[ -z "$DEST" ]]; then
  DEST="$ROOT/doc2md-${VERSION}-comate.zip"
fi

rm -f "$DEST"
(
  cd "$ROOT"
  zip -r "$DEST" SKILL.md scripts \
    -x '*.pyc' '*__pycache__*' '*.pytest_cache*' '*.git*' '*DS_Store'
)

echo "$DEST"
ls -lh "$DEST"
