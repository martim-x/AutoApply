"""ReportLab Platypus PDF renderer with KeepTogether + theme page breaks."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Any, BinaryIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.application.reports import ReportPayload, ReportTheme

_FONT_REG = "AAReport"
_FONT_BOLD = "AAReport-Bold"
_FONT_ITALIC = "AAReport-Italic"

_CANDIDATE_REGULAR = (
    Path(__file__).resolve().parent / "fonts" / "DejaVuSans.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    Path("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"),
    Path("/usr/share/fonts/TTF/DejaVuSans.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    Path("/Library/Fonts/Arial Unicode.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    Path("/Library/Fonts/Arial.ttf"),
)

_CANDIDATE_BOLD = (
    Path(__file__).resolve().parent / "fonts" / "DejaVuSans-Bold.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"),
    Path("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    Path("/Library/Fonts/Arial Bold.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    Path("/Library/Fonts/Arial Unicode.ttf"),
)

_CANDIDATE_ITALIC = (
    Path(__file__).resolve().parent / "fonts" / "DejaVuSans-Oblique.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf"),
    Path("/usr/share/fonts/TTF/DejaVuSans-Oblique.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Italic.ttf"),
    Path("/Library/Fonts/Arial Italic.ttf"),
)

_CATEGORY_HEX = {
    "HIGH": "#1a7a38",
    "MEDIUM": "#b8860b",
    "LOW": "#5a635c",
}
_CATEGORY_COLORS = {k: colors.HexColor(v) for k, v in _CATEGORY_HEX.items()}


@lru_cache(maxsize=1)
def _register_fonts() -> tuple[str, str, str]:
    regular = next((p for p in _CANDIDATE_REGULAR if p.is_file()), None)
    if regular is None:
        raise RuntimeError(
            "No Cyrillic-capable TTF found. Install fonts-dejavu-core "
            "or place DejaVuSans.ttf under app/infrastructure/reports/fonts/"
        )
    bold = next((p for p in _CANDIDATE_BOLD if p.is_file()), regular)
    italic = next((p for p in _CANDIDATE_ITALIC if p.is_file()), regular)
    pdfmetrics.registerFont(TTFont(_FONT_REG, str(regular)))
    pdfmetrics.registerFont(TTFont(_FONT_BOLD, str(bold)))
    pdfmetrics.registerFont(TTFont(_FONT_ITALIC, str(italic)))
    return _FONT_REG, _FONT_BOLD, _FONT_ITALIC


def _esc(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _styles() -> dict[str, ParagraphStyle]:
    font, font_bold, font_italic = _register_fonts()
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "AATitle",
            parent=base["Title"],
            fontName=font_bold,
            fontSize=16,
            leading=20,
            spaceAfter=8,
            alignment=TA_LEFT,
            textColor=colors.HexColor("#1a1a1a"),
        ),
        "theme": ParagraphStyle(
            "AATheme",
            parent=base["Heading1"],
            fontName=font_bold,
            fontSize=13,
            leading=17,
            spaceBefore=4,
            spaceAfter=8,
            textColor=colors.HexColor("#222222"),
        ),
        "block": ParagraphStyle(
            "AABlock",
            parent=base["Heading2"],
            fontName=font_bold,
            fontSize=11,
            leading=14,
            spaceBefore=2,
            spaceAfter=4,
            textColor=colors.HexColor("#333333"),
        ),
        "body": ParagraphStyle(
            "AABody",
            parent=base["Normal"],
            fontName=font,
            fontSize=9,
            leading=12,
            spaceAfter=2,
        ),
        "meta": ParagraphStyle(
            "AAMeta",
            parent=base["Normal"],
            fontName=font_italic,
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#555555"),
            spaceAfter=10,
        ),
        "cell": ParagraphStyle(
            "AACell",
            parent=base["Normal"],
            fontName=font,
            fontSize=8,
            leading=10,
        ),
        "cell_cat": ParagraphStyle(
            "AACellCat",
            parent=base["Normal"],
            fontName=font_bold,
            fontSize=8,
            leading=10,
        ),
        "footer": ParagraphStyle(
            "AAFooter",
            parent=base["Normal"],
            fontName=font,
            fontSize=8,
            leading=10,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#666666"),
        ),
    }


def _header_footer(canvas, doc, payload: ReportPayload) -> None:
    canvas.saveState()
    page = canvas.getPageNumber()
    header = f"{payload.app_name} · {payload.title}"
    footer = f"{payload.app_name}  ·  {payload.generated_label}  ·  стр. {page}"
    canvas.setStrokeColor(colors.HexColor("#cccccc"))
    canvas.setLineWidth(0.4)
    # top rule
    y_top = A4[1] - 12 * mm
    canvas.line(18 * mm, y_top, A4[0] - 18 * mm, y_top)
    canvas.setFont(_register_fonts()[0], 8)  # regular
    canvas.setFillColor(colors.HexColor("#666666"))
    canvas.drawString(18 * mm, y_top + 2 * mm, header[:90])
    # bottom
    y_bot = 12 * mm
    canvas.line(18 * mm, y_bot + 4 * mm, A4[0] - 18 * mm, y_bot + 4 * mm)
    canvas.drawCentredString(A4[0] / 2, y_bot, footer)
    canvas.restoreState()


def _kv_block(block: dict, styles: dict) -> KeepTogether:
    parts: list[Any] = [Paragraph(_esc(block.get("title") or ""), styles["block"])]
    rows = block.get("rows") or []
    data = []
    style_cmds: list[Any] = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#e6e6e6")),
    ]
    for idx, (k, v) in enumerate(rows):
        label = str(k)
        cat = label.upper()
        if cat in _CATEGORY_COLORS:
            data.append(
                [
                    Paragraph(f"<b>{_esc(label)}</b>", styles["cell_cat"]),
                    Paragraph(
                        f'<font color="{_CATEGORY_HEX[cat]}">'
                        f"<b>{_esc(str(v))}</b></font>",
                        styles["cell_cat"],
                    ),
                ]
            )
            style_cmds.append(
                ("TEXTCOLOR", (0, idx), (0, idx), _CATEGORY_COLORS[cat])
            )
        else:
            data.append(
                [
                    Paragraph(f"<b>{_esc(label)}</b>", styles["cell"]),
                    Paragraph(_esc(str(v)), styles["cell"]),
                ]
            )
    if not data:
        data = [[Paragraph("—", styles["cell"]), Paragraph("", styles["cell"])]]
    table = Table(data, colWidths=[45 * mm, 125 * mm])
    table.setStyle(TableStyle(style_cmds))
    parts.append(table)
    parts.append(Spacer(1, 4 * mm))
    return KeepTogether(parts)


def _bullets_block(block: dict, styles: dict) -> KeepTogether:
    parts: list[Any] = [Paragraph(_esc(block.get("title") or ""), styles["block"])]
    items: list[Any] = [
        ListItem(Paragraph(_esc(str(it)), styles["body"]), leftIndent=8)
        for it in (block.get("items") or ["—"])
    ]
    parts.append(ListFlowable(items, bulletType="bullet", start="•"))
    parts.append(Spacer(1, 3 * mm))
    return KeepTogether(parts)


def _table_block(block: dict, styles: dict) -> list:
    """Keep header+rows in chunks so long tables don't orphan mid-row groups."""
    headers = block.get("headers") or []
    rows = block.get("rows") or []
    title = Paragraph(_esc(block.get("title") or ""), styles["block"])

    def make_table(chunk_rows: list) -> Table:
        data = [[Paragraph(f"<b>{_esc(h)}</b>", styles["cell"]) for h in headers]]
        style_cmds: list[Any] = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0f0")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#dddddd")),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]
        for r_i, row in enumerate(chunk_rows):
            cells = []
            for c_i, c in enumerate(row):
                text = str(c)
                cat = text.upper()
                if c_i == 0 and cat in _CATEGORY_COLORS:
                    cells.append(
                        Paragraph(
                            f'<font color="{_CATEGORY_HEX[cat]}">'
                            f"<b>{_esc(text)}</b></font>",
                            styles["cell_cat"],
                        )
                    )
                    style_cmds.append(
                        ("TEXTCOLOR", (0, r_i + 1), (0, r_i + 1), _CATEGORY_COLORS[cat])
                    )
                else:
                    cells.append(Paragraph(_esc(text), styles["cell"]))
            data.append(cells)
        n = max(len(headers), 1)
        width = 170 * mm
        col_w = [width / n] * n
        # bias first narrow cols for cat/score
        if n >= 4:
            col_w = [18 * mm, 16 * mm, 28 * mm]
            rest = width - sum(col_w)
            col_w.extend([rest / (n - 3)] * (n - 3))
        t = Table(data, colWidths=col_w, repeatRows=1)
        t.setStyle(TableStyle(style_cmds))
        return t

    if not rows:
        return [KeepTogether([title, make_table([["—"]])])]

    out: list = []
    chunk_size = 12
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i : i + chunk_size]
        if i == 0:
            out.append(KeepTogether([title, make_table(chunk), Spacer(1, 3 * mm)]))
        else:
            out.append(KeepTogether([make_table(chunk), Spacer(1, 3 * mm)]))
    return out


