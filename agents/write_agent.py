"""Writer Agent for generating a Korean paper-style draft."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import time

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.llm_client import LLMClient
from services.output_service import get_run_output_dir, write_json, write_markdown


RELEVANCE_PATH = Path("data/processed/relevance_result.json")
SUMMARY_PATH = Path("data/processed/summary_result.json")
PIPELINE_CONTEXT_PATH = Path("data/processed/pipeline_context.json")
REPORT_OUTPUT_DIR = Path("outputs/reports")

DEFAULT_WRITER_TOPIC = "AI code review"
DEFAULT_WRITER_SCORE_THRESHOLD = 35.0
OUTLINE_MAX_TOKENS = 1000
BULLET_MAX_TOKENS = 450
SUBSECTION_MAX_TOKENS = 800

FIXED_SECTIONS = ["제목", "초록", "서론", "논의", "결론", "참고문헌"]
FIXED_SECTION_PLAN = {
    "제목": ["제목"],
    "초록": ["초록"],
    "서론": ["연구 배경", "연구 필요성"],
    "논의": ["시사점", "한계 및 보완점"],
    "결론": ["핵심 정리", "향후 방향"],
    "참고문헌": ["참고문헌"],
}
BASE_SECTION_ALIASES = {
    "제목": ["제목", "# 제목"],
    "초록": ["초록", "# 초록"],
    "서론": ["서론", "# 서론"],
    "논의": ["논의", "# 논의"],
    "결론": ["결론", "# 결론"],
    "참고문헌": ["참고문헌", "참고 문헌", "# 참고문헌"],
}
SYNTHESIS_MARKERS = [
    "본 연구는",
    "이러한 점에서",
    "따라서",
    "결국",
    "종합하면",
    "제안한다",
    "기준",
    "프레임워크",
    "활용 방안",
]
REQUIRED_WRITER_FIELDS = [
    "title",
    "score",
    "reason",
    "purpose",
    "method",
    "result",
    "limitation",
]
OUTLINE_CACHE: dict[str, dict] = {}


def safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("cp949", errors="replace").decode("cp949"))


def load_json_file(path: Path) -> list[dict]:
    if not path.exists():
        print(f"파일 없음: {path}")
        return []
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, list):
        print(f"목록 형식이 아님: {path}")
        return []
    return data


def load_pipeline_topic(path: Path = PIPELINE_CONTEXT_PATH) -> str | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    topic = str(payload.get("topic", "")).strip()
    return topic or None


def resolve_writer_topic(topic: str | None = None) -> str:
    explicit_topic = (topic or "").strip()
    if explicit_topic:
        return explicit_topic
    pipeline_topic = load_pipeline_topic()
    if pipeline_topic:
        return pipeline_topic
    return DEFAULT_WRITER_TOPIC


def merge_writer_inputs(relevance_rows: list[dict], summary_rows: list[dict]) -> list[dict]:
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
                "id": relevance.get("id", summary.get("id", "")),
                "title": title,
                "score": relevance.get("score"),
                "reason": relevance.get("reason", ""),
                "purpose": summary.get("purpose", ""),
                "method": summary.get("method", ""),
                "result": summary.get("result", ""),
                "limitation": summary.get("limitation", ""),
                "authors": summary.get("authors", relevance.get("authors", [])),
                "year": summary.get("year", relevance.get("year", "")),
                "url": summary.get("url", relevance.get("url", "")),
                "source": summary.get("source", relevance.get("source", "")),
                "selection_result": relevance.get("selection_result", ""),
            }
        )
    return merged


def find_missing_fields(row: dict, required_fields: list[str]) -> list[str]:
    missing: list[str] = []
    for field in required_fields:
        value = row.get(field)
        if value is None:
            missing.append(field)
        elif isinstance(value, str) and not value.strip():
            missing.append(field)
    return missing


def print_writer_input_preview(rows: list[dict], preview_count: int = 3) -> None:
    print(f"Writer 입력 데이터 {len(rows)}편 확인")
    for index, row in enumerate(rows[:preview_count], 1):
        print(f"\n[{index}] {row.get('title', '')}")
        print(f"  관련성 점수: {row.get('score')}")
        print(f"  선정 이유: {row.get('reason', '')[:120]}")
        print(f"  목적: {row.get('purpose', '')}")
        print(f"  방법: {row.get('method', '')}")
        print(f"  결과: {row.get('result', '')}")
        print(f"  한계: {row.get('limitation', '')}")


def filter_writer_candidates(
    rows: list[dict],
    score_threshold: float = DEFAULT_WRITER_SCORE_THRESHOLD,
) -> list[dict]:
    return [row for row in rows if float(row.get("score", 0) or 0) >= score_threshold]


def print_writer_candidate_list(
    rows: list[dict],
    score_threshold: float = DEFAULT_WRITER_SCORE_THRESHOLD,
) -> None:
    print(f"\nWriter 입력 대상 논문 목록 (기준 점수: {score_threshold:.1f} 이상)")
    if not rows:
        print("선별된 논문이 없습니다.")
        return
    for index, row in enumerate(rows, 1):
        print(f"[{index}] {row.get('title', '')}")
        print(f"  관련성 점수: {row.get('score')}")
        print(f"  선정 이유: {row.get('reason', '')[:120]}")


def build_paper_context(selected_rows: list[dict]) -> str:
    paper_blocks: list[str] = []
    for index, row in enumerate(selected_rows, 1):
        paper_blocks.append(
            "\n".join(
                [
                    f"[논문 {index}]",
                    f"제목: {row.get('title', '')}",
                    f"관련성 점수: {row.get('score')}",
                    f"선정 이유: {row.get('reason', '')}",
                    f"목적: {row.get('purpose', '')}",
                    f"방법: {row.get('method', '')}",
                    f"결과: {row.get('result', '')}",
                    f"한계: {row.get('limitation', '')}",
                    f"저자: {', '.join(row.get('authors', []))}",
                    f"연도: {row.get('year', '')}",
                    f"링크: {row.get('url', '')}",
                    f"출처: {row.get('source', '')}",
                ]
            )
        )
    return "\n\n".join(paper_blocks)


def split_pipe_values(value: str) -> list[str]:
    return [part.strip() for part in value.split("||") if part.strip()]


def build_outline_prompt(topic: str, selected_rows: list[dict]) -> str:
    paper_text = build_paper_context(selected_rows[:5])
    return f"""당신은 한국어 학술논문 목차를 설계하는 Writer Planner이다.

