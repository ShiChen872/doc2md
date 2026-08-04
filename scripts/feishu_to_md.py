#!/usr/bin/env python3
"""Convert a Feishu/Lark wiki or docx URL to Markdown (+ local images).

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

CFG = Path.home() / ".config" / "doc2md"
DEFAULT_STATE = CFG / "feishu_storage_state.json"
SAFE_NAME_RE = re.compile(r"[^\w.\u4e00-\u9fff\-]+")

# Hosts we accept for Feishu / Lark docs
HOST_RE = re.compile(
    r"(?:^|\.)(?:feishu\.cn|larksuite\.com|larkoffice\.com)$",
    re.IGNORECASE,
)
# /wiki/TOKEN or /docx/TOKEN or legacy /docs/TOKEN
PATH_RE = re.compile(
    r"/(wiki|docx|docs)/([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)

# Trailing slash prevents naive replace of id "7" from mangling "73" / "76".
ASSET_PLACEHOLDER = "feishu-asset://{kind}/{block_id}/"

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

  const simplifySnapshot = (block) => {
    const snapshot = block?.snapshot ?? {};
    const base = { type: snapshot.type ?? block?.type ?? '' };

    switch (block?.type) {
      case 'ordered':
        return { ...base, seq: snapshot.seq ?? '' };
      case 'todo':
        return { ...base, done: Boolean(snapshot.done) };
      case 'code':
        return {
          ...base,
          language: snapshot.language ?? snapshot.lang ?? '',
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
      case 'diagram':
        return { ...base, diagram: {} };
      case 'isv':
        return {
          ...base,
          block_type_id: snapshot.block_type_id ?? '',
          data: safeJson(snapshot.data),
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
      type: block.type ?? block?.snapshot?.type ?? '',
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
  const root = window.PageMain.blockManager.rootBlockModel;
  const children = Array.isArray(root.children) ? root.children : [];
  return children.every((block) => {
    const snapshotType = block?.snapshot?.type;
    const blockType = block?.type;
    const ready = snapshotType !== 'pending';
    const syncedReady = blockType !== 'synced_reference' || block?.isAllDataReady;
    const whiteboardReady = blockType !== 'fallback' || snapshotType !== 'whiteboard';
    return ready && syncedReady && whiteboardReady;
  });
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


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url.startswith("http"):
        url = "https://" + url
    return url


def safe_stem(name: str) -> str:
    base = Path(name).stem or name
    return SAFE_NAME_RE.sub("_", base).strip("._") or "feishu_document"


def parse_feishu_url(url: str) -> dict[str, str]:
    """Parse wiki/docx/docs URL → {kind, token, host, url}."""
    url = normalize_url(url)
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not host or not HOST_RE.search(host):
        raise FeishuError(f"Not a Feishu/Lark URL: {url}")
    m = PATH_RE.search(parsed.path or "")
    if not m:
        raise FeishuError(
            f"Cannot parse document token from URL (need /wiki/, /docx/, or /docs/): {url}"
        )
    kind = m.group(1).lower()
    token = m.group(2)
    if kind == "docs":
        # Legacy docs are limited; still return kind so caller can warn
        pass
    return {"kind": kind, "token": token, "host": host, "url": url}


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
        return f"`{insert.replace('`', '\\`')}`"
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
    kind = block.get("type") or "asset"
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
    block_type = block.get("type") or ""
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
    elif block_type == "diagram":
        alt = "diagram"
    return f"{' ' * indent}![{alt}]({url})".rstrip()


def _table_line(cells: list[str], indent: int = 0) -> str:
    normalized = [c.replace("\n", "<br>").strip() for c in cells]
    return f"{' ' * indent}| " + " | ".join(normalized) + " |"


def _extract_plain_text(block: dict[str, Any]) -> str:
    block_type = block.get("type") or ""
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
    if block_type in {"image", "whiteboard", "diagram"}:
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
    block_type = block.get("type") or ""
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
    data = snapshot.get("data") or {}
    # Mermaid ISV
    if block_type_id == "blk_631fefbbae02400430b8f9f4":
        mermaid = _clean_text((data or {}).get("data") or "", keep_newline=True)
        if mermaid:
            return f"{' ' * indent}```mermaid\n{mermaid}\n{' ' * indent}```"
    return f"{' ' * indent}<!-- unsupported feishu block: isv {block_type_id} -->"


def _render_block(block: dict[str, Any], indent: int = 0) -> str:
    block_type = block.get("type") or ""

    if block_type == "divider":
        return " " * indent + "---"

    if block_type.startswith("heading") and block_type[-1:].isdigit():
        level = int(block_type[-1])
        if 1 <= level <= 6:
            content = _render_inline_ops(block)
            return f"{' ' * indent}{'#' * level} {content}".rstrip()

    if block_type in {"text", "heading7", "heading8", "heading9"}:
        content = _render_inline_ops(block)
        return (" " * indent + content) if content else ""

    if block_type == "code":
        language = _clean_text(str((block.get("snapshot") or {}).get("language") or ""))
        # language may be a numeric enum; keep empty if not a word
        if language.isdigit():
            language = ""
        code = _clean_text(_zone_all_text(block), keep_newline=True)
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

    if block_type in {"image", "file", "whiteboard", "diagram"}:
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

    if block_type == "isv":
        return _render_isv(block, indent)

    if block_type in {
        "bitable",
        "sheet",
        "mindnote",
        "board",
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
        block_type = block.get("type")
        if block_type in list_types:
            lines: list[str] = []
            while index < len(blocks) and blocks[index].get("type") in list_types:
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
    block_type = block.get("type") or ""
    block_id = block.get("id")
    if block_type in {"image", "file", "whiteboard", "diagram"} and block_id is not None:
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


def rewrite_asset_placeholders(markdown: str, mapping: dict[str, str]) -> str:
    """Replace placeholders with local paths without prefix collisions.

    Longer placeholders first so a short id never eats into a longer one
    (defense in depth; placeholders also end with `/`).
    """
    rewritten = markdown
    for placeholder, rel in sorted(mapping.items(), key=lambda kv: len(kv[0]), reverse=True):
        rewritten = rewritten.replace(placeholder, rel)
    return rewritten


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
) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    info = parse_feishu_url(url)
    url = info["url"]
    state_path = storage_state or DEFAULT_STATE
    if info["kind"] == "docs":
        print(
            "WARN: legacy /docs/ URLs often need upgrade; will try PageMain if available",
            file=sys.stderr,
        )

    last_err: Exception | None = None
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=headless)
        context_kwargs: dict[str, Any] = {"ignore_https_errors": True}
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
                    raise FeishuError(
                        f"需要登录。请先运行: "
                        f"python {Path(__file__).name.replace('feishu_to_md.py', 'feishu_login.py')} '{url}'"
                    )

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

                # Dump raw model beside work for debugging (hidden)
                work = output_md.parent / f".doc2md_work_feishu_{info['token']}"
                work.mkdir(parents=True, exist_ok=True)
                (work / f"{stem}.blocks.json").write_text(
                    json.dumps(model, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

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
                browser.close()
                return result
            except FeishuError as e:
                last_err = e
                if "需要登录" in str(e) or "旧版" in str(e):
                    break
                print(f"WARN attempt {attempt}: {e}", file=sys.stderr)
                time.sleep(2 * attempt)
            except Exception as e:
                last_err = e
                print(f"WARN attempt {attempt}: {e}", file=sys.stderr)
                time.sleep(2 * attempt)

        browser.close()
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
