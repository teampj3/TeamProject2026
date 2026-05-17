"""Autonomous Visualization Agent driven by the generated draft context."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.llm_client import LLMClient  # noqa: E402
from services.visualization_service import (  # noqa: E402
    VISUALIZATION_OUTPUT_DIR,
    clear_topic_visual_outputs,
    render_visual_spec,
    save_json_asset,
)


DEFAULT_WRITER_TOPIC = "AI code review"
DEFAULT_WRITER_SCORE_THRESHOLD = 35.0
VISUALIZATION_PLAN_MODEL = "claude-sonnet-4-6"
VISUALIZATION_PLAN_MAX_TOKENS = 1800

RELEVANCE_PATH = ROOT_DIR / "data/processed/relevance_result.json"
SUMMARY_PATH = ROOT_DIR / "data/processed/summary_result.json"
REPORT_OUTPUT_DIR = ROOT_DIR / "outputs/reports"
PROFILE_OUTPUT_PATH = ROOT_DIR / "data/processed/visualization_input_profile.json"

SUPPORTED_VISUAL_TYPES = {
    "table": {
        "description": "정의, 비교 항목, 실험 조건, 장단점처럼 표가 가장 잘 맞는 내용을 정리한다.",
        "required_data_shape": {"columns": ["열1", "열2"], "rows": [["값1", "값2"]]},
    },
    "bar_chart": {
        "description": "범주별 수치 비교를 시각화한다. 예: A=93.7, B=31.6",
        "required_data_shape": {
            "labels": ["A", "B"],
            "series": [{"name": "값", "values": [93.7, 31.6]}],
            "category_label": "비교 항목",
            "value_label": "값",
        },
    },
    "line_chart": {
        "description": "시간, 단계, 조건 변화에 따른 수치 흐름을 시각화한다.",
        "required_data_shape": {
            "x_values": ["1단계", "2단계", "3단계"],
            "series": [{"name": "성능", "values": [40, 58, 72]}],
            "x_label": "단계",
            "y_label": "값",
        },
    },
    "timeline": {
        "description": "역사, 발전 흐름, 연도별 사건, 연구 흐름을 시각화한다.",
        "required_data_shape": {
            "events": [
                {"time": "2009", "label": "사건", "detail": "설명"},
                {"time": "2017", "label": "확산", "detail": "설명"},
            ]
        },
    },
    "concept_diagram": {
        "description": "개념 정의, 구조 설명, 구성 요소 관계를 도식화한다.",
        "required_data_shape": {
            "central_topic": "핵심 개념",
            "branches": [
                {"label": "요소 1", "detail": "설명"},
                {"label": "요소 2", "detail": "설명"},
            ],
        },
    },
}


def safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("cp949", errors="replace").decode("cp949"))


def load_json_file(path: Path) -> list[dict]:
    if not path.exists():
        safe_print(f"파일 없음: {path}")
        return []
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
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
                "authors": summary.get("authors", relevance.get("authors", [])),
                "year": summary.get("year", relevance.get("year", "")),
                "source": summary.get("source", relevance.get("source", "")),
                "url": summary.get("url", relevance.get("url", "")),
                "abstract": summary.get("abstract", ""),
                "purpose": summary.get("purpose", ""),
                "method": summary.get("method", ""),
                "result": summary.get("result", ""),
                "limitation": summary.get("limitation", ""),
                "score": relevance.get("score"),
                "reason": relevance.get("reason", ""),
                "selection_result": relevance.get("selection_result", ""),
            }
        )
    return merged


def filter_writer_candidates(rows: list[dict], score_threshold: float) -> list[dict]:
    return [row for row in rows if float(row.get("score", 0) or 0) >= score_threshold]


def slugify_topic(topic: str) -> str:
    slug = topic.strip().lower().replace(" ", "_")
    slug = re.sub(r"[^a-z0-9_]+", "_", slug)
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or "report"


def load_report_text(topic: str = DEFAULT_WRITER_TOPIC) -> tuple[Path | None, str]:
    topic_slug = slugify_topic(topic)
    candidates = sorted(REPORT_OUTPUT_DIR.glob(f"{topic_slug}_*.md"))
    report_candidates = [path for path in candidates if not path.name.endswith("_visualized.md")]
    if not report_candidates:
        return None, ""
    report_path = report_candidates[-1]
    return report_path, report_path.read_text(encoding="utf-8")


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


def build_selected_rows_for_visualization(score_threshold: float = DEFAULT_WRITER_SCORE_THRESHOLD) -> list[dict]:
    relevance_rows = load_json_file(RELEVANCE_PATH)
    summary_rows = load_json_file(SUMMARY_PATH)
    merged_rows = merge_visualization_inputs(relevance_rows, summary_rows)
    return filter_writer_candidates(merged_rows, score_threshold=score_threshold)


def summarize_selected_rows(selected_rows: list[dict], max_items: int = 6) -> list[dict]:
    summarized = []
    for row in selected_rows[:max_items]:
        summarized.append(
            {
                "title": row.get("title", ""),
                "year": row.get("year", ""),
                "purpose": row.get("purpose", ""),
                "method": row.get("method", ""),
                "result": row.get("result", ""),
                "limitation": row.get("limitation", ""),
            }
        )
    return summarized


def build_visualization_profile(topic: str, score_threshold: float) -> dict:
    selected_rows = build_selected_rows_for_visualization(score_threshold=score_threshold)
    report_path, report_text = load_report_text(topic=topic)
    report_sections = extract_report_sections(report_text)
    profile = {
        "topic": topic,
        "score_threshold": score_threshold,
        "selected_paper_count": len(selected_rows),
        "selected_titles": [row.get("title", "") for row in selected_rows],
        "report_path": str(report_path) if report_path else "",
        "report_sections": [section.get("heading", "") for section in report_sections],
        "section_count": len(report_sections),
        "supported_visual_types": SUPPORTED_VISUAL_TYPES,
    }
    PROFILE_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_OUTPUT_PATH.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return profile


def print_visualization_profile(profile: dict) -> None:
    safe_print("Visualization Agent 입력 데이터 확인")
    safe_print(f"주제: {profile.get('topic', '')}")
    safe_print(f"선별 논문 수: {profile.get('selected_paper_count', 0)}")
    safe_print(f"최신 Writer 초안: {profile.get('report_path', '') or '없음'}")
    safe_print(f"초안 섹션: {profile.get('report_sections', [])}")


def strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def split_pipe_values(value: str) -> list[str]:
    return [part.strip() for part in value.split("||") if part.strip()]


def parse_visual_plan_text(raw_text: str) -> dict:
    text = strip_code_fences(raw_text)
    lines = [line.rstrip() for line in text.splitlines()]

    planning_note_parts: list[str] = []
    visuals: list[dict] = []
    current_visual: dict | None = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("PLANNING_NOTE:"):
            planning_note_parts.append(line.split(":", 1)[1].strip())
            continue

        if line == "VISUAL_START":
            current_visual = {
                "visual_id": "",
                "title": "",
                "target_section": "",
                "choice_reason": "",
                "source_excerpt": "",
                "visual_type": "",
                "data_spec": {},
            }
            continue

        if line == "VISUAL_END":
            if current_visual:
                visuals.append(current_visual)
                current_visual = None
            continue

        if current_visual is None:
            continue

        if line.startswith("ID:"):
            current_visual["visual_id"] = line.split(":", 1)[1].strip()
        elif line.startswith("TITLE:"):
            current_visual["title"] = line.split(":", 1)[1].strip()
        elif line.startswith("SECTION:"):
            current_visual["target_section"] = line.split(":", 1)[1].strip()
        elif line.startswith("REASON:"):
            current_visual["choice_reason"] = line.split(":", 1)[1].strip()
        elif line.startswith("SOURCE_EXCERPT:"):
            current_visual["source_excerpt"] = line.split(":", 1)[1].strip()
        elif line.startswith("TYPE:"):
            current_visual["visual_type"] = line.split(":", 1)[1].strip()
        elif line.startswith("SOURCE_NOTE:"):
            current_visual["data_spec"]["source_note"] = line.split(":", 1)[1].strip()
        elif line.startswith("COLUMNS:"):
            current_visual["data_spec"]["columns"] = split_pipe_values(line.split(":", 1)[1].strip())
            current_visual["data_spec"].setdefault("rows", [])
        elif line.startswith("ROW:"):
            current_visual["data_spec"].setdefault("rows", []).append(split_pipe_values(line.split(":", 1)[1].strip()))
        elif line.startswith("LABELS:"):
            current_visual["data_spec"]["labels"] = split_pipe_values(line.split(":", 1)[1].strip())
        elif line.startswith("SERIES:"):
            payload = split_pipe_values(line.split(":", 1)[1].strip())
            if payload:
                name = payload[0]
                values: list[float | str] = []
                for item in payload[1:]:
                    try:
                        values.append(float(item))
                    except ValueError:
                        values.append(item)
                current_visual["data_spec"].setdefault("series", []).append({"name": name, "values": values})
        elif line.startswith("CATEGORY_LABEL:"):
            current_visual["data_spec"]["category_label"] = line.split(":", 1)[1].strip()
        elif line.startswith("VALUE_LABEL:"):
            current_visual["data_spec"]["value_label"] = line.split(":", 1)[1].strip()
        elif line.startswith("ORIENTATION:"):
            current_visual["data_spec"]["orientation"] = line.split(":", 1)[1].strip()
        elif line.startswith("X_VALUES:"):
            current_visual["data_spec"]["x_values"] = split_pipe_values(line.split(":", 1)[1].strip())
        elif line.startswith("X_LABEL:"):
            current_visual["data_spec"]["x_label"] = line.split(":", 1)[1].strip()
        elif line.startswith("Y_LABEL:"):
            current_visual["data_spec"]["y_label"] = line.split(":", 1)[1].strip()
        elif line.startswith("EVENT:"):
            payload = split_pipe_values(line.split(":", 1)[1].strip())
            if len(payload) >= 3:
                current_visual["data_spec"].setdefault("events", []).append(
                    {"time": payload[0], "label": payload[1], "detail": payload[2]}
                )
        elif line.startswith("CENTRAL:"):
            current_visual["data_spec"]["central_topic"] = line.split(":", 1)[1].strip()
        elif line.startswith("BRANCH:"):
            payload = split_pipe_values(line.split(":", 1)[1].strip())
            if len(payload) >= 2:
                current_visual["data_spec"].setdefault("branches", []).append(
                    {"label": payload[0], "detail": payload[1]}
                )

    return {
        "planning_note": " ".join(planning_note_parts).strip(),
        "visuals": visuals,
    }


def repair_visual_plan_text(raw_text: str) -> dict:
    repair_prompt = f"""
