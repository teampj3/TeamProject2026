"""Generic visualization renderers for context-driven draft visuals."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re

ROOT_DIR = Path(__file__).resolve().parents[1]
VISUALIZATION_OUTPUT_DIR = ROOT_DIR / "outputs/visualizations"
MPLCONFIGDIR = ROOT_DIR / ".cache" / "matplotlib"
MPLCONFIGDIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(MPLCONFIGDIR))

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

plt.rcParams["font.family"] = ["Malgun Gothic", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
sns.set_theme(style="whitegrid", font="Malgun Gothic")


def ensure_output_dir() -> Path:
    VISUALIZATION_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return VISUALIZATION_OUTPUT_DIR


def slugify_topic(topic: str) -> str:
    slug = topic.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    return slug.strip("_") or "report"


def slugify_name(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9가-힣]+", "_", name.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "visual"


def clear_topic_visual_outputs(topic: str) -> None:
    ensure_output_dir()
    slug = slugify_topic(topic)
    for path in VISUALIZATION_OUTPUT_DIR.glob(f"{slug}_*"):
        if path.is_file():
            try:
                path.unlink(missing_ok=True)
            except PermissionError:
                # Windows에서 미리보기로 열어 둔 파일은 삭제가 막힐 수 있으므로 건너뜁니다.
                continue


def save_json_asset(topic: str, filename_suffix: str, payload: dict) -> Path:
    ensure_output_dir()
    save_path = VISUALIZATION_OUTPUT_DIR / f"{slugify_topic(topic)}_{filename_suffix}.json"
    save_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return save_path


def normalize_text(text: str, max_length: int = 180) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) > max_length:
        return cleaned[: max_length - 3].rstrip() + "..."
    return cleaned


def _build_output_path(topic: str, visual_id: str) -> Path:
    ensure_output_dir()
    return VISUALIZATION_OUTPUT_DIR / f"{slugify_topic(topic)}_{slugify_name(visual_id)}.png"


def _figure_title(ax, title: str, subtitle: str = "") -> None:
    ax.set_title(title, fontsize=16, fontweight="bold", pad=16)
    if subtitle:
        ax.text(
            0.5,
            1.02,
            subtitle,
            transform=ax.transAxes,
            ha="center",
            va="bottom",
            fontsize=9,
            color="#475569",
        )


def render_table(topic: str, visual_id: str, title: str, data_spec: dict) -> Path:
    rows = data_spec.get("rows", [])
    columns = data_spec.get("columns", [])
    if not rows or not columns:
        raise ValueError("table data_spec requires columns and rows")

    df = pd.DataFrame(rows, columns=columns)
    fig_height = max(4.0, 1.2 + len(df) * 0.68)
    fig_width = max(12.0, len(df.columns) * 2.6)
    fig, ax = plt.subplots(figsize=(fig_width, fig_height))
    ax.axis("off")
    _figure_title(ax, title, data_spec.get("source_note", ""))

    table = ax.table(
        cellText=df.values,
        colLabels=df.columns,
        cellLoc="left",
        colLoc="center",
        loc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.0, 1.6)

    for (row_idx, _col_idx), cell in table.get_celld().items():
        cell.set_edgecolor("#d4d4d8")
        if row_idx == 0:
            cell.set_text_props(weight="bold", color="#111827")
            cell.set_facecolor("#e2e8f0")
        else:
            cell.set_facecolor("#ffffff" if row_idx % 2 else "#f8fafc")

    save_path = _build_output_path(topic, visual_id)
    fig.tight_layout()
    fig.savefig(save_path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return save_path


def render_bar_chart(topic: str, visual_id: str, title: str, data_spec: dict) -> Path:
    labels = data_spec.get("labels", [])
    series = data_spec.get("series", [])
    orientation = data_spec.get("orientation", "vertical")
    if not labels or not series:
        raise ValueError("bar_chart data_spec requires labels and series")

    df = pd.DataFrame({"label": labels})
    for item in series:
        df[item["name"]] = item.get("values", [])

    melted = df.melt(id_vars="label", var_name="series", value_name="value")
    fig, ax = plt.subplots(figsize=(11.5, 6.8))

    if orientation == "horizontal":
        sns.barplot(data=melted, y="label", x="value", hue="series", ax=ax, palette="crest")
        ax.set_ylabel(data_spec.get("category_label", "항목"))
        ax.set_xlabel(data_spec.get("value_label", "값"))
    else:
        sns.barplot(data=melted, x="label", y="value", hue="series", ax=ax, palette="crest")
        ax.set_xlabel(data_spec.get("category_label", "항목"))
        ax.set_ylabel(data_spec.get("value_label", "값"))
        ax.tick_params(axis="x", rotation=0)

    _figure_title(ax, title, data_spec.get("source_note", ""))
    ax.legend(title="", loc="upper right", frameon=True)
    ax.set_ylim(bottom=0)
    ax.grid(axis="y", alpha=0.22)

    for container in ax.containers:
        try:
            ax.bar_label(container, fmt="%.1f", padding=3, fontsize=9)
        except Exception:
            pass

    save_path = _build_output_path(topic, visual_id)
    fig.tight_layout()
    fig.savefig(save_path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return save_path


def render_line_chart(topic: str, visual_id: str, title: str, data_spec: dict) -> Path:
    x_values = data_spec.get("x_values", [])
    series = data_spec.get("series", [])
    if not x_values or not series:
        raise ValueError("line_chart data_spec requires x_values and series")

    fig, ax = plt.subplots(figsize=(11, 6))
    for item in series:
        ax.plot(
            x_values,
            item.get("values", []),
            marker="o",
            linewidth=2.5,
            label=item.get("name", "series"),
        )

    _figure_title(ax, title, data_spec.get("source_note", ""))
    ax.set_xlabel(data_spec.get("x_label", "X"))
    ax.set_ylabel(data_spec.get("y_label", "Y"))
    ax.legend()
    ax.grid(alpha=0.25)

    save_path = _build_output_path(topic, visual_id)
    fig.tight_layout()
    fig.savefig(save_path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return save_path


def render_timeline(topic: str, visual_id: str, title: str, data_spec: dict) -> Path:
    events = data_spec.get("events", [])
    if not events:
        raise ValueError("timeline data_spec requires events")

    events = sorted(events, key=lambda item: str(item.get("time", "")))
    x_values = list(range(len(events)))
    fig_height = max(4.8, 4.2 + len(events) * 0.45)
    fig, ax = plt.subplots(figsize=(12.5, fig_height))

    ax.hlines(y=1, xmin=min(x_values, default=0), xmax=max(x_values, default=1), color="#cbd5e1", linewidth=3)
    ax.scatter(x_values, [1] * len(events), s=240, color="#2563eb", zorder=3)

    for index, event in enumerate(events):
        top = index % 2 == 0
        year_y = 1.12 if top else 0.88
        box_y = 1.23 if top else 0.77
        ax.text(index, year_y, str(event.get("time", "")), ha="center", va="bottom" if top else "top", fontsize=10, fontweight="bold")
        ax.text(
            index,
            box_y,
            f"{normalize_text(event.get('label', ''), 28)}\n{normalize_text(event.get('detail', ''), 40)}",
            ha="center",
            va="bottom" if top else "top",
            fontsize=8.5,
            color="#334155",
            bbox=dict(boxstyle="round,pad=0.35", facecolor="#f8fafc", edgecolor="#cbd5e1"),
        )

    _figure_title(ax, title, data_spec.get("source_note", ""))
    ax.set_yticks([])
    ax.set_xticks([])
    ax.set_ylim(0.62, 1.34)
    for spine in ax.spines.values():
        spine.set_visible(False)

    save_path = _build_output_path(topic, visual_id)
    fig.tight_layout()
    fig.savefig(save_path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return save_path


def render_concept_diagram(topic: str, visual_id: str, title: str, data_spec: dict) -> Path:
    central = data_spec.get("central_topic", title)
    branches = data_spec.get("branches", [])
    if not branches:
        raise ValueError("concept_diagram data_spec requires branches")

    fig, ax = plt.subplots(figsize=(12.5, 7.6))
    ax.axis("off")
    _figure_title(ax, title, data_spec.get("source_note", ""))

    ax.text(
        0.5,
        0.82,
        central,
        ha="center",
        va="center",
        fontsize=17,
        fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.6", facecolor="#0f766e", edgecolor="#0f766e", alpha=0.92),
        color="white",
        transform=ax.transAxes,
    )

    count = min(4, max(1, len(branches)))
    layout = {
        1: [(0.5, 0.45)],
        2: [(0.28, 0.45), (0.72, 0.45)],
        3: [(0.18, 0.45), (0.5, 0.34), (0.82, 0.45)],
        4: [(0.14, 0.48), (0.38, 0.34), (0.62, 0.34), (0.86, 0.48)],
    }

    for (x_pos, y_pos), branch in zip(layout[count], branches[:count]):
        ax.plot([0.5, x_pos], [0.74, y_pos + 0.08], color="#99f6e4", linewidth=3, transform=ax.transAxes)
        ax.text(
            x_pos,
            y_pos,
            branch.get("label", "핵심 항목"),
            ha="center",
            va="center",
            fontsize=13,
            fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.55", facecolor="#ffffff", edgecolor="#99f6e4"),
            color="#134e4a",
            transform=ax.transAxes,
        )
        ax.text(
            x_pos,
            y_pos - 0.18,
            normalize_text(branch.get("detail", ""), 86) or "보조 설명",
            ha="center",
            va="center",
            fontsize=9,
            bbox=dict(boxstyle="round,pad=0.45", facecolor="#f8fafc", edgecolor="#cbd5e1"),
            color="#334155",
            transform=ax.transAxes,
        )

    save_path = _build_output_path(topic, visual_id)
    fig.tight_layout()
    fig.savefig(save_path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return save_path


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
