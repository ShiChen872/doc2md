#!/usr/bin/env python3
"""Convert a Feishu/Lark wiki, docx, board, base, sheets, or mindnotes URL to Markdown (+ local images).

Usage:
  feishu_to_md.py <url> [-o OUTPUT.md]

Uses Playwright storage from feishu_login.py:
  ~/.config/doc2md/feishu_storage_state.json

Flow:
  1. Open URL with saved session (or anonymously for public docs)
  2. Wait for PageMain blockManager, scroll to load lazy blocks
  3. Serialize block tree → Markdown
  4. Download images/files via in-page managers into *_assets/
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urlparse, urlunparse

import session as sess

CFG = Path.home() / ".config" / "doc2md"
DEFAULT_STATE = CFG / "feishu_storage_state.json"
SAFE_NAME_RE = re.compile(r"[^\w.\u4e00-\u9fff\-]+")

# Hosts we accept for Feishu / Lark docs
HOST_RE = re.compile(
    r"(?:^|\.)(?:feishu\.cn|larksuite\.com|larkoffice\.com)$",
    re.IGNORECASE,
)
FEISHU_RESERVED_TOKENS = frozenset(
    {
        "space",
        "settings",
        "create",
        "home",
        "share",
        "gallery",
        "wiki",
        "docx",
        "docs",
        "board",
        "base",
        "sheets",
        "sheet",
        "mindnotes",
        "mindnote",
        "form",
        "view",
        "dashboard",
        "table",
        "record",
        "drive",
    }
)
# /wiki/TOKEN or /docx/TOKEN or legacy /docs/TOKEN
# also standalone 画板 /board/, 多维表格 /base/, 电子表格 /sheets/, 思维笔记 /mindnotes/
PATH_RE = re.compile(
    r"/(wiki|docx|docs|board|base|sheets|sheet|mindnotes|mindnote)/([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)
# SHARE_BASE_RE must be applied before PATH_RE: /share/base/form/TOKEN would
# otherwise look like kind=base token=form.
SHARE_BASE_RE = re.compile(
    r"/share/base/(?:(?:form|view|dashboard|table|record|gallery)/)?([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)

# Trailing slash prevents naive replace of id "7" from mangling "73" / "76".
ASSET_PLACEHOLDER = "feishu-asset://{kind}/{block_id}/"

# Feishu Open API CodeLanguage enum → Markdown fence tag.
# https://open.feishu.cn/document/ukTMukTMukTM/uUDN04SN0QjL1QDN/document-docx/docx-v1/data-structure/block
CODE_LANGUAGE_ENUM: dict[int, str] = {
    1: "",  # PlainText
    2: "abap",
    3: "ada",
    4: "apache",
    5: "apex",
    6: "asm",
    7: "bash",
    8: "csharp",
    9: "cpp",
    10: "c",
    11: "cobol",
    12: "css",
    13: "coffeescript",
    14: "d",
    15: "dart",
    16: "delphi",
    17: "django",
    18: "dockerfile",
    19: "erlang",
    20: "fortran",
    21: "foxpro",
    22: "go",
    23: "groovy",
    24: "html",
    25: "handlebars",
    26: "http",
    27: "haskell",
    28: "json",
    29: "java",
    30: "javascript",
    31: "julia",
    32: "kotlin",
    33: "latex",
    34: "lisp",
    35: "logo",
    36: "lua",
    37: "matlab",
    38: "makefile",
    39: "markdown",
    40: "nginx",
    41: "objectivec",
    42: "abl",
    43: "php",
    44: "perl",
    45: "postscript",
    46: "powershell",
    47: "prolog",
    48: "protobuf",
    49: "python",
    50: "r",
    51: "rpg",
    52: "ruby",
    53: "rust",
    54: "sas",
    55: "scss",
    56: "sql",
    57: "scala",
    58: "scheme",
    59: "scratch",
    60: "shell",
    61: "swift",
    62: "thrift",
    63: "typescript",
    64: "vbscript",
    65: "vb",
    66: "xml",
    67: "yaml",
    68: "cmake",
    69: "diff",
    70: "gherkin",
    71: "graphql",
    72: "glsl",
    73: "properties",
    74: "solidity",
    75: "toml",
}

SERIALIZE_BLOCK_TREE_JS = """
() => {
  const trimCaption = (caption) => {
    return caption?.text?.initialAttributedTexts?.text?.[0] ?? '';
  };

  const safeJson = (value) => {
    try {
      return JSON.parse(JSON.stringify(value ?? null));
    } catch (error) {
      return null;
    }
  };

  const simplifyOps = (ops) => {
    if (!Array.isArray(ops)) {
      return [];
    }
    return ops.map((op) => ({
      insert: typeof op?.insert === 'string' ? op.insert : '',
      attributes: safeJson(op?.attributes ?? {}),
    }));
  };

  const effectiveTypeOf = (block) => {
    const snapshotType = block?.snapshot?.type || '';
    if (block?.type === 'fallback') {
      return snapshotType || 'fallback';
    }
    return block?.type || snapshotType || '';
  };

  const simplifySnapshot = (block) => {
    const snapshot = block?.snapshot ?? {};
    const effectiveType = effectiveTypeOf(block);
    const base = { type: effectiveType };

    switch (effectiveType) {
      case 'ordered':
        return { ...base, seq: snapshot.seq ?? '' };
      case 'todo':
        return { ...base, done: Boolean(snapshot.done) };
      case 'code':
        return {
          ...base,
          language: snapshot.language ?? snapshot.lang ?? snapshot.style?.language ?? '',
        };
      case 'table':
        return {
          ...base,
          rows_id: Array.isArray(snapshot.rows_id) ? snapshot.rows_id : [],
          columns_id: Array.isArray(snapshot.columns_id) ? snapshot.columns_id : [],
        };
      case 'grid_column':
        return { ...base, width_ratio: snapshot.width_ratio ?? null };
      case 'image':
        return {
          ...base,
          image: {
            token: snapshot.image?.token ?? '',
            name: snapshot.image?.name ?? '',
            caption: trimCaption(snapshot.image?.caption),
          },
        };
      case 'file':
        return {
          ...base,
          file: {
            name: snapshot.file?.name ?? '',
            token: snapshot.file?.token ?? '',
          },
        };
      case 'iframe':
        return {
          ...base,
          iframe: {
            height: snapshot.iframe?.height ?? null,
            component: {
              url: snapshot.iframe?.component?.url ?? '',
            },
          },
        };
      case 'whiteboard':
        return {
          ...base,
          whiteboard: {
            caption: trimCaption(snapshot.caption),
          },
        };
      case 'board':
        return {
          ...base,
          board: {
            token: snapshot.board?.token ?? snapshot.token ?? '',
          },
        };
      case 'bitable':
        return {
          ...base,
          bitable: {
            token: snapshot.bitable?.token ?? snapshot.token ?? '',
          },
        };
      case 'sheet':
        return {
          ...base,
          sheet: {
            token: snapshot.sheet?.token ?? snapshot.token ?? '',
          },
        };
      case 'mindnote':
        return {
          ...base,
          mindnote: {
            token: snapshot.mindnote?.token ?? snapshot.token ?? '',
          },
        };
      case 'diagram':
        return { ...base, diagram: {} };
      case 'isv':
        return {
          ...base,
          block_type_id: snapshot.block_type_id ?? '',
          data: safeJson(snapshot.data),
        };
      case 'bookmark':
        return {
          ...base,
          url: snapshot.url ?? snapshot.bookmark?.url ?? snapshot.link ?? '',
          title: snapshot.title ?? snapshot.bookmark?.title ?? '',
        };
      default:
        return base;
    }
  };

  const simplifyBlock = (block) => {
    if (!block) {
      return null;
    }

    const syncedChildren = Array.isArray(block?.innerBlockManager?.rootBlockModel?.children)
      ? block.innerBlockManager.rootBlockModel.children.map(simplifyBlock).filter(Boolean)
      : null;

    return {
      id: block.id ?? null,
      type: effectiveTypeOf(block),
      record_id: block?.record?.id ?? '',
      zone_state: block?.zoneState
        ? {
            all_text: block.zoneState.allText ?? '',
            content: {
              ops: simplifyOps(block.zoneState?.content?.ops ?? []),
            },
          }
        : null,
      snapshot: simplifySnapshot(block),
      children: Array.isArray(block.children)
        ? block.children.map(simplifyBlock).filter(Boolean)
        : [],
      synced_children: syncedChildren,
      is_all_data_ready: block?.isAllDataReady ?? null,
    };
  };

  const root = window.PageMain?.blockManager?.rootBlockModel;
  if (!root) {
    return null;
  }

  return {
    title: root?.zoneState?.allText ?? document.title ?? '',
    root: simplifyBlock(root),
  };
}
"""

WAIT_PAGE_READY_JS = """
() => {
  if (!window.PageMain?.blockManager?.rootBlockModel) {
    return false;
  }
  const hydratingTypes = new Set(['whiteboard', 'board', 'bitable', 'sheet', 'mindnote', 'code', 'file']);
  const isBlockReady = (block) => {
    if (!block) {
      return true;
    }
    const snapshotType = block?.snapshot?.type;
    const blockType = block?.type;
    const ready = snapshotType !== 'pending';
    const syncedReady = blockType !== 'synced_reference' || block?.isAllDataReady;
    const hydratingFallback = blockType === 'fallback' && hydratingTypes.has(snapshotType);
    if (!ready || !syncedReady || hydratingFallback) {
      return false;
    }
    const children = Array.isArray(block.children) ? block.children : [];
    const synced = Array.isArray(block?.innerBlockManager?.rootBlockModel?.children)
      ? block.innerBlockManager.rootBlockModel.children
      : [];
    return children.every(isBlockReady) && synced.every(isBlockReady);
  };
  return isBlockReady(window.PageMain.blockManager.rootBlockModel);
}
"""

DOWNLOAD_ASSET_JS = """
async (asset) => {
  const findBlock = (block, targetId) => {
    if (!block) return null;
    // ids may be number in PageMain but string after JSON serialize
    if (String(block.id) === String(targetId)) return block;
    const children = Array.isArray(block.children) ? block.children : [];
    for (const child of children) {
      const found = findBlock(child, targetId);
      if (found) return found;
    }
    const syncedChildren = Array.isArray(block?.innerBlockManager?.rootBlockModel?.children)
      ? block.innerBlockManager.rootBlockModel.children
      : [];
    for (const child of syncedChildren) {
      const found = findBlock(child, targetId);
      if (found) return found;
    }
    return null;
  };

  const toBase64 = async (blob) => {
    return await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const result = String(reader.result || '');
        const index = result.indexOf(',');
        resolve(index >= 0 ? result.slice(index + 1) : result);
      };
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(blob);
    });
  };

  const extensionFromMime = (mimeType, fallback) => {
    const mapping = {
      'image/png': '.png',
      'image/jpeg': '.jpg',
      'image/jpg': '.jpg',
      'image/gif': '.gif',
      'image/webp': '.webp',
      'image/svg+xml': '.svg',
      'application/pdf': '.pdf',
    };
    return mapping[mimeType] || fallback;
  };

  const buildFileUrl = (token, recordId) => {
    const hostname = window.globalConfig?.drive_api?.[0];
    if (!hostname) {
      throw new Error('Failed to resolve file download url');
    }
    const url = new URL('https://' + hostname + '/space/api/box/stream/download/all/' + token);
    url.searchParams.set('mount_node_token', recordId);
    url.searchParams.set('mount_point', 'docx_file');
    url.searchParams.set(
      'synced_block_host_token',
      window.location.pathname.split('/').at(-1) ?? '',
    );
    url.searchParams.set('synced_block_host_type', '22');
    return url.toString();
  };

  const blobFromImage = async (block) => {
    const image = block?.snapshot?.image;
    if (!image || !block?.imageManager?.fetch) {
      return null;
    }
    const sources = await new Promise((resolve, reject) => {
      block.imageManager
        .fetch({ token: image.token, isHD: true, fuzzy: false }, {}, resolve)
        .catch(reject);
    });
    if (!sources?.src) {
      return null;
    }
    const response = await fetch(sources.src, { credentials: 'include' });
    if (!response.ok) {
      throw new Error('image download failed');
    }
    const blob = await response.blob();
    const fallbackExt = extensionFromMime(blob.type || '', '.png');
    return {
      base64: await toBase64(blob),
      file_name: image.name || `image-${block.id}${fallbackExt}`,
    };
  };

  const blobFromFile = async (block) => {
    const file = block?.snapshot?.file;
    if (!file?.token) {
      return null;
    }
    const response = await fetch(
      buildFileUrl(file.token, block?.record?.id ?? ''),
      { method: 'GET', credentials: 'include' },
    );
    if (!response.ok) {
      throw new Error('file download failed');
    }
    const blob = await response.blob();
    const fallbackExt = extensionFromMime(blob.type || '', '');
    return {
      base64: await toBase64(blob),
      file_name: file.name || `file-${block.id}${fallbackExt}`,
    };
  };

  const blobFromWhiteboard = async (block) => {
    if (!block?.whiteboardBlock) {
      return null;
    }
    const padding = 24;
    const ratio = window.devicePixelRatio || 1;
    const backgroundColor = '#ffffff';
    const toCanvasBlob = async (canvas) => {
      return await new Promise((resolve) => {
        canvas.toBlob(resolve, 'image/png');
      });
    };

    let ratioApp = block.whiteboardBlock?.abilityKit?.getRatioApp?.();
    if (ratioApp?.app) {
      const bounds = ratioApp.app.application.nodeManager.getNodesBounds();
      bounds.maxX += padding;
      bounds.minX -= padding;
      bounds.maxY += padding;
      bounds.minY -= padding;
      const canvas = ratioApp.app.renderManager.getImageOffscreenCanvas(
        bounds,
        ratio,
        backgroundColor,
      );
      if (!canvas) return null;
      const blob = await toCanvasBlob(canvas);
      if (!blob) return null;
      return {
        base64: await toBase64(blob),
        file_name: `whiteboard-${block.id}.png`,
      };
    }
    return null;
  };

  const blobFromDiagram = async (block) => {
    const blockView = block?.blockManager?.getBlockViewByBlockId?.(block.id);
    const svgElement = blockView?.getSvg?.();
    if (!svgElement) {
      return null;
    }
    const svgText = new XMLSerializer().serializeToString(svgElement);
    const blob = new Blob([svgText], { type: 'image/svg+xml' });
    return {
      base64: await toBase64(blob),
      file_name: `diagram-${block.id}.svg`,
    };
  };

  const root = window.PageMain?.blockManager?.rootBlockModel;
  if (!root) return null;
  const block = findBlock(root, asset.block_id);
  if (!block) return null;

  switch (asset.asset_type) {
    case 'image':
      return await blobFromImage(block);
    case 'file':
      return await blobFromFile(block);
    case 'whiteboard':
      return await blobFromWhiteboard(block);
    case 'diagram':
      return await blobFromDiagram(block);
    default:
      return null;
  }
}
"""


class FeishuError(Exception):
    pass


def is_login_error(exc: BaseException | str) -> bool:
    return "需要登录" in str(exc)


def interactive_feishu_login(url: str) -> None:
    """Open headed Chrome for the user to log in; do not scrape credentials."""
    print(
        "Feishu session missing or expired — opening Chrome. "
        "Complete login in the window; conversion will continue.",
        file=sys.stderr,
    )
    from feishu_login import LoginError, run_login

    try:
        run_login(url)
    except LoginError as e:
        raise FeishuError(str(e)) from e


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url.startswith("http"):
        url = "https://" + url
    return url


def safe_stem(name: str) -> str:
    base = Path(name).stem or name
    return SAFE_NAME_RE.sub("_", base).strip("._") or "feishu_document"


def check_feishu_host(url: str) -> str:
    """HTTPS + Feishu/Lark host. Document token optional (login home pages)."""
    raw = normalize_url(url)
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or not HOST_RE.search(host):
        raise FeishuError(f"Not a Feishu/Lark HTTPS URL: {url}")
    if parsed.port not in (None, 443):
        raise FeishuError(f"Unexpected port on Feishu URL: {url}")
    return raw


def parse_feishu_url(url: str) -> dict[str, str]:
    """Parse wiki/docx/docs/board/base/sheets/mindnotes URL → {kind, token, host, url}."""
    url = check_feishu_host(url)
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""
    m2 = SHARE_BASE_RE.search(path)
    if m2 and m2.group(1).lower() not in FEISHU_RESERVED_TOKENS:
        return {"kind": "base", "token": m2.group(1), "host": host, "url": url}
    m = PATH_RE.search(path)
    if m:
        kind = m.group(1).lower()
        token = m.group(2)
        if token.lower() in FEISHU_RESERVED_TOKENS:
            raise FeishuError(f"Cannot parse document token from URL: {url}")
        kind = {
            "sheets": "sheet",
            "sheet": "sheet",
            "mindnotes": "mindnote",
            "mindnote": "mindnote",
        }.get(kind, kind)
        if kind == "docs":
            # Legacy docs are limited; still return kind so caller can warn
            pass
        return {"kind": kind, "token": token, "host": host, "url": url}
    raise FeishuError(
        "Cannot parse document token from URL "
        "(need /wiki/, /docx/, /docs/, /board/, /base/, /sheets/, or /mindnotes/): "
        f"{url}"
    )


BOARD_VIEW_SEL = (
    ".tl-canvas, [class*='ccm-board'], #ccm-board, "
    "iframe[src*='/board/'], [class*='universe-board'], .board-host"
)
BITABLE_VIEW_SEL = (
    ".bitable-form-share-wrapper, [class*='bitable-container'], "
    "[class*='bitable-view'], [class*='bitable-form'], "
    ".suite-bitable, [class*='base-table']"
)
SHEET_VIEW_SEL = (
    ".fortune-container, .fortune-sheet, .suite-spreadsheet, "
    "[class*='spreadsheet-container'], [class*='sheet-container'], "
    "#sheet-container, iframe[src*='/sheets/']"
)
MINDNOTE_VIEW_SEL = (
    "[class*='mindnote'], [class*='MindNote'], "
    ".jsmind, [class*='jsmind'], "
    "iframe[src*='/mindnotes/'], iframe[src*='/mindnote/']"
)

PREVIEW_META: dict[str, dict[str, str]] = {
    "board": {
        "sel": BOARD_VIEW_SEL,
        "heading": "画布",
        "type_line": "> 类型: 飞书画板分享（网页预览分页截图；可见画布）",
        "mode": "board-preview",
    },
    "base": {
        "sel": BITABLE_VIEW_SEL,
        "heading": "视图",
        "type_line": "> 类型: 飞书多维表格分享（网页预览分页截图；可见视图）",
        "mode": "bitable-preview",
    },
    "sheet": {
        "sel": SHEET_VIEW_SEL,
        "heading": "表格",
        "type_line": "> 类型: 飞书电子表格分享（网页预览分页截图；可见工作表）",
        "mode": "sheet-preview",
    },
    "mindnote": {
        "sel": MINDNOTE_VIEW_SEL,
        "heading": "脑图",
        "type_line": "> 类型: 飞书思维笔记分享（网页预览分页截图；可见脑图）",
        "mode": "mindnote-preview",
    },
}

EMBED_SCREENSHOT_TYPES = {"board", "bitable", "whiteboard", "sheet", "mindnote"}
ASSET_BLOCK_TYPES = {
    "image",
    "file",
    "whiteboard",
    "diagram",
    "board",
    "bitable",
    "sheet",
    "mindnote",
}


def _page_looks_like_board(page: Any) -> bool:
    try:
        return page.locator(BOARD_VIEW_SEL).count() > 0
    except Exception:
        return False


def _page_looks_like_bitable(page: Any) -> bool:
    try:
        return page.locator(BITABLE_VIEW_SEL).count() > 0
    except Exception:
        return False


def _page_looks_like_sheet(page: Any) -> bool:
    try:
        return page.locator(SHEET_VIEW_SEL).count() > 0
    except Exception:
        return False


def _page_looks_like_mindnote(page: Any) -> bool:
    try:
        return page.locator(MINDNOTE_VIEW_SEL).count() > 0
    except Exception:
        return False


def _dismiss_feishu_guides(page: Any) -> None:
    for _ in range(2):
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        page.wait_for_timeout(150)
    for label in ("我知道了", "暂不需要", "关闭"):
        try:
            loc = page.get_by_text(label, exact=True)
            if loc.count():
                loc.first.click(timeout=1200)
                page.wait_for_timeout(200)
        except Exception:
            continue


def build_feishu_preview_markdown(
    *,
    title: str,
    source_url: str,
    kind: str,
    pages: list[tuple[str, str]],
) -> str:
    """Markdown for a Feishu board / bitable / sheet / mindnote share captured from the web viewer."""
    meta = PREVIEW_META.get(kind) or PREVIEW_META["base"]
    type_line = meta["type_line"]
    default_h = meta["heading"]
    lines = [
        f"> 来源: {source_url}",
        type_line,
        "",
        f"# {title}",
        "",
    ]
    for i, (rel, heading) in enumerate(pages, 1):
        lines.append(f"## {heading or f'{default_h} {i}'}")
        lines.append("")
        lines.append(f"![]({rel})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _screenshot_locator(page: Any, dest: Path, loc) -> bool:
    try:
        box = loc.bounding_box()
    except Exception:
        box = None
    try:
        if box and (box.get("width", 0) > 2400 or box.get("height", 0) > 2400):
            vp = page.viewport_size or {"width": 1400, "height": 900}
            clip = {
                "x": max(0, int(box["x"])),
                "y": max(0, int(box["y"])),
                "width": min(int(box["width"]), int(vp["width"])),
                "height": min(int(box["height"]), int(vp["height"])),
            }
            if clip["width"] < 80 or clip["height"] < 80:
                return False
            page.screenshot(path=str(dest), clip=clip)
        else:
            loc.screenshot(path=str(dest))
    except Exception:
        return False
    return dest.is_file() and dest.stat().st_size >= 500


def screenshot_feishu_block(page: Any, block_id: str, dest: Path) -> bool:
    for sel in (
        f'[data-block-id="{block_id}"]',
        f'[data-record-id="{block_id}"]',
    ):
        loc = page.locator(sel).first
        try:
            if loc.count() == 0:
                continue
        except Exception:
            continue
        if _screenshot_locator(page, dest, loc):
            return True
    return False


def capture_feishu_preview_pages(
    page: Any, assets_dir: Path, *, kind: str
) -> list[tuple[Path, str]]:
    """Screenshot the visible Feishu board / bitable / sheet / mindnote viewer."""
    try:
        page.set_viewport_size({"width": 1400, "height": 900})
    except Exception:
        pass
    meta = PREVIEW_META.get(kind)
    if not meta:
        return []
    sel = meta["sel"]
    try:
        page.wait_for_selector(sel, timeout=20000)
    except Exception:
        return []
    _dismiss_feishu_guides(page)
    page.wait_for_timeout(600)
    assets_dir.mkdir(parents=True, exist_ok=True)
    sess.clear_generated_assets(assets_dir, patterns=("page_*.png",))
    loc = None
    for candidate in (sel + ", #mainBox").split(","):
        cand = page.locator(candidate.strip()).first
        try:
            if cand.count() == 0:
                continue
            box = cand.bounding_box()
        except Exception:
            continue
        if box and box.get("width", 0) >= 80 and box.get("height", 0) >= 80:
            loc = cand
            break
    dest = assets_dir / "page_001.png"
    if loc is None:
        try:
            page.screenshot(path=str(dest))
        except Exception:
            return []
    elif not _screenshot_locator(page, dest, loc):
        dest.unlink(missing_ok=True)
        return []
    if not dest.is_file() or dest.stat().st_size < 500:
        dest.unlink(missing_ok=True)
        return []
    heading = meta["heading"]
    return [(dest, heading)]


def write_feishu_preview_markdown(
    *,
    title: str,
    source_url: str,
    output_md: Path,
    page_files: list[Path],
    kind: str,
    headings: list[str] | None = None,
) -> dict[str, Any]:
    assets_dir = page_files[0].parent if page_files else output_md.parent
    pages: list[tuple[str, str]] = []
    for i, img in enumerate(page_files):
        rel = f"{assets_dir.name}/{img.name}"
        heading = ""
        if headings and i < len(headings):
            heading = str(headings[i] or "").strip()
        pages.append((rel, heading))
    md = build_feishu_preview_markdown(
        title=title, source_url=source_url, kind=kind, pages=pages
    )
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(md, encoding="utf-8")
    return {
        "pages": len(page_files),
        "markdown_chars": len(md),
        "assets_dir": str(assets_dir),
    }


def _iter_children(block: dict[str, Any]) -> list[dict[str, Any]]:
    synced = block.get("synced_children")
    if isinstance(synced, list) and synced:
        return synced
    children = block.get("children")
    if isinstance(children, list):
        return children
    return []


def _clean_text(text: str, keep_newline: bool = False) -> str:
    if text is None:
        return ""
    text = str(text)
    if keep_newline:
        return text.rstrip()
    return text.replace("\r", "").replace("\n", " ").strip()


def effective_block_type(block: dict[str, Any]) -> str:
    """Use snapshot.type when PageMain still exposes the block as fallback."""
    t = str(block.get("type") or "")
    if t == "fallback":
        snap = block.get("snapshot") or {}
        return str(snap.get("type") or "fallback")
    return t


def resolve_code_language(raw: Any) -> str:
    """Map Feishu CodeLanguage enum / name to a Markdown fence tag."""
    if raw is None or isinstance(raw, bool):
        return ""
    if isinstance(raw, int):
        return CODE_LANGUAGE_ENUM.get(raw, "")
    if isinstance(raw, float) and raw.is_integer():
        return CODE_LANGUAGE_ENUM.get(int(raw), "")
    text = str(raw).strip()
    if not text:
        return ""
    if text.isdigit():
        return CODE_LANGUAGE_ENUM.get(int(text), "")
    lowered = text.lower().replace("c++", "cpp").replace("c#", "csharp")
    compact = re.sub(r"[\s_-]+", "", lowered)
    aliases = {
        "plaintext": "",
        "js": "javascript",
        "ts": "typescript",
        "py": "python",
        "sh": "bash",
        "shell": "shell",
        "objective": "objectivec",
        "objectivec": "objectivec",
        "htmlbars": "handlebars",
        "handlebars": "handlebars",
        "openglshadinglanguage": "glsl",
        "glsl": "glsl",
        "openedgeabl": "abl",
        "visual": "vb",
        "visualbasic": "vb",
    }
    if compact in aliases:
        return aliases[compact]
    if compact in {tag for tag in CODE_LANGUAGE_ENUM.values() if tag}:
        return compact
    if re.fullmatch(r"[A-Za-z][\w+#.-]*", lowered):
        return lowered
    return ""


def _escape_markdown(text: str) -> str:
    """Escape Markdown inline metacharacters without mangling URLs/CJK prose."""
    if not text:
        return ""
    return re.sub(r"([\\`*_{}\[\]|])", r"\\\1", text)


def _zone_all_text(block: dict[str, Any]) -> str:
    zone = block.get("zone_state") or {}
    return zone.get("all_text") or ""


def _normalize_ops(ops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for op in ops:
        insert = op.get("insert") or ""
        attributes = dict(op.get("attributes") or {})
        if attributes.get("fixEnter") is not None:
            continue
        if not attributes and insert == "\n":
            continue
        inline_component = attributes.get("inline-component")
        if inline_component:
            try:
                component = json.loads(inline_component)
            except (json.JSONDecodeError, TypeError):
                component = None
            if isinstance(component, dict):
                ctype = component.get("type")
                data = component.get("data") or {}
                if ctype == "mention_doc":
                    attributes["link"] = data.get("raw_url") or attributes.get("link")
                    insert = f"{insert}{data.get('title') or ''}"
                elif ctype == "user":
                    attributes["mentionUserId"] = data.get("uid") or ""
                    insert = insert or "@mention"
        normalized.append({"insert": insert, "attributes": attributes})
    return normalized


def _render_inline_piece(insert: str, attributes: dict[str, Any]) -> str:
    if attributes.get("mentionUserId") and not insert:
        insert = "@mention"
    equation = _clean_text(attributes.get("equation") or "", keep_newline=True)
    if equation:
        return f"${equation}$"
    if attributes.get("inlineCode") is not None:
        if "`" in insert:
            return "`` " + insert + " ``"
        return "`" + insert + "`"
    text = _escape_markdown(insert).replace("\n", "  \n")
    if attributes.get("underline") is not None and text:
        text = f"<u>{text}</u>"
    if attributes.get("strikethrough") is not None and text:
        text = f"~~{text}~~"
    if attributes.get("italic") is not None and text:
        text = f"*{text}*"
    if attributes.get("bold") is not None and text:
        text = f"**{text}**"
    link = attributes.get("link")
    if link:
        label = text or _escape_markdown(unquote(str(link)))
        text = f"[{label}]({unquote(str(link))})"
    return text


def _render_inline_ops(block: dict[str, Any]) -> str:
    ops = (((block.get("zone_state") or {}).get("content") or {}).get("ops") or [])
    pieces = [
        _render_inline_piece(op.get("insert") or "", op.get("attributes") or {})
        for op in _normalize_ops(ops)
    ]
    return _clean_text("".join(p for p in pieces if p), keep_newline=True)


def _asset_placeholder(block: dict[str, Any]) -> str:
    kind = effective_block_type(block) or "asset"
    bid = block.get("id") or "unknown"
    return ASSET_PLACEHOLDER.format(kind=kind, block_id=bid)


def disable_embed_autoplay(url: str) -> str:
    """Force common video embeds not to autoplay (Bilibili / YouTube / etc.)."""
    url = (url or "").strip()
    if not url:
        return url
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not any(
        h in host
        for h in (
            "bilibili.com",
            "youtube.com",
            "youtu.be",
            "youtube-nocookie.com",
            "v.qq.com",
            "youku.com",
        )
    ):
        return url
    pairs = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k.lower() != "autoplay"]
    pairs.append(("autoplay", "0"))
    # Bilibili also respects muted autoplay quirks; keep explicit mute off
    if "bilibili.com" in host:
        pairs = [(k, v) for k, v in pairs if k.lower() not in {"autoplay", "muted"}]
        pairs.append(("autoplay", "0"))
        pairs.append(("muted", "0"))
    return urlunparse(parsed._replace(query=urlencode(pairs)))


def render_iframe_markdown(
    url: str,
    *,
    height: int | None = None,
    indent: int = 0,
) -> str:
    """Embed as sized iframe + plain link; no autoplay; readable fallback."""
    url = disable_embed_autoplay(url.strip())
    if not url:
        return ""
    h = height if isinstance(height, int) and 120 <= height <= 2000 else 450
    pad = " " * indent
    # width+height avoid collapsed strips in MD previewers; allowfullscreen for normal playback
    iframe = (
        f'{pad}<iframe src="{url}" width="100%" height="{h}" '
        f'style="max-width:100%;aspect-ratio:16/9;border:0;" '
        f'allowfullscreen loading="lazy" referrerpolicy="no-referrer-when-downgrade">'
        f"</iframe>"
    )
    link = f"{pad}[打开视频]({url})"
    return f"{iframe}\n\n{link}"


def _render_asset_block(block: dict[str, Any], indent: int = 0) -> str:
    block_type = effective_block_type(block)
    url = _asset_placeholder(block)
    if block_type == "file":
        name = _clean_text(((block.get("snapshot") or {}).get("file") or {}).get("name") or "附件")
        return f"{' ' * indent}[{name}]({url})".rstrip()
    alt = ""
    if block_type == "image":
        alt = _clean_text(((block.get("snapshot") or {}).get("image") or {}).get("caption") or "")
    elif block_type == "whiteboard":
        alt = _clean_text(
            ((block.get("snapshot") or {}).get("whiteboard") or {}).get("caption") or "whiteboard"
        )
    elif block_type == "board":
        alt = "画板"
    elif block_type == "bitable":
        alt = "多维表格"
    elif block_type == "sheet":
        alt = "电子表格"
    elif block_type == "mindnote":
        alt = "思维笔记"
    elif block_type == "diagram":
        alt = "diagram"
    return f"{' ' * indent}![{alt}]({url})".rstrip()


def _table_line(cells: list[str], indent: int = 0) -> str:
    normalized = [c.replace("\n", "<br>").strip() for c in cells]
    return f"{' ' * indent}| " + " | ".join(normalized) + " |"


def _extract_plain_text(block: dict[str, Any]) -> str:
    block_type = effective_block_type(block)
    text_types = {
        "text",
        "heading1",
        "heading2",
        "heading3",
        "heading4",
        "heading5",
        "heading6",
        "heading7",
        "heading8",
        "heading9",
        "bullet",
        "ordered",
        "todo",
    }
    if block_type in text_types:
        content = _render_inline_ops(block)
        child_texts = [_extract_plain_text(c) for c in _iter_children(block)]
        child_texts = [t for t in child_texts if t]
        if child_texts:
            return "\n".join([content] + child_texts if content else child_texts)
        return content
    if block_type == "table_cell":
        texts = [_extract_plain_text(c) for c in _iter_children(block)]
        return "<br>".join(t for t in texts if t)
    if block_type in {"image", "whiteboard", "diagram", "board", "bitable", "sheet", "mindnote"}:
        return _clean_text(_render_asset_block(block))
    if block_type == "file":
        return _clean_text(((block.get("snapshot") or {}).get("file") or {}).get("name") or "附件")
    texts = [_extract_plain_text(c) for c in _iter_children(block)]
    return "\n".join(t for t in texts if t)


def _render_table(block: dict[str, Any], indent: int = 0) -> str:
    columns = ((block.get("snapshot") or {}).get("columns_id") or [])
    column_count = len(columns)
    if column_count <= 0:
        return _render_blocks(_iter_children(block), indent)
    rows: list[list[str]] = []
    current: list[str] = []
    for cell in _iter_children(block):
        current.append(_extract_plain_text(cell))
        if len(current) == column_count:
            rows.append(current)
            current = []
    if current:
        current.extend([""] * (column_count - len(current)))
        rows.append(current)
    if not rows:
        return ""
    header = rows[0]
    body = rows[1:] if len(rows) > 1 else []
    lines = [_table_line(header, indent), _table_line(["---"] * column_count, indent)]
    lines.extend(_table_line(row, indent) for row in body)
    return "\n".join(lines)


def _render_list_item(block: dict[str, Any], indent: int = 0) -> str:
    block_type = effective_block_type(block)
    content = _render_inline_ops(block)
    marker = "- "
    if block_type == "ordered":
        seq = str(((block.get("snapshot") or {}).get("seq") or "1")).strip() or "1"
        marker = f"{seq}. " if seq.isdigit() else "1. "
    elif block_type == "todo":
        done = bool((block.get("snapshot") or {}).get("done"))
        marker = "- [x] " if done else "- [ ] "
    first = f"{' ' * indent}{marker}{content}".rstrip()
    if not content:
        first = f"{' ' * indent}{marker.rstrip()}"
    child = _render_blocks(_iter_children(block), indent + 4)
    if child:
        return f"{first}\n{child}"
    return first


def _render_isv(block: dict[str, Any], indent: int = 0) -> str:
    snapshot = block.get("snapshot") or {}
    block_type_id = snapshot.get("block_type_id") or ""
    raw = snapshot.get("data")
    mermaid_src = ""
    data: dict[str, Any]
    if isinstance(raw, str):
        mermaid_src = raw
        data = {}
    elif isinstance(raw, dict):
        data = raw
    else:
        data = {}
    # Mermaid ISV
    if block_type_id == "blk_631fefbbae02400430b8f9f4":
        mermaid = _clean_text(mermaid_src or data.get("data") or "", keep_newline=True)
        if mermaid:
            return f"{' ' * indent}```mermaid\n{mermaid}\n{' ' * indent}```"
    return f"{' ' * indent}<!-- unsupported feishu block: isv {block_type_id} -->"


def _render_block(block: dict[str, Any], indent: int = 0) -> str:
    block_type = effective_block_type(block)

    if block_type == "divider":
        return " " * indent + "---"

    if block_type.startswith("heading") and block_type[-1:].isdigit():
        level = int(block_type[-1])
        if 1 <= level <= 6:
            content = _render_inline_ops(block)
            first = f"{' ' * indent}{'#' * level} {content}".rstrip()
            child = _render_blocks(_iter_children(block), indent)
            if child and first:
                return f"{first}\n\n{child}"
            return first or child

    if block_type in {"text", "heading7", "heading8", "heading9"}:
        content = _render_inline_ops(block)
        first = (" " * indent + content) if content else ""
        child = _render_blocks(_iter_children(block), indent)
        if child and first:
            return f"{first}\n\n{child}"
        return first or child

    if block_type == "code":
        language = resolve_code_language((block.get("snapshot") or {}).get("language"))
        code = _clean_text(_zone_all_text(block), keep_newline=True)
        if not code:
            code = _clean_text(_render_inline_ops(block), keep_newline=True)
        if not code:
            return ""
        return f"{' ' * indent}```{language}\n{code}\n{' ' * indent}```"

    if block_type in {"quote_container", "callout", "quote"}:
        parts: list[str] = []
        own = _render_inline_ops(block)
        if own:
            parts.append(own)
        child_content = _render_blocks(_iter_children(block), indent=0)
        if child_content:
            parts.append(child_content)
        if not parts:
            return ""
        content = "\n\n".join(p for p in parts if p.strip())
        return "\n".join(
            f"{' ' * indent}> {line}" if line else f"{' ' * indent}>"
            for line in content.splitlines()
        )

    if block_type == "table":
        return _render_table(block, indent)

    if block_type == "grid":
        return _render_blocks(_iter_children(block), indent)

    if block_type in ASSET_BLOCK_TYPES:
        return _render_asset_block(block, indent)

    if block_type == "iframe":
        iframe = ((block.get("snapshot") or {}).get("iframe") or {})
        url = ((iframe.get("component") or {}).get("url") or "").strip()
        if not url:
            return ""
        height = iframe.get("height")
        try:
            height_i = int(height) if height is not None else None
        except (TypeError, ValueError):
            height_i = None
        return render_iframe_markdown(url, height=height_i, indent=indent)

    if block_type == "bookmark":
        snapshot = block.get("snapshot") or {}
        url = str(snapshot.get("url") or "").strip()
        title = _clean_text(snapshot.get("title") or "") or url or "书签"
        if url:
            return f"{' ' * indent}[{title}]({url})"
        return f"{' ' * indent}<!-- skipped feishu block: bookmark -->"

    if block_type == "isv":
        return _render_isv(block, indent)

    if block_type in {
        "chat_card",
        "poll",
    }:
        return f"{' ' * indent}<!-- skipped feishu block: {block_type} -->"

    if block_type in {
        "synced_source",
        "synced_reference",
        "grid_column",
        "table_cell",
        "page",
        "view",
    }:
        return _render_blocks(_iter_children(block), indent)

    # Unknown containers: try children
    return _render_blocks(_iter_children(block), indent)


def _render_blocks(blocks: list[dict[str, Any]], indent: int = 0) -> str:
    list_types = {"bullet", "ordered", "todo"}
    sections: list[str] = []
    index = 0
    while index < len(blocks):
        block = blocks[index]
        block_type = effective_block_type(block)
        if block_type in list_types:
            lines: list[str] = []
            while index < len(blocks) and effective_block_type(blocks[index]) in list_types:
                rendered = _render_list_item(blocks[index], indent)
                if rendered:
                    lines.append(rendered)
                index += 1
            if lines:
                sections.append("\n".join(lines))
            continue
        rendered = _render_block(block, indent)
        if rendered:
            sections.append(rendered)
        index += 1
    return "\n\n".join(s for s in sections if s.strip())


def blocks_to_markdown(
    model: dict[str, Any],
    *,
    source_url: str | None = None,
    doc_kind: str | None = None,
) -> str:
    """Convert serialized {title, root} model to Markdown text."""
    title = _clean_text(model.get("title") or "untitled") or "untitled"
    root = model.get("root") or {}
    body = _render_blocks(_iter_children(root) if root else [])
    lines: list[str] = []
    if source_url:
        kind_note = doc_kind or "feishu"
        lines.append(f"> 来源: {source_url}")
        lines.append(f"> 类型: 飞书文档 ({kind_note})")
        lines.append("")
    lines.append(f"# {title}")
    if body:
        lines.append("")
        lines.append(body)
    return "\n".join(lines).rstrip() + "\n"


def collect_assets(block: dict[str, Any]) -> list[dict[str, str]]:
    assets: list[dict[str, str]] = []
    block_type = effective_block_type(block)
    block_id = block.get("id")
    if block_type in ASSET_BLOCK_TYPES and block_id is not None:
        assets.append(
            {
                "asset_type": block_type,
                "block_id": str(block_id),
                "placeholder": ASSET_PLACEHOLDER.format(kind=block_type, block_id=block_id),
            }
        )
    for child in _iter_children(block):
        assets.extend(collect_assets(child))
    return assets


def _ext_from_name(name: str, default: str = ".png") -> str:
    suffix = Path(name).suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".pdf", ".bin"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return default


ASSET_PLACEHOLDER_RE = re.compile(r"feishu-asset://[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/")


def rewrite_asset_placeholders(markdown: str, mapping: dict[str, str]) -> str:
    """Replace placeholders with local paths without prefix collisions.

    Longer placeholders first so a short id never eats into a longer one
    (defense in depth; placeholders also end with `/`). Unmapped placeholders
    become HTML comments instead of leftover feishu-asset:// links.
    """
    rewritten = markdown
    for placeholder, rel in sorted(mapping.items(), key=lambda kv: len(kv[0]), reverse=True):
        rewritten = rewritten.replace(placeholder, rel)

    def leftover(match: re.Match[str]) -> str:
        body = match.group(0)[len("feishu-asset://") :].rstrip("/")
        return f"<!-- feishu asset not downloaded: {body} -->"

    return ASSET_PLACEHOLDER_RE.sub(leftover, rewritten)


def download_assets(page: Any, model: dict[str, Any], assets_dir: Path, markdown: str) -> tuple[str, int]:
    """Download assets via page.evaluate; rewrite placeholders. Returns (md, count)."""
    root = model.get("root") or {}
    assets = collect_assets(root)
    if not assets:
        return markdown, 0
    assets_dir.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, str] = {}
    saved = 0
    for index, asset in enumerate(assets, 1):
        try:
            payload = page.evaluate(DOWNLOAD_ASSET_JS, asset)
        except Exception as e:
            print(f"WARN asset {asset['block_id']}: {e}", file=sys.stderr)
            payload = None
        if not payload or not payload.get("base64"):
            dest = assets_dir / f"image_{index:03d}.png"
            if asset["asset_type"] in EMBED_SCREENSHOT_TYPES and screenshot_feishu_block(
                page, str(asset["block_id"]), dest
            ):
                mapping[asset["placeholder"]] = f"{assets_dir.name}/{dest.name}"
                saved += 1
            continue
        raw_name = str(payload.get("file_name") or f"{asset['asset_type']}-{asset['block_id']}.png")
        ext = _ext_from_name(raw_name)
        # Stable document-order names (avoids colliding image.png renames)
        filename = f"image_{index:03d}{ext}"
        dest = assets_dir / filename
        dest.write_bytes(base64.b64decode(str(payload["base64"]).encode("utf-8")))
        mapping[asset["placeholder"]] = f"{assets_dir.name}/{filename}"
        saved += 1
    return rewrite_asset_placeholders(markdown, mapping), saved


def _page_looks_rate_limited(page: Any) -> bool:
    try:
        title = page.title() or ""
        body = page.inner_text("body") if page.query_selector("body") else ""
    except Exception:
        return False
    return "访问人数过多" in title or "访问人数过多" in (body or "")[:500]


def _page_needs_login(page: Any) -> bool:
    url = (page.url or "").lower()
    if any(h in url for h in ("accounts.feishu.cn", "accounts.larksuite.com", "/accounts/page/login")):
        return True
    try:
        text = page.inner_text("body") if page.query_selector("body") else ""
    except Exception:
        text = ""
    return any(x in (text or "")[:800] for x in ("登录后即可查看", "请登录", "扫码登录", "Sign in"))


def extract_model_from_page(
    page: Any,
    *,
    timeout_ms: int = 60000,
    scroll_rounds: int = 80,
    scroll_wait_ms: int = 350,
) -> dict[str, Any]:
    page.wait_for_function(
        "() => Boolean(window.PageMain || window.editor)",
        timeout=timeout_ms,
    )
    if page.evaluate("() => Boolean(window.editor && !window.PageMain)"):
        raise FeishuError("旧版 /docs/ 文档暂不支持；请在飞书中升级为新版文档后重试")

    ready = False
    if page.evaluate(WAIT_PAGE_READY_JS):
        ready = True
    else:
        top = 0
        for _ in range(scroll_rounds):
            page.evaluate(
                """
                (nextTop) => {
                  const container = document.querySelector('#mainBox .bear-web-x-container');
                  if (container) {
                    container.scrollTo({ top: nextTop, behavior: 'instant' });
                  }
                }
                """,
                top,
            )
            page.wait_for_timeout(scroll_wait_ms)
            if page.evaluate(WAIT_PAGE_READY_JS):
                ready = True
                break
            top = page.evaluate(
                """
                () => {
                  const container = document.querySelector('#mainBox .bear-web-x-container');
                  return container ? container.scrollHeight : 0;
                }
                """
            )

    if not ready:
        # Soft fail: still try to serialize whatever is loaded
        print("WARN: some blocks may still be pending; exporting partial tree", file=sys.stderr)

    payload = page.evaluate(SERIALIZE_BLOCK_TREE_JS)
    if not payload or not payload.get("root"):
        raise FeishuError("未能从页面提取飞书文档块树（PageMain 不可用）")
    return payload


def share_to_markdown(
    url: str,
    output_md: Path,
    *,
    storage_state: Path | None = None,
    headless: bool = True,
    timeout_ms: int = 60000,
    retries: int = 3,
    auto_login: bool = True,
    _login_retried: bool = False,
    insecure: bool = False,
    keep_work: bool = False,
) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    info = parse_feishu_url(url)
    url = info["url"]
    state_path = storage_state or DEFAULT_STATE
    sess.ensure_config_dir()
    if state_path.is_file():
        sess.tighten_file(state_path)
    if info["kind"] == "docs":
        print(
            "WARN: legacy /docs/ URLs often need upgrade; will try PageMain if available",
            file=sys.stderr,
        )

    last_err: Exception | None = None
    relogin = False
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=headless)
        context_kwargs: dict[str, Any] = {}
        if insecure:
            print(
                "WARN: --insecure disables HTTPS certificate checks",
                file=sys.stderr,
            )
            context_kwargs["ignore_https_errors"] = True
        if state_path.is_file():
            context_kwargs["storage_state"] = str(state_path)
        context = browser.new_context(**context_kwargs)
        page = context.new_page()

        for attempt in range(1, retries + 1):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(1500)
                if _page_looks_rate_limited(page):
                    wait_s = min(10 * attempt, 30)
                    print(
                        f"WARN rate-limited (attempt {attempt}/{retries}), sleep {wait_s}s",
                        file=sys.stderr,
                    )
                    time.sleep(wait_s)
                    last_err = FeishuError("飞书限流：页面访问人数过多，请稍后重试")
                    continue
                if _page_needs_login(page):
                    last_err = FeishuError(
                        f"需要登录。请先运行: "
                        f"python {Path(__file__).name.replace('feishu_to_md.py', 'feishu_login.py')} '{url}'"
                    )
                    relogin = auto_login and not _login_retried
                    break

                page.wait_for_timeout(1500)
                _dismiss_feishu_guides(page)
                has_pagemain = False
                try:
                    has_pagemain = bool(
                        page.evaluate(
                            "() => Boolean(window.PageMain?.blockManager?.rootBlockModel)"
                        )
                    )
                except Exception:
                    has_pagemain = False
                preview_kind = ""
                if info["kind"] in PREVIEW_META:
                    preview_kind = info["kind"]
                elif not has_pagemain:
                    if _page_looks_like_board(page):
                        preview_kind = "board"
                    elif _page_looks_like_bitable(page):
                        preview_kind = "base"
                    elif _page_looks_like_sheet(page):
                        preview_kind = "sheet"
                    elif _page_looks_like_mindnote(page):
                        preview_kind = "mindnote"
                if preview_kind:
                    title = _clean_text(page.title() or "") or info["token"]
                    stem = safe_stem(title.split(" - ")[0] if title else info["token"])
                    if output_md.suffix.lower() != ".md":
                        output_md = output_md.with_suffix(".md")
                    if output_md.name in {"out.md", "output.md"} or output_md.stem == "feishu_out":
                        output_md = output_md.with_name(f"{stem}.md")
                    assets_dir = output_md.parent / f"{output_md.stem}_assets"
                    captured = capture_feishu_preview_pages(
                        page, assets_dir, kind=preview_kind
                    )
                    if not captured:
                        raise FeishuError(
                            "Could not capture the Feishu viewer. "
                            "Re-run feishu_login.py, or export an image from the Feishu UI."
                        )
                    stats = write_feishu_preview_markdown(
                        title=stem,
                        source_url=url,
                        output_md=output_md,
                        page_files=[p for p, _ in captured],
                        kind=preview_kind,
                        headings=[name for _, name in captured],
                    )
                    result = {
                        "ok": True,
                        "url": url,
                        "kind": info["kind"],
                        "mode": (PREVIEW_META.get(preview_kind) or {}).get(
                            "mode", f"{preview_kind}-preview"
                        ),
                        "token": info["token"],
                        "title": title,
                        "output": str(output_md),
                        "assets_dir": stats.get("assets_dir"),
                        "images_saved": stats.get("pages"),
                        "markdown_chars": stats.get("markdown_chars"),
                        "storage_state": str(state_path) if state_path.is_file() else None,
                    }
                    browser.close()
                    return result

                model = extract_model_from_page(page, timeout_ms=timeout_ms)
                title = _clean_text(model.get("title") or "") or info["token"]
                stem = safe_stem(title)
                if output_md.suffix.lower() != ".md":
                    output_md = output_md.with_suffix(".md")
                # If user passed a directory-like default, keep stem from title
                if output_md.name in {"out.md", "output.md"} or output_md.stem == "feishu_out":
                    output_md = output_md.with_name(f"{stem}.md")

                output_md.parent.mkdir(parents=True, exist_ok=True)
                assets_dir = output_md.parent / f"{output_md.stem}_assets"

                md = blocks_to_markdown(model, source_url=url, doc_kind=info["kind"])
                md, images_saved = download_assets(page, model, assets_dir, md)
                output_md.write_text(md, encoding="utf-8")

                result = {
                    "ok": True,
                    "url": url,
                    "kind": info["kind"],
                    "token": info["token"],
                    "title": title,
                    "output": str(output_md),
                    "assets_dir": str(assets_dir) if images_saved else None,
                    "images_saved": images_saved,
                    "markdown_chars": len(md),
                    "storage_state": str(state_path) if state_path.is_file() else None,
                }
                if keep_work:
                    work = sess.make_work_dir(
                        f"feishu_{info['token']}", keep=True, beside=output_md
                    )
                    (work / f"{stem}.blocks.json").write_text(
                        json.dumps(model, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    result["work_dir"] = str(work)

                browser.close()
                return result
            except FeishuError as e:
                last_err = e
                if is_login_error(e) or "旧版" in str(e):
                    relogin = auto_login and not _login_retried and is_login_error(e)
                    break
                print(f"WARN attempt {attempt}: {e}", file=sys.stderr)
                time.sleep(2 * attempt)
            except Exception as e:
                last_err = e
                print(f"WARN attempt {attempt}: {e}", file=sys.stderr)
                time.sleep(2 * attempt)

        browser.close()

    if relogin:
        interactive_feishu_login(url)
        return share_to_markdown(
            url,
            output_md,
            storage_state=storage_state,
            headless=headless,
            timeout_ms=timeout_ms,
            retries=retries,
            auto_login=auto_login,
            _login_retried=True,
            insecure=insecure,
            keep_work=keep_work,
        )
    raise FeishuError(str(last_err) if last_err else "conversion failed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert Feishu/Lark wiki/docx URL to Markdown.")
    parser.add_argument("url", help="Feishu wiki or docx URL")
    parser.add_argument("-o", "--output", type=Path, default=None, help="Output .md path")
    parser.add_argument(
        "--storage-state",
        type=Path,
        default=DEFAULT_STATE,
        help="Playwright storage state JSON",
    )
    parser.add_argument("--headed", action="store_true", help="Show browser window")
    parser.add_argument("--timeout-ms", type=int, default=60000)
    parser.add_argument(
        "--no-login",
        action="store_true",
        help="Do not open Chrome if the Feishu session is missing or expired",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable HTTPS certificate checks (enterprise MITM/proxy only)",
    )
    parser.add_argument(
        "--keep-work",
        action="store_true",
        help="Keep .doc2md_work_* next to the Markdown (blocks JSON dump). Default: do not write it.",
    )
    args = parser.parse_args(argv)

    url = normalize_url(args.url)
    try:
        info = parse_feishu_url(url)
    except FeishuError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    out = args.output
    if out is None:
        out = Path.cwd() / f"feishu_{info['token']}.md"

    try:
        result = share_to_markdown(
            url,
            out,
            storage_state=args.storage_state,
            headless=not args.headed,
            timeout_ms=args.timeout_ms,
            auto_login=not args.no_login,
            insecure=args.insecure,
            keep_work=args.keep_work,
        )
    except FeishuError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print("OK")
    for k, v in result.items():
        if k == "ok":
            continue
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
