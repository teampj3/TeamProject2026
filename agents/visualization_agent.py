"""Visualization Agent.

This agent reads the latest Writer draft, asks Claude whether visuals are needed,
asks Claude to produce renderable data_spec values, validates those specs, and
renders only the visuals that pass schema checks.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.llm_client import LLMClient  # noqa: E402
from services.visualization_service import (  # noqa: E402
    VISUALIZATION_OUTPUT_DIR,
    clear_topic_visual_outputs,
    normalize_text,
    render_visual_spec,
    save_json_asset,
    slugify_topic,
)


DEFAULT_WRITER_SCORE_THRESHOLD = 35.0
VISUALIZATION_PLAN_MODEL = "claude-sonnet-4-6"
VISUALIZATION_PLAN_MAX_TOKENS = 2200

RELEVANCE_PATH = ROOT_DIR / "data" / "processed" / "relevance_result.json"
SUMMARY_PATH = ROOT_DIR / "data" / "processed" / "summary_result.json"
REPORT_OUTPUT_DIR = ROOT_DIR / "outputs" / "reports"

SUPPORTED_VISUAL_TYPES = {
    "table",
    "bar_chart",
    "line_chart",
    "timeline",
    "concept_diagram",
}


def safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("cp949", errors="replace").decode("cp949"))


def load_json_file(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def merge_visualization_inputs(relevance_rows: list[dict], summary_rows: list[dict]) -> list[dict]:
    summary_by_title = {
        row.get("title", "").strip(): row
        for row in summary_rows
        if row.get("title", "").strip()
    }
    merged: list[dict] = []
    for relevance in relevance_rows:
        title = relevance.get("title", "").strip()
        summary = summary_by_title.get(title, {})
        merged.append(
            {
                "title": title,
                "year": summary.get("year", relevance.get("year", "")),
                "purpose": summary.get("purpose", ""),
                "method": summary.get("method", ""),
                "result": summary.get("result", ""),
                "limitation": summary.get("limitation", ""),
                "score": relevance.get("score", 0),
                "reason": relevance.get("reason", ""),
            }
        )
    return merged


def build_selected_rows_for_visualization(score_threshold: float = DEFAULT_WRITER_SCORE_THRESHOLD) -> list[dict]:
    relevance_rows = load_json_file(RELEVANCE_PATH)
    summary_rows = load_json_file(SUMMARY_PATH)
    merged_rows = merge_visualization_inputs(relevance_rows, summary_rows)
    return [row for row in merged_rows if float(row.get("score", 0) or 0) >= score_threshold]


def infer_topic_from_report_path(report_path: Path) -> str:
    stem = report_path.stem
    stem = re.sub(r"_visualized$", "", stem)
    match = re.match(r"(.+?)_\d{8}_\d{6}$", stem)
    if match:
        return match.group(1).replace("_", " ")
    return stem.replace("_", " ")


def load_latest_report(topic: str | None = None) -> tuple[Path | None, str, str]:
    candidates = sorted(REPORT_OUTPUT_DIR.glob("*.md"), key=lambda path: path.stat().st_mtime)
    report_candidates = [path for path in candidates if not path.name.endswith("_visualized.md")]
    if topic:
        prefix = f"{slugify_topic(topic)}_"
        report_candidates = [path for path in report_candidates if path.name.startswith(prefix)]
    if not report_candidates:
        return None, "", topic or ""
    report_path = report_candidates[-1]
    inferred_topic = infer_topic_from_report_path(report_path)
    report_text = report_path.read_text(encoding="utf-8")
    return report_path, report_text, inferred_topic


def extract_report_sections(report_text: str) -> list[dict]:
    sections: list[dict] = []
    current_heading = ""
    current_level = 0
    current_lines: list[str] = []

    for line in report_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            if current_heading:
                sections.append(
                    {
                        "heading": current_heading,
                        "level": current_level,
                        "body": "\n".join(current_lines).strip(),
                    }
                )
            current_level = len(stripped) - len(stripped.lstrip("#"))
            current_heading = stripped.lstrip("#").strip()
            current_lines = []
            continue
        if current_heading:
            current_lines.append(line)

    if current_heading:
        sections.append(
            {
                "heading": current_heading,
                "level": current_level,
                "body": "\n".join(current_lines).strip(),
            }
        )
    return sections


def extract_paragraph_candidates(report_sections: list[dict]) -> list[dict]:
    candidates: list[dict] = []
    for section in report_sections:
        heading = section.get("heading", "")
        body = section.get("body", "")
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", body) if part.strip()]
        for index, paragraph in enumerate(paragraphs, 1):
            candidates.append(
                {
                    "section": heading,
                    "paragraph_index": index,
                    "text": normalize_text(paragraph, 520),
                }
            )
    return candidates


def extract_json_block(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("JSON block not found")
    return text[start : end + 1]


def sanitize_visual_spec(visual: dict) -> dict:
    visual["visual_id"] = str(visual.get("visual_id", "")).strip() or "visual"
    visual["visual_type"] = str(visual.get("visual_type", "")).strip()
    visual["title"] = normalize_text(str(visual.get("title", "")).strip(), 80)
    visual["target_section"] = str(visual.get("target_section", "")).strip()
    visual["choice_reason"] = normalize_text(str(visual.get("choice_reason", "")).strip(), 220)
    visual["data_spec"] = visual.get("data_spec", {}) if isinstance(visual.get("data_spec", {}), dict) else {}
    return visual


# Python은 내용 자체를 만들지 않고, LLM이 만든 data_spec이 형식에 맞는지만 검증합니다.
def validate_visual_spec(visual: dict) -> tuple[bool, str]:
    visual_type = visual.get("visual_type")
    data_spec = visual.get("data_spec", {})

    if visual_type not in SUPPORTED_VISUAL_TYPES:
        return False, f"unsupported visual_type: {visual_type}"

    if visual_type == "table":
        columns = data_spec.get("columns", [])
        rows = data_spec.get("rows", [])
        if not isinstance(columns, list) or not isinstance(rows, list):
            return False, "table columns or rows is not a list"
        if len(columns) < 2 or not rows:
            return False, "table requires at least 2 columns and 1 row"
        if len(columns) > 6:
            return False, "table has too many columns"

        clean_columns = [normalize_text(str(column).strip(), 24) for column in columns if str(column).strip()]
        if len(clean_columns) != len(columns):
            return False, "table has empty column names"

        clean_rows = []
        for row in rows[:8]:
            if not isinstance(row, list) or len(row) != len(columns):
                return False, "table row length mismatch"
            clean_rows.append([normalize_text(str(cell).strip(), 36) for cell in row])

        data_spec["columns"] = clean_columns
        data_spec["rows"] = clean_rows
        return True, "ok"

    if visual_type == "timeline":
        events = data_spec.get("events", [])
        if not isinstance(events, list):
            return False, "timeline events is not a list"

        valid_events = []
        for event in events:
            if not isinstance(event, dict):
                continue
            time = str(event.get("time", "")).strip()
            label = str(event.get("label", "")).strip()
            detail = str(event.get("detail", "")).strip()
            if not time or not label or not detail:
                continue
            if label.startswith("(") or label.startswith(")"):
                continue
            if "et al" in label.lower():
                continue
            if len(label) > 40:
                continue
            if re.search(r"\b(?:19|20)\d{2}\b", label) and len(label.split()) <= 2:
                continue
            valid_events.append(
                {
                    "time": normalize_text(time, 16),
                    "label": normalize_text(label, 32),
                    "detail": normalize_text(detail, 90),
                }
            )

        data_spec["events"] = valid_events
        if len(valid_events) < 3:
            return False, "timeline has fewer than 3 valid events"
        return True, "ok"

    if visual_type in {"bar_chart", "line_chart"}:
        labels = data_spec.get("labels", [])
        series = data_spec.get("series", [])
        if not isinstance(labels, list) or not isinstance(series, list):
            return False, "labels or series is not a list"
        if len(labels) < 2 or not series:
            return False, "not enough labels or series"
        if len(labels) > 4:
            return False, "chart has too many labels"
        if len(series) > 3:
            return False, "chart has too many series"

        clean_labels = [normalize_text(str(label).strip(), 28) for label in labels if str(label).strip()]
        if len(clean_labels) < 2:
            return False, "not enough cleaned labels"

        clean_series = []
        for item in series:
            if not isinstance(item, dict):
                return False, "series item is not a dict"
            name = normalize_text(str(item.get("name", "")).strip(), 28)
            values = item.get("values", [])
            if not name or not isinstance(values, list) or len(values) != len(clean_labels):
                return False, "series values length mismatch"
            if not all(isinstance(value, (int, float)) for value in values):
                return False, "series contains non-numeric values"
            if len(name) > 26:
                return False, "series label too long"
            clean_series.append({"name": name, "values": values})

        data_spec["labels"] = clean_labels
        data_spec["series"] = clean_series
        if visual_type == "bar_chart":
            data_spec["category_label"] = normalize_text(str(data_spec.get("category_label", "비교 기준")), 24)
            data_spec["value_label"] = normalize_text(str(data_spec.get("value_label", "측정값")), 24)
        else:
            data_spec["x_label"] = normalize_text(str(data_spec.get("x_label", "시점")), 24)
            data_spec["y_label"] = normalize_text(str(data_spec.get("y_label", "측정값")), 24)
        return True, "ok"

    if visual_type == "concept_diagram":
        central_topic = str(data_spec.get("central_topic", "")).strip()
        branches = data_spec.get("branches", [])
        if not central_topic:
            return False, "concept_diagram central_topic missing"
        if not isinstance(branches, list):
            return False, "concept_diagram branches is not a list"

        valid_branches = []
        for branch in branches:
            if not isinstance(branch, dict):
                continue
            label = str(branch.get("label", "")).strip()
            detail = str(branch.get("detail", "")).strip()
            if label:
                valid_branches.append(
                    {
                        "label": normalize_text(label, 24),
                        "detail": normalize_text(detail, 28) if detail else "",
                    }
                )

        data_spec["central_topic"] = normalize_text(central_topic, 36)
        data_spec["branches"] = valid_branches[:6]
        if len(valid_branches) < 2:
            return False, "concept_diagram has fewer than 2 valid branches"
        return True, "ok"

    return False, "unknown validation path"


def build_visualization_plan(topic: str, report_sections: list[dict], report_text: str, selected_rows: list[dict]) -> dict:
    paragraph_candidates = extract_paragraph_candidates(report_sections)
    selected_context = selected_rows[:6]

    prompt = f"""
