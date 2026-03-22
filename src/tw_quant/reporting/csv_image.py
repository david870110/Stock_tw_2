"""Helpers for rendering CSV-style row data into preview PNG artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # pragma: no cover - optional dependency fallback
    Image = None
    ImageDraw = None
    ImageFont = None


_FONT_CANDIDATES = (
    "C:/Windows/Fonts/msjh.ttc",
    "C:/Windows/Fonts/microsoftjhengheiui.ttf",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simsun.ttc",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/consola.ttf",
)


def write_csv_preview_image(
    *,
    csv_path: str | Path,
    fieldnames: Sequence[str],
    rows: Sequence[dict[str, Any]],
) -> str | None:
    if Image is None or ImageDraw is None or ImageFont is None:
        return None

    output_path = Path(csv_path).with_suffix(".png")
    normalized_fieldnames = [str(field) for field in fieldnames]
    normalized_rows = [
        {field: _stringify_cell(row.get(field, "")) for field in normalized_fieldnames}
        for row in rows
    ]
    font = _load_font(size=18)
    header_font = _load_font(size=18, bold=True)
    padding_x = 10
    padding_y = 8
    min_col_width = 120
    max_col_width = 320
    line_spacing = 6
    max_lines_per_cell = 4

    sample_rows = normalized_rows[: min(len(normalized_rows), 60)]
    col_widths: list[int] = []
    dummy_image = Image.new("RGB", (1, 1), "white")
    drawer = ImageDraw.Draw(dummy_image)
    for field in normalized_fieldnames:
        header_width = int(drawer.textlength(field, font=header_font)) + padding_x * 2
        content_width = max(
            (
                _measure_wrapped_width(
                    text=row.get(field, ""),
                    draw=drawer,
                    font=font,
                    max_width=max_col_width - padding_x * 2,
                    max_lines=max_lines_per_cell,
                )
                + padding_x * 2
                for row in sample_rows
            ),
            default=min_col_width,
        )
        col_widths.append(max(min_col_width, min(max_col_width, max(header_width, content_width))))

    line_height = _line_height(font)
    header_height = line_height + padding_y * 2
    body_heights = [
        _row_height(
            row=row,
            fieldnames=normalized_fieldnames,
            col_widths=col_widths,
            draw=drawer,
            font=font,
            line_height=line_height,
            padding_y=padding_y,
            max_lines=max_lines_per_cell,
        )
        for row in normalized_rows
    ]

    image_width = max(1, sum(col_widths) + 1)
    image_height = max(1, header_height + sum(body_heights) + 1)
    image = Image.new("RGB", (image_width, image_height), "white")
    draw = ImageDraw.Draw(image)

    x = 0
    for field, width in zip(normalized_fieldnames, col_widths, strict=False):
        draw.rectangle((x, 0, x + width, header_height), fill="#EAF2FF", outline="#AAB7C4", width=1)
        draw.text((x + padding_x, padding_y), field, font=header_font, fill="#17212B")
        x += width

    y = header_height
    for row_index, row in enumerate(normalized_rows):
        row_height = body_heights[row_index]
        background = "#FFFFFF" if row_index % 2 == 0 else "#F7F9FC"
        x = 0
        for field, width in zip(normalized_fieldnames, col_widths, strict=False):
            draw.rectangle((x, y, x + width, y + row_height), fill=background, outline="#D5DEE8", width=1)
            wrapped = _wrap_text(
                text=row.get(field, ""),
                draw=draw,
                font=font,
                max_width=max(20, width - padding_x * 2),
                max_lines=max_lines_per_cell,
            )
            text_y = y + padding_y
            for line in wrapped:
                draw.text((x + padding_x, text_y), line, font=font, fill="#1F2933")
                text_y += line_height + line_spacing
            x += width
        y += row_height

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    return str(output_path)


def _stringify_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _load_font(*, size: int, bold: bool = False):
    if ImageFont is None:
        return None
    if bold:
        bold_candidates = (
            "C:/Windows/Fonts/msjhbd.ttc",
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/consolab.ttf",
        )
        for path in (*bold_candidates, *_FONT_CANDIDATES):
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                continue
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _line_height(font) -> int:
    if hasattr(font, "size"):
        return int(font.size) + 2
    return 18


def _wrap_text(*, text: str, draw, font, max_width: int, max_lines: int) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    logical_lines = normalized.split("\n") if normalized else [""]
    wrapped_lines: list[str] = []
    for logical_line in logical_lines:
        if not logical_line:
            wrapped_lines.append("")
            if len(wrapped_lines) >= max_lines:
                return wrapped_lines[:max_lines]
            continue
        current = ""
        for char in logical_line:
            candidate = f"{current}{char}"
            if current and draw.textlength(candidate, font=font) > max_width:
                wrapped_lines.append(current)
                current = char
                if len(wrapped_lines) >= max_lines:
                    return _truncate_last_line(wrapped_lines, draw=draw, font=font, max_width=max_width)
            else:
                current = candidate
        if current or not wrapped_lines:
            wrapped_lines.append(current)
        if len(wrapped_lines) >= max_lines:
            return _truncate_last_line(wrapped_lines[:max_lines], draw=draw, font=font, max_width=max_width)
    return wrapped_lines[:max_lines]


def _truncate_last_line(lines: list[str], *, draw, font, max_width: int) -> list[str]:
    if not lines:
        return [""]
    lines = list(lines)
    last = lines[-1]
    ellipsis = "..."
    while last and draw.textlength(f"{last}{ellipsis}", font=font) > max_width:
        last = last[:-1]
    lines[-1] = f"{last}{ellipsis}" if last else ellipsis
    return lines


def _measure_wrapped_width(*, text: str, draw, font, max_width: int, max_lines: int) -> int:
    lines = _wrap_text(text=text, draw=draw, font=font, max_width=max_width, max_lines=max_lines)
    return max((int(draw.textlength(line, font=font)) for line in lines), default=0)


def _row_height(
    *,
    row: dict[str, str],
    fieldnames: Sequence[str],
    col_widths: Sequence[int],
    draw,
    font,
    line_height: int,
    padding_y: int,
    max_lines: int,
) -> int:
    counts = []
    for field, width in zip(fieldnames, col_widths, strict=False):
        wrapped = _wrap_text(
            text=row.get(field, ""),
            draw=draw,
            font=font,
            max_width=max(20, width - 20),
            max_lines=max_lines,
        )
        counts.append(max(1, len(wrapped)))
    return max(1, max(counts, default=1)) * (line_height + 6) + padding_y * 2
