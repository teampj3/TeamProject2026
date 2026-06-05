"""Shared Anthropic client for agent modules."""

from __future__ import annotations

import json
import os
import re
import time

from anthropic import APIConnectionError, APITimeoutError, Anthropic
from dotenv import load_dotenv

load_dotenv()


def _env_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _extract_topic(prompt: str) -> str:
    patterns = [
        r"주제:\s*(.+)",
        r"\[사용자 주제\]\s*(.+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, prompt)
        if match:
            return match.group(1).strip()
    return "AI 에이전트"


def _extract_section(prompt: str) -> str:
    patterns = [
        r"현재 섹션:\s*(.+)",
        r"target_section\":\s*\"(.+?)\"",
    ]
    for pattern in patterns:
        match = re.search(pattern, prompt)
        if match:
            return match.group(1).strip()
    return "논의"


def _mock_outline_response(topic: str) -> str:
    return f"""OUTLINE_NOTE: {topic} 주제를 학술 논문 구조로 정리한 기본 목차

SECTION_START
NAME: {topic}의 개념과 배경
SUBSECTIONS: 핵심 개념 || 연구 필요성
SECTION_END
SECTION_START
NAME: {topic}의 적용 구조와 사례
SUBSECTIONS: 적용 방식 || 대표 사례 || 한계
SECTION_END
SECTION_START
NAME: {topic}의 시사점과 발전 방향
SUBSECTIONS: 실무 시사점 || 향후 연구 방향
SECTION_END"""


def _mock_reader_response() -> str:
    return json.dumps(
        {
            "purpose": "이 논문은 주제와 관련된 핵심 문제를 정의하고 해결 방향을 제시한다.",
            "method": "관련 개념을 정리한 뒤 사례와 구조를 비교하는 방식으로 분석을 수행한다.",
            "result": "제안한 접근이 이해 가능성과 적용 가능성 측면에서 유의미한 장점을 보인다고 보고한다.",
            "limitation": "평가 범위가 제한적이며 실제 대규모 환경에 대한 추가 검증이 필요하다.",
        },
        ensure_ascii=False,
    )


def _mock_review_response() -> str:
    return json.dumps(
        {
            "logic_score": 4,
            "duplication_score": 4,
            "structure_score": 4,
            "awkward_expressions": [],
            "incomplete_sentences": [],
            "feedback_summary": "초안의 구조와 논리 흐름은 전반적으로 안정적이며, 세부 근거를 보강하면 바로 활용 가능한 수준입니다.",
        },
        ensure_ascii=False,
    )


def _mock_visualization_response(topic: str) -> str:
    return json.dumps(
        {
            "need_visual": "yes",
            "need_reason": f"{topic}의 핵심 요소와 적용 구조를 표와 개념도로 정리하면 이해가 쉬워집니다.",
            "visuals": [
                {
                    "visual_id": "visual_1",
                    "visual_type": "table",
                    "title": f"{topic} 핵심 비교 요약",
                    "target_section": "논의",
                    "choice_reason": "정성적 차이를 한 번에 비교하기 적합합니다.",
                    "data_spec": {
                        "columns": ["항목", "핵심 내용", "시사점"],
                        "rows": [
                            ["개념", "주요 역할과 범위를 정의", "분석 기준 정립"],
                            ["적용", "실무 흐름에 맞춘 활용 구조", "현장 적용성 향상"],
                            ["한계", "비용과 평가 범위 제약", "추가 검증 필요"],
                        ],
                    },
                },
                {
                    "visual_id": "visual_2",
                    "visual_type": "concept_diagram",
                    "title": f"{topic} 구성 요소 개요",
                    "target_section": "결론",
                    "choice_reason": "핵심 구성 요소와 관계를 직관적으로 보여주기 적합합니다.",
                    "data_spec": {
                        "central_topic": topic,
                        "branches": [
                            {"label": "구조", "detail": "에이전트와 파이프라인 구성"},
                            {"label": "활용", "detail": "실무 적용 흐름"},
                            {"label": "한계", "detail": "비용과 품질 제약"},
                            {"label": "확장", "detail": "후속 개선 방향"},
                        ],
                    },
                },
            ],
        },
        ensure_ascii=False,
    )


def _mock_section_response(prompt: str) -> str:
    topic = _extract_topic(prompt)
    section = _extract_section(prompt)
    return (
        f"{section}에서는 {topic}와 관련된 핵심 쟁점을 정리하고, 선행 연구와 적용 사례를 연결하여 "
        f"본 논문의 분석 관점을 분명히 제시한다. 특히 문제 정의, 적용 구조, 한계와 시사점을 한 흐름으로 "
        f"묶어 설명함으로써 단순한 문헌 나열이 아니라 논지 중심의 초안을 구성한다.\n\n"
        f"또한 본 절은 {topic}가 실제 환경에서 어떻게 활용될 수 있는지와 함께, 품질 검증과 운영 측면에서 "
        f"어떤 보완이 필요한지를 함께 다룬다. 이를 통해 이후 논의와 결론에서 활용 가능한 정리된 근거를 제공한다."
    )


def build_mock_response(prompt: str) -> str:
    topic = _extract_topic(prompt)

    if "need_visual" in prompt and "visual_type" in prompt and "data_spec" in prompt:
        return _mock_visualization_response(topic)
    if '"purpose"' in prompt and '"method"' in prompt and '"result"' in prompt and '"limitation"' in prompt:
        return _mock_reader_response()
    if '"logic_score"' in prompt and '"duplication_score"' in prompt and '"structure_score"' in prompt:
        return _mock_review_response()
    if "OUTLINE_NOTE:" in prompt and "SECTION_START" in prompt:
        return _mock_outline_response(topic)
    if "한국어 학술 논문 제목 한 줄" in prompt or "제목 한 줄만 제시" in prompt:
        return f"{topic} 기반 멀티 에이전트 파이프라인 설계와 적용 분석"
    return _mock_section_response(prompt)


class LLMClient:
    """Small wrapper so agents can share one Claude client interface."""

    def __init__(self) -> None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        self.mock_mode = (
            _env_enabled("TEAMPROJECT_USE_MOCK_LLM")
            or _env_enabled("TEAMPROJECT_USE_MOCK_PIPELINE")
            or os.getenv("TEAMPROJECT_LLM_MODE", "").strip().lower() == "mock"
        )
        # 여러 Agent가 같은 Claude 클라이언트를 재사용하도록 공통 래퍼를 둡니다.
        # 네트워크가 잠깐 흔들려도 바로 실패하지 않게 timeout을 조금 넉넉하게 둡니다.
        self.client = None if self.mock_mode or not api_key else Anthropic(api_key=api_key, timeout=90.0)

    def ask(self, prompt: str, model: str = "claude-sonnet-4-6", max_tokens: int = 500) -> str:
        if self.mock_mode:
            return build_mock_response(prompt)

        if self.client is None:
            raise RuntimeError("ANTHROPIC_API_KEY is missing and mock mode is disabled.")

        # Claude 요청은 최대 3번까지 재시도합니다.
        # 연결/타임아웃 계열 오류만 재시도하고, 그 외 오류는 즉시 올립니다.
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = self.client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.content[0].text
            except (APITimeoutError, APIConnectionError) as error:
                last_error = error
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise

        if last_error is not None:
            raise last_error
        raise RuntimeError("Claude response was not returned.")