다음 응답을 같은 내용으로 다시 정리하되, 아래 태그 형식만 사용하라.

반드시 지킬 것:
- 설명문 금지
- JSON 금지
- 오직 PLANNING_NOTE, VISUAL_START, ID, TITLE, SECTION, REASON, SOURCE_EXCERPT,
  TYPE, SOURCE_NOTE, COLUMNS, ROW, LABELS, SERIES, CATEGORY_LABEL, VALUE_LABEL,
  ORIENTATION, X_VALUES, X_LABEL, Y_LABEL, EVENT, CENTRAL, BRANCH, VISUAL_END 만 사용
- 값 구분은 || 로 한다

원본:
{raw_text}
""".strip()
    repaired = LLMClient().ask(repair_prompt, model=VISUALIZATION_PLAN_MODEL, max_tokens=1400)
    return parse_visual_plan_text(repaired)


def build_visualization_plan_prompt(
    topic: str,
    report_sections: list[dict],
    report_text: str,
    selected_rows: list[dict],
) -> str:
    section_payload = []
    for section in report_sections:
        body = " ".join(section.get("body", "").split())
        section_payload.append(
            {
                "heading": section.get("heading", ""),
                "body_preview": body[:900],
            }
        )

    return f"""
당신은 한국어 논문 초안을 읽고, 본문 이해를 실제로 돕는 시각 자료를 판단하는 Visualization Agent다.