당신은 사용자가 입력한 주제의 논문 초안을 분석하여 시각자료 계획을 세우는 Visualization Agent다.

중요 규칙:
1. 주제는 매번 달라질 수 있으므로 특정 분야 지식을 하드코딩하지 말고, 제공된 초안 내용에 근거해 시각자료를 설계한다.
2. 시각자료가 필요 없으면 need_visual="no"로 답한다.
3. 시각자료가 필요하면 최대 2개만 만든다.
4. visual_type은 반드시 다음 중 하나를 사용한다:
   - table
   - bar_chart
   - line_chart
   - timeline
   - concept_diagram
5. 각 visual에는 반드시 렌더링 가능한 data_spec을 포함한다.
6. 논문 인용 연도, 참고문헌 연도, 저자명 뒤의 연도는 timeline 사건으로 사용하지 않는다.
7. 본문에 근거가 부족한 수치나 사건은 임의로 만들지 않는다.
8. 응답은 JSON만 작성한다.
9. 항목 수가 많고 범례가 길면 bar_chart를 피하고 table을 우선한다.
10. 정성적 비교는 table을 우선한다.
11. 수치 축의 의미가 약하면 bar_chart를 피한다.
12. 한 차트에는 최대 3개 핵심 지표만 포함한다.
13. 비교 대상이 2~4개이고 수치가 명확할 때만 bar_chart 또는 line_chart를 사용한다.