주제:
{topic}

참고 논문 요약:
{paper_text}

목표:
- 참고 논문을 바탕으로 "하나의 논문 초안"을 작성하기 위한 학술논문형 목차를 설계한다.
- 제목, 초록, 서론, 논의, 결론, 참고문헌은 고정이다.
- 그 사이의 본문 섹션 3~4개는 주제에 맞게 동적으로 만든다.
- 섹션명은 주제에 따라 달라져야 하며, 특정 주제 전용 표현을 고정적으로 쓰지 마라.
- 비교 보고서처럼 "공통점/차이점" 중심으로만 흐르지 않게 하고, 본 연구가 무엇을 분석·도출·제안하는지가 드러나게 한다.

형식:
OUTLINE_NOTE: 한 줄 설명

SECTION_START
NAME: 섹션명
SUBSECTIONS: 소단락1 || 소단락2
SECTION_END

규칙:
- 고정 섹션은 출력하지 마라. 동적 본문 섹션만 출력하라.
- 섹션은 3개 이상 4개 이하로 제안하라.
- 각 섹션은 소단락 2~4개를 제안하라.
- "관련 연구" 절이 필요하면 넣되, 반드시 그 이후에 본 연구가 직접 도출하거나 제안하는 절이 오게 하라.
- JSON 금지.
""".strip()


def parse_outline_text(raw_text: str) -> dict:
    note = ""
    sections: list[dict] = []
    current: dict | None = None
    for raw_line in raw_text.strip().splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("OUTLINE_NOTE:"):
            note = line.split(":", 1)[1].strip()
            continue
        if line == "SECTION_START":
            current = {"name": "", "subsections": []}
            continue
        if line == "SECTION_END":
            if current and current.get("name"):
                sections.append(current)
            current = None
            continue
        if current is None:
            continue
        if line.startswith("NAME:"):
            current["name"] = line.split(":", 1)[1].strip()
        elif line.startswith("SUBSECTIONS:"):
            current["subsections"] = split_pipe_values(line.split(":", 1)[1].strip())
    return {"note": note, "sections": sections}


def repair_outline_text(raw_text: str, topic: str, selected_rows: list[dict]) -> dict:
    repair_prompt = f"""다음 응답을 같은 의미로 다시 정리하되, 반드시 아래 형식만 사용하라.

