"""Local Pillow-based renderers for visualization assets."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT_DIR = Path(__file__).resolve().parent.parent
VISUALIZATION_OUTPUT_DIR = ROOT_DIR / "outputs" / "visualizations"

CANVAS_WIDTH = 1600
CANVAS_HEIGHT = 900
BACKGROUND = "#f8fafc"
PANEL = "#ffffff"
BORDER = "#dbe3ee"
TEXT = "#1f2937"
SUBTEXT = "#475569"
GRID = "#e5e7eb"
ACCENT = "#2563eb"
ACCENT_2 = "#0f766e"
ACCENT_3 = "#dc2626"
ACCENT_4 = "#7c3aed"
ACCENT_5 = "#ea580c"
PALETTE = [ACCENT, ACCENT_2, ACCENT_3, ACCENT_4, ACCENT_5]

FONT_CANDIDATES = [
    Path("C:/Windows/Fonts/malgun.ttf"),
    Path("C:/Windows/Fonts/malgunbd.ttf"),
    Path("C:/Windows/Fonts/NanumGothic.ttf"),
]


def ensure_output_dir() -> Path:
    VISUALIZATION_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return VISUALIZATION_OUTPUT_DIR


def slugify_topic(topic: str) -> str:
    slug = topic.strip().lower().replace(" ", "_")
    slug = re.sub(r"[^a-z0-9_]+", "_", slug)
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or "report"


def slugify_name(name: str) -> str:
    slug = name.strip().lower().replace(" ", "_")
    slug = re.sub(r"[^a-z0-9_]+", "_", slug)
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or "visual"


def normalize_text(text: str, max_length: int = 80) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= max_length:
        return compact
    return compact[: max_length - 3].rstrip() + "..."


def _build_output_path(topic: str, visual_id: str) -> Path:
    ensure_output_dir()
    return VISUALIZATION_OUTPUT_DIR / f"{slugify_topic(topic)}_{slugify_name(visual_id)}.png"


def clear_topic_visual_outputs(topic: str) -> None:
    ensure_output_dir()
    prefix = f"{slugify_topic(topic)}_"
    for path in VISUALIZATION_OUTPUT_DIR.glob(f"{prefix}*"):
        if path.name == ".gitkeep":
            continue
        try:
            if path.is_file():
                path.unlink()
        except PermissionError:
            continue


def save_json_asset(filename: str, payload: dict | list) -> Path:
    ensure_output_dir()
    path = VISUALIZATION_OUTPUT_DIR / filename
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = FONT_CANDIDATES[::-1] if bold else FONT_CANDIDATES
    for candidate in candidates:
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _create_canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (CANVAS_WIDTH, CANVAS_HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((40, 40, CANVAS_WIDTH - 40, CANVAS_HEIGHT - 40), radius=28, fill=PANEL, outline=BORDER, width=2)
    return image, draw


def _text_box(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=6)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _wrap(text: str, limit: int) -> str:
    words = str(text or "").split()
    if not words:
        return ""
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        if len(trial) <= limit:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return "\n".join(lines)


def _draw_title(draw: ImageDraw.ImageDraw, title: str, subtitle: str = "") -> None:
    title_font = _font(40, bold=True)
    subtitle_font = _font(20)
    title_w, title_h = _text_box(draw, title, title_font)
    draw.text(((CANVAS_WIDTH - title_w) / 2, 70), title, font=title_font, fill=TEXT)
    if subtitle:
        subtitle = normalize_text(subtitle, 120)
        sub_w, _sub_h = _text_box(draw, subtitle, subtitle_font)
        draw.text(((CANVAS_WIDTH - sub_w) / 2, 122), subtitle, font=subtitle_font, fill=SUBTEXT)


def _save(image: Image.Image, topic: str, visual_id: str) -> Path:
    path = _build_output_path(topic, visual_id)
    image.save(path, format="PNG", optimize=True)
    return path


def render_table(topic: str, visual_id: str, title: str, data_spec: dict) -> Path:
    columns = data_spec.get("columns", [])
    rows = data_spec.get("rows", [])
    if not columns or not rows:
        raise ValueError("table data_spec requires columns and rows")

    image, draw = _create_canvas()
    _draw_title(draw, title, data_spec.get("source_note", ""))

    header_font = _font(22, bold=True)
    body_font = _font(20)

    left = 90
    top = 180
    width = CANVAS_WIDTH - 180
    col_count = len(columns)
    col_width = width / col_count
    row_height = 78

    for index, column in enumerate(columns):
        x0 = left + col_width * index
        x1 = x0 + col_width
        draw.rounded_rectangle((x0, top, x1, top + row_height), radius=10, fill="#e8eef9", outline=BORDER, width=2)
        wrapped = _wrap(column, 14)
        tw, th = _text_box(draw, wrapped, header_font)
        draw.multiline_text((x0 + (col_width - tw) / 2, top + (row_height - th) / 2), wrapped, font=header_font, fill=TEXT, spacing=6)

    for row_index, row in enumerate(rows):
        y0 = top + row_height + row_index * row_height
        y1 = y0 + row_height
        fill = "#ffffff" if row_index % 2 == 0 else "#f8fafc"
        for col_index, cell in enumerate(row):
            x0 = left + col_width * col_index
            x1 = x0 + col_width
            draw.rectangle((x0, y0, x1, y1), fill=fill, outline=BORDER, width=1)
            wrapped = _wrap(str(cell), 18 if col_index else 12)
            tw, th = _text_box(draw, wrapped, body_font)
            draw.multiline_text((x0 + 18, y0 + (row_height - th) / 2), wrapped, font=body_font, fill=TEXT, spacing=5)

    return _save(image, topic, visual_id)


def render_bar_chart(topic: str, visual_id: str, title: str, data_spec: dict) -> Path:
    labels = data_spec.get("labels", [])
    series = data_spec.get("series", [])
    if not labels or not series:
        raise ValueError("bar_chart data_spec requires labels and series")

    image, draw = _create_canvas()
    _draw_title(draw, title, data_spec.get("source_note", ""))

    chart_left = 120
    chart_top = 230
    chart_right = CANVAS_WIDTH - 120
    chart_bottom = CANVAS_HEIGHT - 140
    draw.rectangle((chart_left, chart_top, chart_right, chart_bottom), outline=BORDER, width=2)

    all_values = [value for item in series for value in item.get("values", [])]
    max_value = max(all_values) if all_values else 1
    step_count = 5
    for step in range(step_count + 1):
        y = chart_bottom - (chart_bottom - chart_top) * step / step_count
        draw.line((chart_left, y, chart_right, y), fill=GRID, width=1)
        label = f"{max_value * step / step_count:.1f}"
        draw.text((chart_left - 55, y - 10), label, font=_font(18), fill=SUBTEXT)

    group_count = len(labels)
    group_width = (chart_right - chart_left) / max(1, group_count)
    bar_width = min(70, (group_width - 40) / max(1, len(series)))

    for group_index, label in enumerate(labels):
        group_x = chart_left + group_width * group_index + group_width / 2
        for series_index, item in enumerate(series):
            values = item.get("values", [])
            value = values[group_index]
            color = PALETTE[series_index % len(PALETTE)]
            x0 = group_x - (len(series) * bar_width) / 2 + series_index * bar_width
            x1 = x0 + bar_width - 10
            bar_height = 0 if max_value == 0 else (value / max_value) * (chart_bottom - chart_top - 30)
            y0 = chart_bottom - bar_height
            draw.rounded_rectangle((x0, y0, x1, chart_bottom), radius=10, fill=color)
            value_text = f"{value:.1f}" if isinstance(value, float) and not value.is_integer() else str(int(value))
            tw, th = _text_box(draw, value_text, _font(18, bold=True))
            draw.text((x0 + (x1 - x0 - tw) / 2, y0 - th - 8), value_text, font=_font(18, bold=True), fill=TEXT)

        wrapped_label = _wrap(label, 10)
        tw, _th = _text_box(draw, wrapped_label, _font(20))
        draw.multiline_text((group_x - tw / 2, chart_bottom + 20), wrapped_label, font=_font(20), fill=TEXT, align="center", spacing=4)

    legend_y = 165
    legend_x = 120
    for series_index, item in enumerate(series):
        color = PALETTE[series_index % len(PALETTE)]
        draw.rounded_rectangle((legend_x, legend_y, legend_x + 24, legend_y + 24), radius=4, fill=color)
        draw.text((legend_x + 34, legend_y - 2), normalize_text(item.get("name", ""), 24), font=_font(19), fill=TEXT)
        legend_x += 260

    return _save(image, topic, visual_id)


def render_line_chart(topic: str, visual_id: str, title: str, data_spec: dict) -> Path:
    labels = data_spec.get("labels", [])
    series = data_spec.get("series", [])
    if not labels or not series:
        raise ValueError("line_chart data_spec requires labels and series")

    image, draw = _create_canvas()
    _draw_title(draw, title, data_spec.get("source_note", ""))

    chart_left = 120
    chart_top = 230
    chart_right = CANVAS_WIDTH - 120
    chart_bottom = CANVAS_HEIGHT - 140
    draw.rectangle((chart_left, chart_top, chart_right, chart_bottom), outline=BORDER, width=2)

    all_values = [value for item in series for value in item.get("values", [])]
    max_value = max(all_values) if all_values else 1
    step_count = 5
    for step in range(step_count + 1):
        y = chart_bottom - (chart_bottom - chart_top) * step / step_count
        draw.line((chart_left, y, chart_right, y), fill=GRID, width=1)
        label = f"{max_value * step / step_count:.1f}"
        draw.text((chart_left - 55, y - 10), label, font=_font(18), fill=SUBTEXT)

    x_positions = []
    for index, label in enumerate(labels):
        x = chart_left + (chart_right - chart_left) * index / max(1, len(labels) - 1)
        x_positions.append(x)
        wrapped_label = _wrap(label, 10)
        tw, _th = _text_box(draw, wrapped_label, _font(20))
        draw.multiline_text((x - tw / 2, chart_bottom + 20), wrapped_label, font=_font(20), fill=TEXT, align="center", spacing=4)

    for series_index, item in enumerate(series):
        color = PALETTE[series_index % len(PALETTE)]
        points = []
        for x, value in zip(x_positions, item.get("values", [])):
            y = chart_bottom - (0 if max_value == 0 else (value / max_value) * (chart_bottom - chart_top - 30))
            points.append((x, y))
        if len(points) >= 2:
            draw.line(points, fill=color, width=5)
        for x, y in points:
            draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill=color, outline="#ffffff", width=3)

    legend_y = 165
    legend_x = 120
    for series_index, item in enumerate(series):
        color = PALETTE[series_index % len(PALETTE)]
        draw.line((legend_x, legend_y + 12, legend_x + 34, legend_y + 12), fill=color, width=5)
        draw.ellipse((legend_x + 10, legend_y + 4, legend_x + 24, legend_y + 18), fill=color, outline="#ffffff", width=2)
        draw.text((legend_x + 46, legend_y - 2), normalize_text(item.get("name", ""), 24), font=_font(19), fill=TEXT)
        legend_x += 260

    return _save(image, topic, visual_id)


def render_timeline(topic: str, visual_id: str, title: str, data_spec: dict) -> Path:
    events = data_spec.get("events", [])
    if not events:
        raise ValueError("timeline data_spec requires events")

    image, draw = _create_canvas()
    _draw_title(draw, title, data_spec.get("source_note", ""))

    line_y = 460
    left = 140
    right = CANVAS_WIDTH - 140
    draw.line((left, line_y, right, line_y), fill=ACCENT, width=6)

    count = len(events)
    positions = [left + (right - left) * index / max(1, count - 1) for index in range(count)]
    for index, (x, event) in enumerate(zip(positions, events)):
        top = index % 2 == 0
        draw.ellipse((x - 16, line_y - 16, x + 16, line_y + 16), fill=ACCENT, outline="#ffffff", width=4)
        year = normalize_text(event.get("time", ""), 16)
        label = _wrap(event.get("label", ""), 12)
        detail = _wrap(event.get("detail", ""), 26)

        year_font = _font(22, bold=True)
        card_font = _font(19)
        if top:
            draw.text((x - 28, line_y - 70), year, font=year_font, fill=TEXT)
            card_top = line_y - 240
            draw.rounded_rectangle((x - 180, card_top, x + 180, card_top + 120), radius=18, fill="#eef4ff", outline=BORDER, width=2)
            draw.multiline_text((x - 160, card_top + 18), label, font=_font(21, bold=True), fill=TEXT, spacing=4)
            draw.multiline_text((x - 160, card_top + 58), detail, font=card_font, fill=SUBTEXT, spacing=4)
        else:
            draw.text((x - 28, line_y + 30), year, font=year_font, fill=TEXT)
            card_top = line_y + 80
            draw.rounded_rectangle((x - 180, card_top, x + 180, card_top + 120), radius=18, fill="#f8fafc", outline=BORDER, width=2)
            draw.multiline_text((x - 160, card_top + 18), label, font=_font(21, bold=True), fill=TEXT, spacing=4)
            draw.multiline_text((x - 160, card_top + 58), detail, font=card_font, fill=SUBTEXT, spacing=4)

    return _save(image, topic, visual_id)


def render_concept_diagram(topic: str, visual_id: str, title: str, data_spec: dict) -> Path:
    branches = data_spec.get("branches", [])
    if not branches:
        raise ValueError("concept_diagram data_spec requires branches")

    image, draw = _create_canvas()
    _draw_title(draw, title, data_spec.get("source_note", ""))

    center_x = CANVAS_WIDTH / 2
    center_y = 330
    central_topic = normalize_text(data_spec.get("central_topic", title), 28)
    central_box = (center_x - 230, center_y - 50, center_x + 230, center_y + 50)
    draw.rounded_rectangle(central_box, radius=24, fill=ACCENT_2, outline=ACCENT_2, width=2)
    center_text = _wrap(central_topic, 18)
    tw, th = _text_box(draw, center_text, _font(26, bold=True))
    draw.multiline_text((center_x - tw / 2, center_y - th / 2), center_text, font=_font(26, bold=True), fill="#ffffff", align="center", spacing=6)

    count = len(branches)

    def spaced_positions(node_count: int, y: float, left_margin: int = 180, right_margin: int = 180) -> list[tuple[float, float]]:
        if node_count <= 0:
            return []
        if node_count == 1:
            return [(center_x, y)]
        usable_width = CANVAS_WIDTH - left_margin - right_margin
        step = usable_width / (node_count - 1)
        return [(left_margin + step * index, y) for index in range(node_count)]

    # 구성요소는 모두 중앙 주제 아래로 배치해 위쪽 겹침을 막습니다.
    if count <= 3:
        positions = spaced_positions(count, 640, 240, 240)
    else:
        top_count = math.ceil(count / 2)
        bottom_count = count - top_count
        positions = spaced_positions(top_count, 585, 200, 200)
        positions += spaced_positions(bottom_count, 745, 240, 240)

    for branch, (x, y) in zip(branches, positions):
        box_width = 300
        box_height = 92
        line_start = (center_x, center_y + 50)
        line_end = (x, y - box_height / 2)
        draw.line((*line_start, *line_end), fill="#7dd3fc", width=5)

        label = _wrap(branch.get("label", ""), 14)
        label_font = _font(21, bold=True)
        box = (x - box_width / 2, y - box_height / 2, x + box_width / 2, y + box_height / 2)
        draw.rounded_rectangle(box, radius=20, fill="#eff6ff", outline="#93c5fd", width=2)
        label_w, label_h = _text_box(draw, label, label_font)
        label_x = x - label_w / 2
        label_y = y - label_h / 2
        draw.multiline_text((label_x, label_y), label, font=label_font, fill=TEXT, align="center", spacing=4)

    return _save(image, topic, visual_id)


RENDERERS = {
    "table": render_table,
    "bar_chart": render_bar_chart,
    "line_chart": render_line_chart,
    "timeline": render_timeline,
    "concept_diagram": render_concept_diagram,
}


def render_visual_spec(topic: str, visual_spec: dict) -> Path:
    visual_type = visual_spec.get("visual_type", "")
    renderer = RENDERERS.get(visual_type)
    if not renderer:
        raise ValueError(f"unsupported visual_type: {visual_type}")

    visual_id = visual_spec.get("visual_id") or visual_spec.get("title") or visual_type
    title = visual_spec.get("title", visual_type)
    data_spec = visual_spec.get("data_spec", {})
    return renderer(topic, visual_id, title, data_spec)