def _log_block(block: dict, styles: dict) -> list:
    title = Paragraph(_esc(block.get("title") or ""), styles["block"])
    items = block.get("items") or []
    out: list = []
    chunk_size = 10
    for i in range(0, max(len(items), 1), chunk_size):
        chunk = items[i : i + chunk_size] if items else []
        paras: list[Any] = []
        if i == 0:
            paras.append(title)
        for it in chunk:
            line = (
                f"<b>{_esc(it.get('when') or '')}</b> "
                f"[{_esc(it.get('level') or '')}] "
                f"{_esc(it.get('event') or '')} — "
                f"{_esc(it.get('message') or '')}"
            )
            paras.append(Paragraph(line, styles["body"]))
        if not chunk and i == 0:
            paras.append(Paragraph("—", styles["body"]))
        paras.append(Spacer(1, 2 * mm))
        out.append(KeepTogether(paras))
    return out


def _theme_flowables(theme: ReportTheme, styles: dict) -> list:
    """Build flowables for one theme; sub-blocks wrapped in KeepTogether."""
    flow: list = [Paragraph(_esc(theme.title), styles["theme"])]
    for block in theme.blocks:
        btype = block.get("type")
        if btype == "kv":
            flow.append(_kv_block(block, styles))
        elif btype == "bullets":
            flow.append(_bullets_block(block, styles))
        elif btype == "table":
            flow.extend(_table_block(block, styles))
        elif btype == "log":
            flow.extend(_log_block(block, styles))
        else:
            flow.append(
                KeepTogether(
                    [Paragraph(_esc(str(block)), styles["body"]), Spacer(1, 2 * mm)]
                )
            )
    # Prefer keeping a short theme on one page when it fits.
    # Long themes already use KeepTogether on sub-blocks; wrapping the whole
    # theme would force awkward page jumps — only wrap if few flowables.
    if len(flow) <= 4:
        return [KeepTogether(flow)]
    return flow