형식:
OUTLINE_NOTE: 설명
SECTION_START
NAME: 섹션명
SUBSECTIONS: 소단락1 || 소단락2
SECTION_END

주제: {topic}

참고 논문 요약:
{build_paper_context(selected_rows[:4])}

원본:
{raw_text}
"""
    repaired = LLMClient().ask(repair_prompt, model="claude-sonnet-4-6", max_tokens=OUTLINE_MAX_TOKENS)
    return parse_outline_text(repaired)


def build_report_outline(topic: str = DEFAULT_WRITER_TOPIC, selected_rows: list[dict] | None = None) -> dict:
    if topic in OUTLINE_CACHE:
        return OUTLINE_CACHE[topic]

    dynamic_sections: list[dict] = []
    note = ""
    if selected_rows:
        prompt = build_outline_prompt(topic, selected_rows)
        raw_response = LLMClient().ask(prompt, model="claude-sonnet-4-6", max_tokens=OUTLINE_MAX_TOKENS)
        try:
            parsed = parse_outline_text(raw_response)
        except Exception:
            parsed = repair_outline_text(raw_response, topic, selected_rows)
        dynamic_sections = parsed.get("sections", [])
        note = parsed.get("note", "")

    if not dynamic_sections:
        dynamic_sections = [
            {"name": f"{topic}의 핵심 쟁점", "subsections": ["핵심 문제", "주요 분석 축"]},
            {"name": "관련 연구 검토", "subsections": ["기존 연구 흐름", "본 주제에 대한 시사점"]},
            {"name": f"{topic}에 대한 분석 기준 도출", "subsections": ["기준 제안", "적용 관점"]},
            {"name": f"{topic}에 대한 제안 및 활용 방안", "subsections": ["핵심 제안", "활용 방향"]},
        ]
        note = "기본 학술논문형 동적 목차"

    sections = ["제목", "초록", "서론"] + [item["name"] for item in dynamic_sections] + ["논의", "결론", "참고문헌"]
    section_plan = dict(FIXED_SECTION_PLAN)
    for item in dynamic_sections:
        section_plan[item["name"]] = item.get("subsections", []) or [item["name"]]
    aliases = dict(BASE_SECTION_ALIASES)
    for item in dynamic_sections:
        name = item["name"]
        aliases[name] = [name]

    outline = {
        "topic": topic,
        "note": note,
        "sections": sections,
        "section_plan": section_plan,
        "aliases": aliases,
        "dynamic_sections": dynamic_sections,
    }
    OUTLINE_CACHE[topic] = outline
    return outline


def print_report_outline(outline: dict) -> None:
    print("\n한국어 논문형 목차 템플릿")
    print(f"주제: {outline.get('topic', '')}")
    if outline.get("note"):
        print(f"목차 메모: {outline.get('note')}")
    for index, section in enumerate(outline.get("sections", []), 1):
        print(f"{index}. {section}")


def infer_section_role(section_name: str, subsection_name: str) -> str:
    name = f"{section_name} {subsection_name}"
    lowered = name.lower()
    if "서론" in section_name:
        return "서론에서는 주제의 중요성과 연구 필요성을 먼저 세우고, 왜 이 논문 초안이 필요한지에 초점을 맞출 것."
    if "관련 연구" in name or "선행연구" in name:
        return "관련 연구 절은 참고 문헌을 정리하는 절로 제한하고, 각 연구를 언급하더라도 본 연구에 주는 의미를 연결할 것."
    if "문제" in name or "쟁점" in name:
        return "이 절에서는 주제의 핵심 문제를 독립된 문제 장처럼 분명히 제시할 것."
    if "기준" in name or "관점" in name or "분석" in name:
        return "이 절에서는 기존 연구를 요약하는 데서 끝나지 말고, 본 논문이 직접 분석 기준이나 관점을 도출하는 형태로 작성할 것."
    if "프레임워크" in name or "제안" in name or "활용 방안" in name or "적용" in name:
        return "이 절은 본 논문의 핵심 제안 장이다. 구조적 제안, 적용 절차, 활용 방안을 본 논문이 직접 제시하는 문장으로 작성할 것."
    if "논의" in section_name:
        return "논의에서는 요약이 아니라 해석과 주장 중심으로 쓰고, 본 논문의 시사점과 한계를 분명히 드러낼 것."
    if "결론" in section_name:
        return "결론에서는 단순 반복이 아니라 본 논문이 도출한 내용의 의미와 향후 방향을 정리할 것."
    return "본 논문의 논지 전개에 도움이 되는 방향으로 작성할 것."


def build_subsection_bullet_prompt(
    topic: str,
    section_name: str,
    subsection_name: str,
    selected_rows: list[dict],
) -> str:
    paper_text = build_paper_context(selected_rows)
    section_role = infer_section_role(section_name, subsection_name)
    return f"""당신은 한국어 논문 초안 작성을 위한 구조 메모 작성자이다.