visual_type별 data_spec 형식:

0) table:
{{
  "columns": ["항목", "특징 A", "특징 B"],
  "rows": [
    ["비교 대상 1", "설명", "설명"],
    ["비교 대상 2", "설명", "설명"]
  ]
}}

1) bar_chart:
{{
  "labels": ["비교 대상1", "비교 대상2"],
  "series": [
    {{
      "name": "측정 항목",
      "values": [10, 20]
    }}
  ],
  "category_label": "비교 기준",
  "value_label": "측정값"
}}

2) line_chart:
{{
  "labels": ["시점1", "시점2", "시점3"],
  "series": [
    {{
      "name": "변화 항목",
      "values": [10, 15, 20]
    }}
  ],
  "x_label": "시점",
  "y_label": "측정값"
}}

3) timeline:
{{
  "events": [
    {{
      "time": "시점",
      "label": "짧은 사건명",
      "detail": "사건의 의미를 설명하는 한 문장"
    }}
  ]
}}

4) concept_diagram:
{{
  "central_topic": "중심 개념",
  "branches": [
    {{
      "label": "하위 개념",
      "detail": "역할 또는 설명"
    }}
  ]
}}

응답 형식:
{{
  "need_visual": "yes",
  "need_reason": "시각자료가 필요한 이유",
  "visuals": [
    {{
      "visual_id": "visual_1",
      "visual_type": "table",
      "title": "시각자료 제목",
      "target_section": "적용할 섹션명",
      "choice_reason": "이 시각자료 형식이 적절한 이유",
      "data_spec": {{
        "columns": [],
        "rows": []
      }}
    }}
  ]
}}

