"""Skill packaging and frontmatter (no network)."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "SKILL.md"


def _frontmatter(text: str) -> str:
    parts = text.split("---", 2)
    assert len(parts) >= 3, "SKILL.md must start with YAML frontmatter"
    return parts[1]


def test_skill_frontmatter_is_standard():
    text = SKILL.read_text(encoding="utf-8")
    fm = _frontmatter(text)
    assert "name: doc2md" in fm
    assert "description:" in fm
    assert "display_name" not in fm
    keys = [
        line.split(":", 1)[0].strip()
        for line in fm.splitlines()
        if line.strip() and not line.startswith(" ") and ":" in line
    ]
    assert keys == ["name", "description"]


def test_skill_description_length_and_body_size():
    text = SKILL.read_text(encoding="utf-8")
    fm = _frontmatter(text)
    lines: list[str] = []
    grab = False
    for line in fm.splitlines():
        if line.startswith("description:"):
            grab = True
            continue
        if grab:
            if line and not line.startswith(" "):
                break
            lines.append(line.strip())
    desc = " ".join(x for x in lines if x)
    assert 1 <= len(desc) <= 1024
    assert text.count("\n") + 1 <= 500


def test_skill_links_references():
    text = SKILL.read_text(encoding="utf-8")
    for name in ("wps.md", "feishu.md", "local.md", "pdf.md"):
        path = ROOT / "references" / name
        assert path.is_file(), path
        assert f"references/{name}" in text


def test_openai_yaml_ui_metadata():
    yaml = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
    assert 'display_name: "文档转 Markdown"' in yaml
    assert "short_description:" in yaml
    assert "$doc2md" in yaml


def test_pack_comate_injects_display_name(tmp_path: Path):
    src = tmp_path / "SKILL.md"
    src.write_text(SKILL.read_text(encoding="utf-8"), encoding="utf-8")
    script = ROOT / "pack-comate.sh"
    subprocess.check_call(["bash", str(script), "--inject", str(src)])
    fm = _frontmatter(src.read_text(encoding="utf-8"))
    assert "display_name: 文档转Markdown" in fm
    assert fm.index("name: doc2md") < fm.index("display_name:")


def test_pack_comate_zip_is_slim(tmp_path: Path):
    import zipfile

    dest = tmp_path / "doc2md-comate.zip"
    subprocess.check_call(["bash", str(ROOT / "pack-comate.sh"), "0.0.0", str(dest)])
    with zipfile.ZipFile(dest) as zf:
        names = zf.namelist()
        skill = zf.read("SKILL.md").decode("utf-8")
    assert "SKILL.md" in names
    assert any(n.startswith("scripts/") and n.endswith(".py") for n in names)
    assert "scripts/doc2md.py" in names
    assert not any(n.startswith("tests/") for n in names)
    assert not any(n.startswith("references/") for n in names)
    assert "README.md" not in names
    assert "CHANGELOG.md" not in names
    assert "display_name: 文档转Markdown" in skill