이번 작업의 핵심 원칙:
- 기준은 참고 논문 목록이 아니라 "현재 작성된 초안 본문"이다.
- 초안의 문맥을 읽고, 시각 자료가 있으면 이해가 확실히 좋아지는 위치만 골라라.
- 선행연구 비교표를 기본값처럼 만들지 마라.
- 필요 없는 시각 자료는 만들지 마라.
- 시각 자료 개수를 미리 정하지 마라. 0개도 가능하고, 필요하면 1개 이상도 가능하다.
- 다만 정말 도움이 되는 자료만 제안하라.

판단 기준 예시:
- 정의, 구성 요소, 구조 관계 설명이 핵심이면 concept_diagram
- 실험 수치, 성능 비교, A/B 비교, 퍼센트 비교가 있으면 bar_chart 또는 line_chart
- 연도별 흐름, 역사, 단계적 발전이 있으면 timeline
- 표 형식이 더 직관적인 비교나 정리라면 table

중요:
- 초안에 없는 수치나 사건을 지어내지 마라.
- data_spec에는 바로 렌더링 가능한 실제 값만 넣어라.
- 숫자가 부족하면 숫자 그래프를 억지로 만들지 마라.
- 특정 섹션에 넣는 이유를 REASON에 짧고 분명하게 써라.
- SOURCE_EXCERPT에는 해당 판단의 근거가 된 초안 문장을 짧게 적어라.
- SECTION에는 아래 초안 섹션 제목 중 하나를 정확히 써라.