def write_report_pdf(payload: ReportPayload, dest: BinaryIO | str | Path) -> None:
    """Write PDF into a binary stream or filesystem path."""
    _register_fonts()
    styles = _styles()
    doc = SimpleDocTemplate(
        dest if not isinstance(dest, Path) else str(dest),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
        title=payload.title,
        author=payload.app_name,
    )
    story: list = [
        Paragraph(_esc(payload.title), styles["title"]),
        Paragraph(
            f"Профиль: <b>{_esc(payload.profile)}</b> · "
            f"тип: <b>{_esc(payload.kind)}</b> · "
            f"{_esc(payload.generated_label)}",
            styles["meta"],
        ),
    ]
    for idx, theme in enumerate(payload.themes):
        if idx > 0:
            # Theme N (N>=2) always starts on a new page.
            story.append(PageBreak())
        story.extend(_theme_flowables(theme, styles))

    def _on_page(canvas, doc):
        _header_footer(canvas, doc, payload)

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)


def render_report_pdf(payload: ReportPayload) -> Path:
    """Render to a temp file; caller streams then deletes."""
    fd, name = tempfile.mkstemp(prefix="aa-report-", suffix=".pdf")
    os.close(fd)
    path = Path(name)
    try:
        write_report_pdf(payload, path)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def iter_file_chunks(path: Path, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            yield chunk