[사용자 주제]
{topic}

[초안 섹션 후보]
{json.dumps(paragraph_candidates[:18], ensure_ascii=False, indent=2)}

[선별 논문 요약 참고]
{json.dumps(selected_context, ensure_ascii=False, indent=2)}

[논문 초안]
{report_text[:6000]}
"""

    safe_print("\n시각 자료 계획 생성 중...")
    try:
        raw_response = LLMClient().ask(
            prompt,
            model=VISUALIZATION_PLAN_MODEL,
            max_tokens=VISUALIZATION_PLAN_MAX_TOKENS,
        )
        plan = json.loads(extract_json_block(raw_response))
    except Exception as error:
        safe_print(f"Claude 시각화 계획 요청 실패: {error}")
        return {
            "planner": "claude_failed",
            "planning_note": "Claude 계획 생성에 실패하여 시각 자료를 만들지 않았습니다.",
            "need_visual": "no",
            "need_reason": "계획 생성 실패",
            "candidates": paragraph_candidates[:18],
            "visuals": [],
            "validation_errors": [],
        }

    valid_visuals = []
    validation_errors = []
    for visual in plan.get("visuals", []):
        if not isinstance(visual, dict):
            validation_errors.append("visual item is not an object")
            continue
        visual = sanitize_visual_spec(visual)
        is_valid, reason = validate_visual_spec(visual)
        if is_valid:
            valid_visuals.append(visual)
        else:
            validation_errors.append(f"{visual.get('visual_id', 'visual')}: {reason}")

    plan["planner"] = "claude"
    plan["planning_note"] = ""
    plan["candidates"] = paragraph_candidates[:18]
    plan["visuals"] = valid_visuals
    plan["validation_errors"] = validation_errors
    plan["need_visual"] = "yes" if valid_visuals else "no"
    if not valid_visuals and not plan.get("need_reason"):
        plan["need_reason"] = "검증을 통과한 시각 자료가 없어 생성하지 않았습니다."
    return plan


def print_visualization_plan(plan: dict) -> None:
    safe_print("\nVisualization Agent 시각 자료 계획")
    safe_print(f"기획 방식: {plan.get('planner', 'unknown')}")
    safe_print(f"기획 메모: {plan.get('planning_note', '')}")
    safe_print(f"시각화 필요 여부: {plan.get('need_visual', 'unknown')}")
    safe_print(f"필요 이유: {plan.get('need_reason', '')}")
    if plan.get("validation_errors"):
        safe_print("검증 제외 항목:")
        for error in plan["validation_errors"]:
            safe_print(f"- {error}")
    if not plan.get("visuals"):
        safe_print("시각 자료를 생성하지 않습니다.")
    for index, visual in enumerate(plan.get("visuals", []), 1):
        safe_print(
            f"[{index}] {visual.get('title', '')} | type={visual.get('visual_type', '')} | "
            f"section={visual.get('target_section', '')}"
        )


def generate_visual_assets_from_plan(topic: str, plan: dict) -> dict[str, str]:
    assets: dict[str, str] = {}
    if plan.get("need_visual") != "yes":
        return assets
    for visual in plan.get("visuals", []):
        try:
            save_path = render_visual_spec(topic, visual)
            assets[visual.get("visual_id", "visual")] = str(save_path)
        except Exception as error:
            safe_print(f"시각 자료 생성 실패: {visual.get('title', visual.get('visual_id', 'visual'))} | {error}")
    return assets


def build_writer_visual_asset_map(profile: dict, plan: dict, assets: dict[str, str]) -> dict:
    section_to_assets: dict[str, list[str]] = {}
    visual_notes: dict[str, dict] = {}
    for visual in plan.get("visuals", []):
        visual_id = visual.get("visual_id", "")
        target_section = visual.get("target_section", "")
        asset_path = assets.get(visual_id, "")
        if not asset_path:
            continue
        section_to_assets.setdefault(target_section, []).append(asset_path)
        visual_notes[visual_id] = {
            "title": visual.get("title", ""),
            "reason": visual.get("choice_reason", ""),
            "visual_type": visual.get("visual_type", ""),
        }
    return {
        "topic": profile.get("topic", ""),
        "source_report": str(profile.get("report_path", "")),
        "section_to_assets": section_to_assets,
        "visual_notes": visual_notes,
    }


def insert_visuals_into_report(report_path: Path, asset_map: dict) -> Path:
    original = report_path.read_text(encoding="utf-8")
    sections = original.split("\n---\n")
    rebuilt_sections: list[str] = []

    for section in sections:
        stripped = section.strip()
        if not stripped:
            continue
        lines = stripped.splitlines()
        heading_line = lines[0].strip()
        heading_name = re.sub(r"^#{1,3}\s+", "", heading_line).strip()
        rebuilt_sections.append(stripped)
        asset_paths = asset_map.get("section_to_assets", {}).get(heading_name, [])
        if asset_paths:
            embeds = [f"![{Path(path).stem}]({path})" for path in asset_paths]
            rebuilt_sections.append("\n".join(embeds))

    visualized_path = report_path.with_name(f"{report_path.stem}_visualized.md")
    visualized_path.write_text("\n\n---\n\n".join(rebuilt_sections) + "\n", encoding="utf-8")
    return visualized_path


def validate_visualization_outputs(assets: dict[str, str], plan: dict, asset_map_path: Path, manifest_path: Path) -> dict:
    return {
        "selected_rows_exists": True,
        "plan_exists": bool(plan),
        "assets_exist": {key: Path(value).exists() for key, value in assets.items()},
        "asset_map_exists": asset_map_path.exists(),
        "manifest_exists": manifest_path.exists(),
    }


def run_visualization_pipeline(topic: str | None = None, score_threshold: float = DEFAULT_WRITER_SCORE_THRESHOLD) -> dict:
    report_path, report_text, inferred_topic = load_latest_report(topic=topic)
    if report_path is None or not report_text:
        safe_print("Visualization Agent를 실행하려면 먼저 Writer 초안이 필요합니다.")
        return {"is_valid": False}

    active_topic = topic or inferred_topic
    report_sections = extract_report_sections(report_text)
    selected_rows = build_selected_rows_for_visualization(score_threshold=score_threshold)

    safe_print("Visualization Agent 입력 데이터 확인")
    safe_print(f"주제: {active_topic}")
    safe_print(f"선별 논문 수: {len(selected_rows)}")
    safe_print(f"최신 Writer 초안: {report_path}")
    safe_print(f"초안 섹션: {[section.get('heading', '') for section in report_sections]}")

    clear_topic_visual_outputs(active_topic)

    plan = build_visualization_plan(
        topic=active_topic,
        report_sections=report_sections,
        report_text=report_text,
        selected_rows=selected_rows,
    )
    print_visualization_plan(plan)

    topic_slug = slugify_topic(active_topic)
    plan_path = save_json_asset(f"{topic_slug}_visual_plan.json", plan)
    safe_print(f"\n시각 자료 계획 저장 완료: {plan_path}")

    assets = generate_visual_assets_from_plan(active_topic, plan)

    profile = {
        "topic": active_topic,
        "report_path": report_path,
        "report_sections": report_sections,
        "selected_rows": selected_rows,
    }
    writer_asset_map = build_writer_visual_asset_map(profile, plan, assets)
    asset_map_path = save_json_asset(f"{topic_slug}_visual_asset_map.json", writer_asset_map)
    safe_print(f"Writer 연계 구조 저장 완료: {asset_map_path}")

    visualized_report_path = insert_visuals_into_report(report_path, writer_asset_map)
    safe_print(f"시각 자료 삽입 초안 저장 완료: {visualized_report_path}")

    manifest = {
        "topic": active_topic,
        "planner": plan.get("planner", ""),
        "plan_file": str(plan_path),
        "visual_assets": assets,
        "asset_map_file": str(asset_map_path),
        "visualized_report": str(visualized_report_path),
    }
    manifest_path = save_json_asset(f"{topic_slug}_visualization_manifest.json", manifest)
    safe_print(f"시각화 결과 저장 완료: {manifest_path}")

    validation = validate_visualization_outputs(assets, plan, asset_map_path, manifest_path)
    safe_print("\nVisualization Agent 테스트 검증 결과")
    safe_print(f"선별 논문 존재 여부: {'성공' if validation['selected_rows_exists'] else '실패'}")
    safe_print(f"시각화 계획 생성 여부: {'성공' if validation['plan_exists'] else '실패'}")
    safe_print(f"시각 자료 저장 여부: {validation['assets_exist']}")
    safe_print(f"전체 저장 여부: {'성공' if Path(visualized_report_path).exists() else '실패'}")
    safe_print(f"Writer 연계 구조 저장 여부: {'성공' if validation['asset_map_exists'] else '실패'}")
    safe_print(f"매니페스트 저장 여부: {'성공' if validation['manifest_exists'] else '실패'}")
    safe_print(f"출력 경로: {VISUALIZATION_OUTPUT_DIR}")
    safe_print("Visualization Agent 테스트 완료")

    return {
        "is_valid": True,
        "topic": active_topic,
        "report_path": str(report_path),
        "plan_path": str(plan_path),
        "asset_map_path": str(asset_map_path),
        "manifest_path": str(manifest_path),
        "assets": assets,
        "visualized_report": str(visualized_report_path),
    }


if __name__ == "__main__":
    run_visualization_pipeline()
