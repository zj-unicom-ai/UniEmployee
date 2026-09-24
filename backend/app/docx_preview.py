"""Render DOCX documents into a restricted, self-contained HTML preview."""
from __future__ import annotations

import base64
import html
import re
import zipfile
from pathlib import Path

from docx import Document
from docx.document import Document as DocumentObject
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

MAX_DOCX_SIZE = 30 * 1024 * 1024
MAX_UNPACKED_SIZE = 120 * 1024 * 1024
MAX_INLINE_IMAGES_SIZE = 15 * 1024 * 1024


def _check_package(path: Path) -> None:
    if path.stat().st_size > MAX_DOCX_SIZE:
        raise ValueError("文档超过 30 MB，暂不支持在线预览，请下载后查看")
    try:
        with zipfile.ZipFile(path) as package:
            if sum(entry.file_size for entry in package.infolist()) > MAX_UNPACKED_SIZE:
                raise ValueError("文档内容过大，暂不支持在线预览，请下载后查看")
    except ValueError:
        raise
    except zipfile.BadZipFile as exc:
        raise ValueError("文件不是有效的 DOCX 文档") from exc
    except Exception as exc:
        raise ValueError("文件不是有效的 DOCX 文档") from exc


def _iter_blocks(parent):
    element = parent._body._element if isinstance(parent, DocumentObject) else parent._tc
    for child in element.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, parent)
        elif child.tag == qn("w:tbl"):
            yield Table(child, parent)


def _run_html(run, image_budget: list[int]) -> str:
    text = html.escape(run.text or "").replace("\n", "<br>").replace("\t", "&emsp;")
    for blip in run._element.xpath(".//a:blip"):
        relationship_id = blip.get(qn("r:embed"))
        part = run.part.related_parts.get(relationship_id) if relationship_id else None
        if not part or image_budget[0] + len(part.blob) > MAX_INLINE_IMAGES_SIZE:
            continue
        image_budget[0] += len(part.blob)
        content_type = part.content_type
        if not re.fullmatch(r"image/[A-Za-z0-9.+-]+", content_type or ""):
            content_type = "image/png"
        encoded = base64.b64encode(part.blob).decode("ascii")
        text += f'<img class="docx-image" alt="" src="data:{content_type};base64,{encoded}">'

    font_size = run.font.size.pt if run.font.size else None
    styles = []
    if font_size and 5 <= font_size <= 96:
        styles.append(f"font-size:{font_size:g}pt")
    color = run.font.color.rgb if run.font.color and run.font.color.rgb else None
    if color and re.fullmatch(r"[0-9A-Fa-f]{6}", str(color)):
        styles.append(f"color:#{color}")
    if styles:
        text = f'<span style="{html.escape(";".join(styles), quote=True)}">{text}</span>'
    if run.font.underline:
        text = f"<u>{text}</u>"
    if run.italic:
        text = f"<em>{text}</em>"
    if run.bold:
        text = f"<strong>{text}</strong>"
    return text


def _paragraph_html(paragraph, image_budget: list[int]) -> str:
    content = "".join(_run_html(run, image_budget) for run in paragraph.runs)
    # Some generated documents store hyperlinks outside the paragraph's run list.
    if not content:
        content = html.escape(paragraph.text or "").replace("\n", "<br>").replace("\t", "&emsp;")
    if not content.strip():
        return '<p class="docx-empty">&nbsp;</p>'

    style_name = getattr(getattr(paragraph, "style", None), "name", "") or ""
    heading = re.search(r"(?:heading|标题)\s*([1-6])", style_name, re.IGNORECASE)
    if style_name.lower() == "title" or style_name in {"标题", "Title"}:
        tag, css_class = "h1", "docx-title"
    elif heading:
        tag, css_class = f"h{heading.group(1)}", ""
    elif "subtitle" in style_name.lower() or "副标题" in style_name:
        tag, css_class = "p", "docx-subtitle"
    else:
        tag, css_class = "p", ""

    p_pr = paragraph._p.pPr
    if p_pr is not None and p_pr.numPr is not None and tag == "p":
        css_class = (css_class + " docx-list-item").strip()

    alignment = paragraph.alignment
    align = {1: "center", 2: "right", 3: "justify"}.get(alignment, "")
    style = f' style="text-align:{align}"' if align else ""
    cls = f' class="{css_class}"' if css_class else ""
    return f"<{tag}{cls}{style}>{content}</{tag}>"


def _table_html(table, image_budget: list[int]) -> str:
    rows = []
    for row_index, row in enumerate(table.rows):
        cells = []
        for cell in row.cells:
            blocks = []
            for block in _iter_blocks(cell):
                if isinstance(block, Paragraph):
                    blocks.append(_paragraph_html(block, image_budget))
                elif isinstance(block, Table):
                    blocks.append(_table_html(block, image_budget))
            content = "".join(blocks) or "&nbsp;"
            tag = "th" if row_index == 0 else "td"
            cells.append(f"<{tag}>{content}</{tag}>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return '<div class="docx-table-wrap"><table class="docx-table">' + "".join(rows) + "</table></div>"


def render_docx_html(path: Path) -> str:
    """Convert the document's paragraphs, tables, basic formatting, and images."""
    _check_package(path)
    try:
        document = Document(path)
    except Exception as exc:
        raise ValueError("无法读取该 Word 文档，请下载后查看") from exc

    try:
        image_budget = [0]
        body = []
        for block in _iter_blocks(document):
            if isinstance(block, Paragraph):
                body.append(_paragraph_html(block, image_budget))
            elif isinstance(block, Table):
                body.append(_table_html(block, image_budget))
    except Exception as exc:
        raise ValueError("无法读取该 Word 文档，请下载后查看") from exc

    return """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline';">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
*{box-sizing:border-box}body{margin:0;padding:36px max(24px,calc((100vw - 860px)/2));color:#1f2937;background:#f3f5f8;font:15px/1.8 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}
.docx-page{min-height:calc(100vh - 72px);padding:44px clamp(24px,7vw,76px);background:#fff;box-shadow:0 2px 18px #1e293b12}
h1,h2,h3,h4,h5,h6{color:#172033;line-height:1.45;margin:1.5em 0 .7em}h1{font-size:26px}h2{font-size:22px}h3{font-size:19px}.docx-title{text-align:center;font-size:28px;font-weight:700;margin:0 0 24px}.docx-subtitle{color:#64748b;text-align:center;font-size:16px}
p{margin:.55em 0;white-space:pre-wrap;overflow-wrap:anywhere}.docx-empty{min-height:.8em}.docx-list-item{padding-left:1.5em;position:relative}.docx-list-item:before{content:"•";position:absolute;left:.45em;color:#4f6bed}
.docx-table-wrap{width:100%;overflow:auto;margin:18px 0}.docx-table{width:100%;border-collapse:collapse;font-size:13px;line-height:1.6}.docx-table th,.docx-table td{border:1px solid #d8dee8;padding:8px 10px;text-align:left;vertical-align:top}.docx-table th{background:#f1f5f9;font-weight:650}.docx-table p{margin:0}.docx-image{display:block;max-width:100%;height:auto;margin:12px auto}
@media(max-width:640px){body{padding:12px}.docx-page{padding:28px 18px}.docx-table{min-width:520px}}
</style></head><body><main class="docx-page">""" + "".join(body) + "</main></body></html>"
