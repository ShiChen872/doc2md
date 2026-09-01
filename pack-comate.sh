#!/usr/bin/env bash
# Pack the Comate install zip: SKILL.md + scripts/ + references/.
# Tests, fixtures, README, CHANGELOG, and agents/ stay in git; tests trip
# Comate's security-audit LLM (504 / 500102) if included.
#
# Git SKILL.md has only name/description (official skill validator).
# Comate UI needs display_name, so this script injects it into the zip
# (and can inject a live overlay with --inject PATH).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
COMATE_DISPLAY_NAME="${COMATE_DISPLAY_NAME:-文档转Markdown}"

inject_comate_display_name() {
  local skill_md="$1"
  python3 - "$skill_md" "$COMATE_DISPLAY_NAME" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
display = sys.argv[2]
text = path.read_text(encoding="utf-8")
if not text.startswith("---"):
    raise SystemExit(f"{path}: missing YAML frontmatter")
parts = text.split("---", 2)
if len(parts) < 3:
    raise SystemExit(f"{path}: truncated YAML frontmatter")
fm = parts[1]
if "\ndisplay_name:" in fm or fm.lstrip().startswith("display_name:"):
    path.write_text(text, encoding="utf-8")
    raise SystemExit(0)
needle = "name: doc2md\n"
if needle not in fm:
    raise SystemExit(f"{path}: expected 'name: doc2md' in frontmatter")
fm = fm.replace(needle, needle + f"display_name: {display}\n", 1)
path.write_text("---" + fm + "---" + parts[2], encoding="utf-8")
PY
}

if [[ "${1:-}" == "--inject" ]]; then
  TARGET="${2:-}"
  if [[ -z "$TARGET" ]]; then
    echo "usage: $0 --inject /path/to/SKILL.md" >&2
    exit 2
  fi
  inject_comate_display_name "$TARGET"
  exit 0
fi

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

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp "$ROOT/SKILL.md" "$STAGE/SKILL.md"
cp -R "$ROOT/scripts" "$STAGE/scripts"
cp -R "$ROOT/references" "$STAGE/references"
inject_comate_display_name "$STAGE/SKILL.md"

rm -f "$DEST"
(
  cd "$STAGE"
  zip -r "$DEST" SKILL.md scripts references \
    -x '*.pyc' '*__pycache__*' '*.pytest_cache*' '*.git*' '*DS_Store'
)

echo "$DEST"
ls -lh "$DEST"