사용 가능한 visual_type:
{json.dumps(SUPPORTED_VISUAL_TYPES, ensure_ascii=False, indent=2)}

주제:
{topic}

초안 섹션과 내용:
{json.dumps(section_payload, ensure_ascii=False, indent=2)}

선별 논문 요약(보조 정보, 필요할 때만 사용):
{json.dumps(summarize_selected_rows(selected_rows), ensure_ascii=False, indent=2)}

초안 전체 원문:
{report_text}

반환 형식:
PLANNING_NOTE: 전체 판단 요약

VISUAL_START
ID: visual_1
TITLE: 시각 자료 제목
SECTION: 초안 섹션 제목
REASON: 왜 이 위치에 이 시각 자료가 필요한지
SOURCE_EXCERPT: 판단 근거가 된 초안 문장 일부
TYPE: table
SOURCE_NOTE: 데이터 출처 또는 구성 방식
COLUMNS: 열1 || 열2 || 열3
ROW: 값1 || 값2 || 값3
ROW: 값1 || 값2 || 값3
VISUAL_END

VISUAL_START
ID: visual_2
TITLE: 시각 자료 제목
SECTION: 초안 섹션 제목
REASON: 왜 이 위치에 이 시각 자료가 필요한지
SOURCE_EXCERPT: 판단 근거가 된 초안 문장 일부
TYPE: bar_chart
SOURCE_NOTE: 데이터 출처 또는 구성 방식
LABELS: A || B || C
SERIES: 값 || 93.7 || 31.6 || 88.1
CATEGORY_LABEL: 비교 항목
VALUE_LABEL: 수치
ORIENTATION: vertical
VISUAL_END

타입별 규칙:
- table: COLUMNS 1개 이상 + ROW 여러 개
- bar_chart: LABELS 1개 이상 + SERIES 1개 이상
- line_chart: X_VALUES 1개 이상 + SERIES 1개 이상
- timeline: EVENT 여러 개. 형식은 EVENT: 시간 || 사건명 || 설명
- concept_diagram: CENTRAL 1개 + BRANCH 여러 개. 형식은 BRANCH: 가지명 || 설명

