#!/usr/bin/env bash
# Pack the Comate install zip: SKILL.md + scripts/ only.
# Tests, fixtures, README, CHANGELOG, agents/, and references/ stay in git.
# Extra markdown/tests make Comate's security-audit LLM time out (504 / 500102).
#
# Git SKILL.md has only name/description (official skill validator).
# The Comate platform skill is anything-to-markdown. The zip must use that
# name or install fails with "包内是 doc2md". display_name is the UI title.
# Both are injected into the zip (and a live overlay via --inject PATH).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
COMATE_DISPLAY_NAME="${COMATE_DISPLAY_NAME:-文档转Markdown}"
COMATE_SKILL_NAME="${COMATE_SKILL_NAME:-anything-to-markdown}"

inject_comate_display_name() {
  local skill_md="$1"
  python3 - "$skill_md" "$COMATE_DISPLAY_NAME" "$COMATE_SKILL_NAME" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
display = sys.argv[2]
skill_name = sys.argv[3]
text = path.read_text(encoding="utf-8")
if not text.startswith("---"):
    raise SystemExit(f"{path}: missing YAML frontmatter")
parts = text.split("---", 2)
if len(parts) < 3:
    raise SystemExit(f"{path}: truncated YAML frontmatter")
fm = parts[1]
if "\nname: doc2md\n" in fm or fm.lstrip().startswith("name: doc2md\n"):
    fm = fm.replace("name: doc2md\n", f"name: {skill_name}\n", 1)
elif f"name: {skill_name}\n" not in fm and not fm.lstrip().startswith(f"name: {skill_name}\n"):
    raise SystemExit(f"{path}: expected 'name: doc2md' in frontmatter")
if "\ndisplay_name:" not in fm and not fm.lstrip().startswith("display_name:"):
    needle = f"name: {skill_name}\n"
    if needle not in fm:
        raise SystemExit(f"{path}: missing name after rewrite")
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
inject_comate_display_name "$STAGE/SKILL.md"

rm -f "$DEST"
(
  cd "$STAGE"
  COPYFILE_DISABLE=1 zip -X -r "$DEST" SKILL.md scripts \
    -x '*.pyc' '*__pycache__*' '*.pytest_cache*' '*.git*' '*DS_Store' '*/.*'
)

echo "$DEST"
ls -lh "$DEST"