주제: {topic}
현재 섹션: {section_name}
현재 소단락: {subsection_name}

[참고 논문 데이터]
{paper_text}

[지시]
- 참고 논문은 근거 자료일 뿐이며, 최종 목표는 "본 논문 초안"을 쓰는 것이다.
- 지금은 "{section_name}"의 "{subsection_name}"에 들어갈 핵심 bullet만 생성할 것.
- 4~6개의 bullet로 정리할 것.
- bullet은 "이 소단락에서 주장해야 할 핵심", "근거로 쓸 연구 포인트", "본 논문에 주는 의미"를 포함할 것.
- 논문별 나열 메모보다 논지 전개용 메모를 우선할 것.
- {section_role}"""


def build_subsection_expansion_prompt(
    topic: str,
    section_name: str,
    subsection_name: str,
    bullets_text: str,
    existing_section_text: str,
) -> str:
    section_role = infer_section_role(section_name, subsection_name)
    return f"""당신은 한국어 논문 초안 본문을 작성하는 Writer Agent이다.

주제: {topic}
현재 섹션: {section_name}
현재 소단락: {subsection_name}

[현재까지 작성된 섹션 내용]
{existing_section_text}

[핵심 bullet]
{bullets_text}

[지시]
- 위 bullet만 바탕으로 "{section_name}"의 "{subsection_name}" 부분을 한국어 논문 문체로 작성할 것.
- 기존 섹션 내용과 자연스럽게 이어지도록 할 것.
- 이것은 "문헌 정리문"이 아니라 "본 논문의 초안"이라는 점을 유지할 것.
- 개별 논문 소개를 길게 나열하지 말고, 본 연구의 문제의식과 주장 전개를 중심으로 서술할 것.
- 각 문단은 가능하면 다음 흐름을 따를 것: 핵심 주장 제시 -> 선행연구 근거 연결 -> 본 논문에 주는 의미.
- "A는 ..., B는 ..." 식의 연속 나열은 피하고, 정말 필요할 때만 짧게 근거로 사용할 것.
- 독자적 논지 표현(예: '본 연구는', '이러한 점에서', '따라서', '결국')을 적절히 사용할 것.
- {section_role}
- 문장이 중간에 끊기지 않게 완결하게 작성할 것."""


def print_writer_prompt_preview(prompt: str, max_length: int = 2000) -> None:
    print("\nWriter 프롬프트 미리보기")
    safe_print(prompt[:max_length])
    if len(prompt) > max_length:
        print("\n... (이하 생략)")


def generate_text(prompt: str, max_tokens: int) -> str:
    client = LLMClient()
    return client.ask(prompt, model="claude-sonnet-4-6", max_tokens=max_tokens)


def build_references_section(selected_rows: list[dict]) -> str:
    lines = ["# 참고문헌", ""]
    for row in selected_rows:
        authors = ", ".join(row.get("authors", [])) if row.get("authors") else "저자 미상"
        year = row.get("year", "연도 미상")
        title = row.get("title", "제목 미상")
        source = row.get("source", "")
        url = row.get("url", "")
        citation = f"{authors} ({year}). {title}."
        if source:
            citation += f" {source}."
        if url:
            citation += f" {url}"
        lines.append(citation)
        lines.append("")
    return "\n".join(lines).strip()


def build_title_section(topic: str, selected_rows: list[dict]) -> str:
    paper_text = build_paper_context(selected_rows)
    prompt = f"""주제: {topic}