중요:
- JSON으로 답하지 마라.
- 시각 자료가 정말 필요하지 않다면 PLANNING_NOTE만 쓰고 VISUAL_START를 쓰지 않아도 된다.
""".strip()


def is_literature_review_focused(visuals: list[dict]) -> bool:
    if not visuals:
        return False
    review_keywords = ("선행연구", "개요", "공통점", "차이점", "연구 공백")
    review_like_count = 0
    table_count = 0
    for visual in visuals:
        section = visual.get("target_section", "")
        visual_type = visual.get("visual_type", "")
        if any(keyword in section for keyword in review_keywords):
            review_like_count += 1
        if visual_type == "table":
            table_count += 1
    return review_like_count == len(visuals) or table_count == len(visuals)


def build_reconsideration_prompt(
    topic: str,
    report_sections: list[dict],
    report_text: str,
    selected_rows: list[dict],
    current_plan_text: str,
) -> str:
    section_payload = []
    for section in report_sections:
        body = " ".join(section.get("body", "").split())
        section_payload.append(
            {
                "heading": section.get("heading", ""),
                "body_preview": body[:700],
            }
        )

    return f"""
현재 시각화 계획이 초안의 핵심 설명보다 '선행연구 비교' 쪽으로만 과도하게 치우쳤는지 재검토하라.

재검토 기준:
- 초안의 핵심 설명, 문제 정의, 연구 목적, 연구 방법, 논의, 결론에 시각 자료가 더 유익한 부분이 있는지 우선 본다.
- 비교표 하나로 끝내지 마라.
- 초안에 구조 설명이 강하면 concept_diagram을 검토하라.
- 초안에 과정, 단계, 흐름이 강하면 line_chart 또는 timeline을 검토하라.
- 초안에 수치 비교가 실제로 있으면 bar_chart 또는 line_chart를 검토하라.
- 선행연구 비교는 정말 필요할 때만 유지하라.
- 개수는 고정하지 말고, 꼭 필요한 자료만 남겨라.
- 초안에 없는 내용은 지어내지 마라.

주제:
{topic}

초안 섹션과 내용:
{json.dumps(section_payload, ensure_ascii=False, indent=2)}

선별 논문 요약(보조 정보):
{json.dumps(summarize_selected_rows(selected_rows), ensure_ascii=False, indent=2)}

초안 전체 원문:
{report_text}

현재 계획:
{current_plan_text}

