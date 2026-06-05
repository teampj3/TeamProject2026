# Review-Writer 평가 루프 개선 정리

## 개요
이 문서는 기존 `Writer -> Review -> 재작성` 흐름을 `Evals / LLM-as-a-judge` 관점으로 개선한 내용을 정리한다.  
핵심 목표는 단순 생성 이후 수동 확인에 머무르지 않고, **생성 -> 평가 -> 수정 -> 재평가**의 자동 품질 개선 루프를 만드는 것이다.

## 이전 구조
- Writer가 논문 초안을 생성한다.
- Review Agent가 초안을 읽고 점수와 피드백을 만든다.
- 기준 점수 미달이면 Writer가 다시 초안을 생성한다.
- 전체적으로 동작은 가능했지만 다음 한계가 있었다.

### 이전 한계
- Review 평가 기준이 상대적으로 단순했다.
- `PASS/FAIL` 판정이 있어도 왜 통과/실패했는지 구조적으로 설명하기 어려웠다.
- 재작성 시 초안 전체를 다시 생성하는 비중이 커서 시간이 오래 걸렸다.
- LLM 응답 파싱이 깨지면 review 품질이 급격히 떨어질 수 있었다.
- 회차별 개선 과정을 `evaluation trace`처럼 설명하기 어려웠다.

## 현재 구조
현재는 Review Agent를 **rubric 기반 judge**로 재정의하고, Writer-Review 루프를 평가 중심으로 강화했다.

### 핵심 변경점
1. Review Agent를 `LLM-as-a-judge` 역할로 정리
2. rubric 기반 평가 점수 도입
3. `PASS/FAIL` 기준 명확화
4. 문제 섹션만 골라서 재작성하는 targeted revision 도입
5. 회차별 로그 저장 강화
6. LLM 응답 파싱 실패 시 fallback 평가 추가

## 평가 기준(Rubric)
Review Agent는 아래 5개 축을 1~5점으로 평가한다.

- `logic_score`
  - 논리 전개와 문단 간 연결성
- `structure_score`
  - 섹션 구성과 필수 섹션 충족도
- `academic_style_score`
  - 학술 문체, 번역투, 어색한 표현 여부
- `research_focus_score`
  - 선행연구 나열이 아니라 본 연구 중심 서술인지
- `completeness_score`
  - 미완성 문장, 끊긴 문장, 설명 누락 정도

추가로 다음 항목도 함께 생성한다.

- `missing_sections`
- `incomplete_sentences`
- `awkward_expressions`
- `strengths`
- `priority_fixes`
- `feedback_summary`
- `judge_notes`

## 통과 기준
- 평균 점수 `3.5 이상`
- 필수 섹션 누락 없음
- 미완성 문장 없음

이 조건을 만족하면 `PASS`, 그렇지 않으면 `FAIL`로 판정한다.

## 재작성 방식 변화
### 이전
- FAIL이면 초안 전체를 다시 쓰는 경우가 많았다.

### 현재
- Review 결과를 바탕으로 문제 섹션만 식별한다.
- `미완성 문장`, `어색한 표현`, `누락 섹션`이 걸린 부분만 다시 생성한다.
- 즉 `전체 재작성`보다 `섹션 단위 targeted revision`에 가깝다.

## fallback 평가
LLM 응답이 JSON 형식으로 깨지거나 파싱이 실패해도 파이프라인이 멈추지 않도록 fallback 로직을 추가했다.

fallback에서는 다음을 규칙 기반으로 점검한다.

- 필수 섹션 누락 여부
- 미완성 문장 여부
- 어색한 표현 여부

이를 바탕으로 기본 점수와 요약 피드백을 생성해 `review_result.json`에 저장한다.

## 회차별 로그
Review-Writer 루프는 회차별로 다음 정보를 로그에 남긴다.

- round
- draft_path
- review_path
- average_score
- rewrite_requested
- rewrite_reasons
- target_sections
- overall_verdict

이 로그는 `outputs/logs/*review_writer_loop*.json`에 저장된다.

## 관련 파일
### `run_pipeline.py`
- 전체 파이프라인 오케스트레이션
- Review-Writer 루프 실행
- 재작성 여부 판단
- 회차별 로그 저장

### `agents/write_agent.py`
- 초안 생성
- 섹션 단위 재작성
- 기존 초안에 부분 교체 적용

### `agents/review_agent.py`
- rubric 기반 Review Agent
- LLM judge 프롬프트 생성
- review 결과 파싱
- fallback 평가
- `review_result.json` 저장

## 데모 설명용 한 문장
본 시스템은 초안을 단순 생성하는 데 그치지 않고, **LLM-as-a-judge 기반의 평가 루프를 통해 논리성·구조·학술 문체·본 연구 중심성·완결성을 자동 평가한 뒤 필요 시 문제 섹션만 재작성하는 멀티 에이전트 품질 개선 구조**를 갖는다.