[논문 데이터]
{paper_text}

이 자료를 참고하여 한국어 학술 논문 제목 한 줄만 제시하시오.
단, 제목은 단순한 문헌 정리나 비교 보고서처럼 보이지 말고,
"본 논문이 어떤 문제를 다루고 어떤 관점으로 접근하는지"가 드러나야 한다.
출력은 제목 한 줄만 작성하시오.
"""
    title = generate_text(prompt, max_tokens=120).strip()
    return f"# 제목\n\n{title}"


def build_section_heading(section_name: str) -> str:
    if section_name == "제목":
        return "# 제목"
    return f"# {section_name}"


def sanitize_generated_subsection_text(text: str, section_name: str, subsection_name: str) -> str:
    cleaned_lines: list[str] = []
    duplicate_patterns = {
        section_name.strip(),
        subsection_name.strip(),
        f"# {section_name.strip()}",
        f"## {section_name.strip()}",
        f"# {subsection_name.strip()}",
        f"## {subsection_name.strip()}",
    }
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line in duplicate_patterns:
            continue
        cleaned_lines.append(raw_line)
    return "\n".join(cleaned_lines).strip()


def build_section_text(
    topic: str,
    section_name: str,
    selected_rows: list[dict],
    outline: dict,
) -> str:
    if section_name == "제목":
        return build_title_section(topic, selected_rows)
    if section_name == "참고문헌":
        return build_references_section(selected_rows)

    section_lines = [build_section_heading(section_name), ""]
    current_body = ""
    section_plan = outline.get("section_plan", {})
    for subsection_name in section_plan.get(section_name, [section_name]):
        bullet_prompt = build_subsection_bullet_prompt(
            topic=topic,
            section_name=section_name,
            subsection_name=subsection_name,
            selected_rows=selected_rows,
        )
        bullets_text = generate_text(bullet_prompt, max_tokens=BULLET_MAX_TOKENS)
        subsection_prompt = build_subsection_expansion_prompt(
            topic=topic,
            section_name=section_name,
            subsection_name=subsection_name,
            bullets_text=bullets_text,
            existing_section_text=current_body,
        )
        subsection_text = generate_text(subsection_prompt, max_tokens=SUBSECTION_MAX_TOKENS).strip()
        subsection_text = sanitize_generated_subsection_text(subsection_text, section_name, subsection_name)
        if subsection_text:
            section_lines.append(subsection_text)
            section_lines.append("")
            current_body = "\n\n".join(line for line in section_lines[1:] if line.strip())
    return "\n".join(section_lines).strip()


def assemble_draft(section_outputs: list[tuple[str, str]]) -> str:
    parts = [content.strip() for _, content in section_outputs if content.strip()]
    return "\n\n---\n\n".join(parts)


def print_report_draft_preview(draft: str) -> None:
    print("\n생성된 보고서 초안")
    safe_print(draft)


def check_synthesis_markers(draft: str, topic: str = DEFAULT_WRITER_TOPIC) -> dict:
    found_markers = [marker for marker in SYNTHESIS_MARKERS if marker in draft]
    outline = OUTLINE_CACHE.get(topic, {})
    dynamic_sections = [item["name"] for item in outline.get("dynamic_sections", [])]
    required_sections = []
    if dynamic_sections:
        required_sections.extend(dynamic_sections[:2])
    required_sections.extend(["논의", "결론"])
    aliases = outline.get("aliases", BASE_SECTION_ALIASES)
    section_hits = {
        section: any(alias in draft for alias in aliases.get(section, [section]))
        for section in required_sections
    }
    return {
        "found_markers": found_markers,
        "section_hits": section_hits,
        "is_synthesis_visible": len(found_markers) >= 3,
    }


def print_synthesis_check(result: dict) -> None:
    print("\n종합 분석 반영 확인")
    print(f"비교·종합 표현 발견: {result.get('found_markers', [])}")
    print(f"주요 섹션 포함 여부: {result.get('section_hits', {})}")
    if result.get("is_synthesis_visible"):
        print("종합 분석 표현이 초안에 반영된 것으로 확인됨")
    else:
        print("종합 분석 표현이 충분하지 않을 수 있음")


def slugify_topic(topic: str) -> str:
    normalized = topic.strip().lower()
    normalized = re.sub(r"[^a-z0-9가-힣]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or "report"


def save_report_draft(draft: str, topic: str) -> Path:
    REPORT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"{slugify_topic(topic)}_{timestamp}.md"
    save_path = REPORT_OUTPUT_DIR / filename
    save_path.write_text(draft, encoding="utf-8")
    return save_path


def save_run_writer_outputs(
    *,
    run_id: str,
    draft: str,
    report_path: Path,
) -> None:
    run_dir = get_run_output_dir(run_id)
    writer_payload = {
        "gptDraft": "",
        "claudeDraft": draft,
        "commonHighlights": [],
        "differentHighlights": [],
        "reviewResult": "",
        "mergedReport": draft,
    }
    write_json(run_dir / "writer_output.json", writer_payload)
    write_markdown(run_dir / "report.md", draft)


def find_latest_report_file(topic: str) -> Path | None:
    topic_slug = slugify_topic(topic)
    candidates = sorted(REPORT_OUTPUT_DIR.glob(f"{topic_slug}_*.md"))
    if not candidates:
        return None
    return candidates[-1]


def check_report_sections(draft: str, topic: str = DEFAULT_WRITER_TOPIC) -> dict:
    outline = OUTLINE_CACHE.get(topic, {})
    aliases = outline.get("aliases", BASE_SECTION_ALIASES)
    section_names = outline.get("sections", FIXED_SECTIONS)
    section_hits: dict[str, bool] = {}
    for section in section_names:
        section_hits[section] = any(alias in draft for alias in aliases.get(section, [section]))
    return section_hits


def validate_writer_output(draft: str, saved_path: Path, synthesis_check: dict, topic: str) -> dict:
    section_hits = check_report_sections(draft, topic=topic)
    has_draft = bool(draft.strip())
    file_saved = saved_path.exists()
    sections_ok = all(section_hits.values())
    synthesis_ok = synthesis_check.get("is_synthesis_visible", False)
    is_valid = has_draft and file_saved and sections_ok and synthesis_ok
    return {
        "has_draft": has_draft,
        "file_saved": file_saved,
        "section_hits": section_hits,
        "sections_ok": sections_ok,
        "synthesis_ok": synthesis_ok,
        "is_valid": is_valid,
    }


def print_writer_validation_result(result: dict, saved_path: Path) -> None:
    print("\n42번 테스트 검증 결과")
    print(f"초안 생성 여부: {'정상' if result.get('has_draft') else '실패'}")
    print(f"저장 파일 여부: {'정상' if result.get('file_saved') else '실패'}")
    print(f"섹션 포함 여부: {result.get('section_hits', {})}")
    print(f"비교·종합 표현 반영 여부: {'정상' if result.get('synthesis_ok') else '보완 필요'}")
    print(f"저장 경로: {saved_path}")
    if result.get("is_valid"):
        print("Writer Agent 테스트 완료")
    else:
        print("Writer Agent 테스트 미통과 - 일부 항목 보완 필요")


def run_writer_output_test(draft: str, topic: str = DEFAULT_WRITER_TOPIC) -> dict:
    saved_path = find_latest_report_file(topic)
    synthesis_check = check_synthesis_markers(draft, topic=topic)
    if saved_path is None:
        result = {
            "has_draft": bool(draft.strip()),
            "file_saved": False,
            "section_hits": check_report_sections(draft, topic=topic),
            "sections_ok": False,
            "synthesis_ok": synthesis_check.get("is_synthesis_visible", False),
            "is_valid": False,
        }
        print_writer_validation_result(result, Path("없음"))
        return result
    result = validate_writer_output(draft, saved_path, synthesis_check, topic=topic)
    print_writer_validation_result(result, saved_path)
    return result


def validate_writer_input(rows: list[dict]) -> bool:
    is_valid = True
    for index, row in enumerate(rows, 1):
        missing = find_missing_fields(row, REQUIRED_WRITER_FIELDS)
        if missing:
            is_valid = False
            print(f"[경고] {index}번 논문 입력 누락 필드: {missing}")
    return is_valid


def load_writer_input_data() -> list[dict]:
    relevance_rows = load_json_file(RELEVANCE_PATH)
    summary_rows = load_json_file(SUMMARY_PATH)
    if not relevance_rows or not summary_rows:
        return []
    return merge_writer_inputs(relevance_rows, summary_rows)


def run_writer_input_check() -> list[dict]:
    rows = load_writer_input_data()
    if not rows:
        print("Writer 입력 데이터를 불러오지 못했습니다.")
        return []
    print_writer_input_preview(rows)
    if validate_writer_input(rows):
        print("\nWriter Agent 입력 필드 확인 완료")
    else:
        print("\nWriter Agent 입력 필드 일부 누락")
    return rows


def run_writer_input_build(score_threshold: float = DEFAULT_WRITER_SCORE_THRESHOLD) -> list[dict]:
    rows = load_writer_input_data()
    if not rows:
        print("Writer 입력 데이터를 불러오지 못했습니다.")
        return []
    selected_rows = filter_writer_candidates(rows, score_threshold=score_threshold)
    print_writer_candidate_list(selected_rows, score_threshold=score_threshold)
    print(f"\nWriter 입력 구성 완료: {len(selected_rows)}편 선별")
    return selected_rows


def run_report_outline_demo(topic: str | None = None) -> dict:
    topic = resolve_writer_topic(topic)
    selected_rows = run_writer_input_build()
    outline = build_report_outline(topic=topic, selected_rows=selected_rows)
    print_report_outline(outline)
    print("\n목차 템플릿 적용 완료")
    return outline


def run_writer_preparation_flow(
    topic: str | None = None,
    score_threshold: float = DEFAULT_WRITER_SCORE_THRESHOLD,
) -> dict:
    print("Writer 준비 흐름 시작")
    topic = resolve_writer_topic(topic)
    all_rows = run_writer_input_check()
    if not all_rows:
        return {}
    selected_rows = filter_writer_candidates(all_rows, score_threshold=score_threshold)
    print_writer_candidate_list(selected_rows, score_threshold=score_threshold)
    print(f"\nWriter 입력 구성 완료: {len(selected_rows)}편 선별")

    outline = build_report_outline(topic=topic, selected_rows=selected_rows)
    print_report_outline(outline)
    print("\n목차 템플릿 적용 완료")

    dynamic_sections = outline.get("dynamic_sections", [])
    if dynamic_sections:
        preview_section = dynamic_sections[0]["name"]
        preview_subsection = dynamic_sections[0]["subsections"][0]
    else:
        preview_section = "서론"
        preview_subsection = "연구 필요성"
    preview_prompt = build_subsection_bullet_prompt(
        topic=topic,
        section_name=preview_section,
        subsection_name=preview_subsection,
        selected_rows=selected_rows,
    )
    print_writer_prompt_preview(preview_prompt)
    print("\n프롬프트 생성 완료")
    return {"topic": topic, "selected_rows": selected_rows, "outline": outline}


def run_writer_draft_generation(
    topic: str | None = None,
    score_threshold: float = DEFAULT_WRITER_SCORE_THRESHOLD,
    run_id: str | None = None,
) -> str:
    topic = resolve_writer_topic(topic)
    preparation = run_writer_preparation_flow(topic=topic, score_threshold=score_threshold)
    if not preparation:
        print("Writer 초안 생성 준비에 실패했습니다.")
        return ""

    selected_rows = preparation["selected_rows"]
    outline = preparation["outline"]

    section_outputs: list[tuple[str, str]] = []
    for section_name in outline["sections"]:
        print(f"\n섹션 생성 중: {section_name}")
        section_text = build_section_text(
            topic=topic,
            section_name=section_name,
            selected_rows=selected_rows,
            outline=outline,
        )
        section_outputs.append((section_name, section_text))

    draft = assemble_draft(section_outputs)
    print_report_draft_preview(draft)
    synthesis_check = check_synthesis_markers(draft, topic=topic)
    print_synthesis_check(synthesis_check)
    saved_path = save_report_draft(draft, topic=topic)
    if run_id:
        save_run_writer_outputs(run_id=run_id, draft=draft, report_path=saved_path)
    print(f"\n초안 저장 완료: {saved_path}")
    print("\n보고서 초안 생성 완료")
    return draft


def prompt_topic(default_topic: str = DEFAULT_WRITER_TOPIC) -> str:
    topic = input(f"연구 주제를 입력하세요 (기본값: {default_topic}): ").strip()
    return topic or default_topic


if __name__ == "__main__":
    run_writer_draft_generation()