반환 형식은 이전과 동일한 태그 형식만 사용하라.
PLANNING_NOTE, VISUAL_START, ID, TITLE, SECTION, REASON, SOURCE_EXCERPT,
TYPE, SOURCE_NOTE, COLUMNS, ROW, LABELS, SERIES, CATEGORY_LABEL, VALUE_LABEL,
ORIENTATION, X_VALUES, X_LABEL, Y_LABEL, EVENT, CENTRAL, BRANCH, VISUAL_END
""".strip()


def build_visualization_plan(topic: str, report_sections: list[dict], report_text: str, selected_rows: list[dict]) -> dict:
    prompt = build_visualization_plan_prompt(
        topic=topic,
        report_sections=report_sections,
        report_text=report_text,
        selected_rows=selected_rows,
    )
    safe_print("\n시각 자료 계획 생성 중...")
    raw_response = LLMClient().ask(prompt, model=VISUALIZATION_PLAN_MODEL, max_tokens=VISUALIZATION_PLAN_MAX_TOKENS)
    try:
        plan = parse_visual_plan_text(raw_response)
    except Exception:
        plan = repair_visual_plan_text(raw_response)

    visuals_for_review = plan.get("visuals", []) if isinstance(plan, dict) else []
    if is_literature_review_focused(visuals_for_review):
        safe_print("시각화 계획이 문헌 비교 쪽으로 치우쳐 있어 재판단을 요청합니다...")
        reconsider_prompt = build_reconsideration_prompt(
            topic=topic,
            report_sections=report_sections,
            report_text=report_text,
            selected_rows=selected_rows,
            current_plan_text=raw_response,
        )
        reconsidered = LLMClient().ask(
            reconsider_prompt,
            model=VISUALIZATION_PLAN_MODEL,
            max_tokens=VISUALIZATION_PLAN_MAX_TOKENS,
        )
        try:
            reconsidered_plan = parse_visual_plan_text(reconsidered)
        except Exception:
            reconsidered_plan = repair_visual_plan_text(reconsidered)
        if reconsidered_plan.get("visuals"):
            plan = reconsidered_plan

    visuals = []
    for index, visual in enumerate(plan.get("visuals", []), 1):
        visual_type = visual.get("visual_type", "").strip()
        if visual_type not in SUPPORTED_VISUAL_TYPES:
            continue
        visuals.append(
            {
                "visual_id": visual.get("visual_id", f"visual_{index}"),
                "title": visual.get("title", f"시각 자료 {index}"),
                "target_section": visual.get("target_section", ""),
                "choice_reason": visual.get("choice_reason", ""),
                "source_excerpt": visual.get("source_excerpt", ""),
                "visual_type": visual_type,
                "data_spec": visual.get("data_spec", {}),
            }
        )

    return {
        "planner": "claude",
        "planning_note": plan.get("planning_note", ""),
        "visuals": visuals,
    }


def print_visualization_plan(plan: dict) -> None:
    safe_print("\nVisualization Agent 시각 자료 계획")
    safe_print(f"기획 방식: {plan.get('planner', 'unknown')}")
    safe_print(f"기획 메모: {plan.get('planning_note', '')}")
    if not plan.get("visuals"):
        safe_print("시각 자료가 꼭 필요하다고 판단된 위치가 없어 추가 생성하지 않았습니다.")
    for index, visual in enumerate(plan.get("visuals", []), 1):
        safe_print(
            f"[{index}] {visual.get('title', '')} | type={visual.get('visual_type', '')} | "
            f"section={visual.get('target_section', '')}"
        )


def generate_visual_assets_from_plan(topic: str, plan: dict) -> dict[str, str]:
    assets: dict[str, str] = {}
    for visual in plan.get("visuals", []):
        visual_type = visual.get("visual_type", "")
        if visual_type not in SUPPORTED_VISUAL_TYPES:
            continue
        save_path = render_visual_spec(topic, visual)
        assets[visual.get("visual_id", visual_type)] = str(save_path)
    return assets


def build_writer_visual_asset_map(profile: dict, plan: dict, assets: dict[str, str]) -> dict:
    section_to_assets: dict[str, list[str]] = {}
    visual_notes: dict[str, dict] = {}

    for visual in plan.get("visuals", []):
        visual_id = visual.get("visual_id", "")
        asset_path = assets.get(visual_id, "")
        target_section = visual.get("target_section", "기타")
        if asset_path:
            section_to_assets.setdefault(target_section, []).append(asset_path)
        visual_notes[visual_id] = {
            "title": visual.get("title", ""),
            "target_section": target_section,
            "visual_type": visual.get("visual_type", ""),
            "choice_reason": visual.get("choice_reason", ""),
            "source_excerpt": visual.get("source_excerpt", ""),
            "asset_path": asset_path,
        }

    return {
        "topic": profile.get("topic", ""),
        "writer_report_path": profile.get("report_path", ""),
        "section_to_visual_assets": section_to_assets,
        "visual_notes": visual_notes,
    }


def build_markdown_image_block(image_paths: list[str], report_path: Path) -> str:
    lines = ["", "> 시각 자료", ""]
    for image_path in image_paths:
        final_path = Path(image_path).resolve()
        relative_from_report = os.path.relpath(final_path, report_path.parent.resolve())
        lines.append(f"![visual]({relative_from_report.replace(os.sep, '/')})")
    lines.append("")
    return "\n".join(lines)


def insert_visuals_into_report(profile: dict, asset_map: dict) -> Path | None:
    report_path_str = profile.get("report_path", "")
    if not report_path_str:
        return None

    report_path = Path(report_path_str)
    if not report_path.exists():
        return None

    report_text = report_path.read_text(encoding="utf-8")
    lines = report_text.splitlines()
    section_assets = asset_map.get("section_to_visual_assets", {})

    inserted_sections: set[str] = set()
    output_lines: list[str] = []

    for line in lines:
        output_lines.append(line)
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            image_paths = section_assets.get(heading, [])
            if image_paths:
                output_lines.append(build_markdown_image_block(image_paths, report_path))
                inserted_sections.add(heading)

    for heading, image_paths in section_assets.items():
        if heading in inserted_sections or not image_paths:
            continue
        output_lines.append("")
        output_lines.append(f"## {heading} 시각 자료")
        output_lines.append(build_markdown_image_block(image_paths, report_path))

    visualized_path = report_path.with_name(f"{report_path.stem}_visualized.md")
    visualized_path.write_text("\n".join(output_lines) + "\n", encoding="utf-8")
    return visualized_path


def validate_visualization_outputs(profile: dict, plan: dict, assets: dict, mapping_path: Path, manifest_path: Path) -> dict:
    asset_status = {visual_id: bool(asset_path) and Path(asset_path).exists() for visual_id, asset_path in assets.items()}
    all_assets_saved = all(asset_status.values()) if asset_status else True
    has_plan = isinstance(plan.get("visuals"), list)
    return {
        "has_selected_papers": profile.get("selected_paper_count", 0) > 0,
        "has_plan": has_plan,
        "asset_status": asset_status,
        "all_assets_saved": all_assets_saved,
        "mapping_saved": mapping_path.exists(),
        "manifest_saved": manifest_path.exists(),
        "output_dir": str(VISUALIZATION_OUTPUT_DIR),
        "is_valid": has_plan and all_assets_saved and mapping_path.exists() and manifest_path.exists(),
    }


def print_visualization_validation(result: dict) -> None:
    safe_print("\nVisualization Agent 테스트 검증 결과")
    safe_print(f"선별 논문 존재 여부: {'성공' if result.get('has_selected_papers') else '실패'}")
    safe_print(f"시각화 계획 생성 여부: {'성공' if result.get('has_plan') else '실패'}")
    safe_print(f"시각 자료 저장 여부: {result.get('asset_status', {})}")
    safe_print(f"전체 저장 여부: {'성공' if result.get('all_assets_saved') else '실패'}")
    safe_print(f"Writer 연계 구조 저장 여부: {'성공' if result.get('mapping_saved') else '실패'}")
    safe_print(f"매니페스트 저장 여부: {'성공' if result.get('manifest_saved') else '실패'}")
    safe_print(f"출력 경로: {result.get('output_dir', '')}")
    safe_print("Visualization Agent 테스트 완료" if result.get("is_valid") else "Visualization Agent 테스트 실패")


def run_visualization_pipeline(topic: str = DEFAULT_WRITER_TOPIC, score_threshold: float = DEFAULT_WRITER_SCORE_THRESHOLD) -> dict:
    clear_topic_visual_outputs(topic)
    profile = build_visualization_profile(topic=topic, score_threshold=score_threshold)
    print_visualization_profile(profile)

    selected_rows = build_selected_rows_for_visualization(score_threshold=score_threshold)
    _report_path, report_text = load_report_text(topic=topic)
    report_sections = extract_report_sections(report_text)
    plan = build_visualization_plan(
        topic=topic,
        report_sections=report_sections,
        report_text=report_text,
        selected_rows=selected_rows,
    )
    print_visualization_plan(plan)
    plan_path = save_json_asset(topic, "visual_plan", plan)
    safe_print(f"\n시각 자료 계획 저장 완료: {plan_path}")

    assets = generate_visual_assets_from_plan(topic=topic, plan=plan)
    asset_map = build_writer_visual_asset_map(profile, plan, assets)
    asset_map_path = save_json_asset(topic, "visual_asset_map", asset_map)
    visualized_report_path = insert_visuals_into_report(profile, asset_map)
    manifest_path = save_json_asset(
        topic,
        "visualization_manifest",
        {
            "topic": topic,
            "planner": plan.get("planner", "unknown"),
            "planning_note": plan.get("planning_note", ""),
            "assets": assets,
            "writer_visual_mapping": str(asset_map_path),
            "visualized_report_path": str(visualized_report_path) if visualized_report_path else "",
            "profile_path": str(PROFILE_OUTPUT_PATH),
        },
    )
    safe_print(f"Writer 연계 구조 저장 완료: {asset_map_path}")
    if visualized_report_path:
        safe_print(f"시각 자료 삽입 초안 저장 완료: {visualized_report_path}")
    safe_print(f"시각화 결과 저장 완료: {manifest_path}")

    result = validate_visualization_outputs(profile, plan, assets, asset_map_path, manifest_path)
    print_visualization_validation(result)
    return result


if __name__ == "__main__":
    run_visualization_pipeline()
