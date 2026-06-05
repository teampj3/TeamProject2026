# Agent Runtime 스타일 파이프라인 리팩터링 정리

## 개요
이 문서는 기존 멀티 에이전트 파이프라인을 `Agent Runtime / Agents SDK` 관점에서 더 설명 가능하고 추적 가능한 구조로 리팩터링한 내용을 정리한다.

핵심 목적은 다음과 같다.

- 단계별 상태를 하나의 공통 context에서 관리
- 각 Agent를 독립 step/task처럼 보이게 정리
- Review-Writer loop를 별도 workflow step으로 승격
- trace/log를 구조화해 long-running workflow로 설명 가능하게 만들기

## 이전 구조
기존 파이프라인은 다음과 같은 성격에 가까웠다.

- `run_pipeline.py` 안에서 함수들을 순차적으로 호출
- 단계별 결과는 대부분 파일 경로를 각 Agent가 직접 다시 찾음
- Search/Reader/Relevance/Writer/Visualization/Archive/DOCX가 연결되긴 하지만, 공통 상태 객체가 없음
- step trace가 부분 로그 수준에 머무름
- 발표 시 “스크립트 순차 실행”처럼 보일 가능성이 큼

## 현재 구조
현재는 `PipelineContext + step 함수 + trace + tool wrapper` 중심 구조로 정리되었다.

### 1. PipelineContext 도입
공통 상태를 다음 필드로 관리한다.

- `topic`
- `search_result_path`
- `summary_result_path`
- `relevance_result_path`
- `draft_path`
- `review_result_path`
- `visual_plan_path`
- `visualized_report_path`
- `archive_path`
- `archive_manifest_path`
- `docx_path`
- `loop_log_path`
- `trace_path`

즉 각 Agent가 파일을 제각각 찾기보다, `context`를 받아 읽고 갱신하는 방식으로 정리되었다.

### 2. step/task 분리
파이프라인을 다음 step 함수로 명시화했다.

- `search_step(context)`
- `reader_step(context)`
- `relevance_step(context)`
- `writer_step(context)`
- `review_loop_step(context)`
- `visualization_step(context)`
- `archive_step(context)`
- `export_step(context)`

이 구조 덕분에 발표 시 “멀티 에이전트 workflow”라는 설명이 쉬워졌다.

### 3. tool wrapper 추가
Agent Runtime 관점에서 직접 파일과 함수를 뒤지는 대신, 아래와 같은 래퍼를 두었다.

- `save_pipeline_context`
- `save_runtime_trace`
- `load_latest_report`
- `read_review_result`
- `archive_results`
- `export_docx`

즉 기존 로직을 버린 것이 아니라, **도구처럼 호출할 수 있는 레이어**를 하나 추가한 셈이다.

### 4. Review-Writer loop를 runtime workflow로 승격
이전에도 피드백 루프는 있었지만, 현재는 별도 step으로 명확히 보이도록 정리되었다.

흐름:
1. Writer 1차 초안 생성
2. Review judge 실행
3. `PASS`면 종료
4. `FAIL`이면 문제 섹션만 재작성
5. 최대 2회 반복
6. 최종 초안 확정

즉 단순한 함수 재호출이 아니라, **에이전트 품질 개선 workflow**로 설명할 수 있다.

### 5. tracing/logging 강화
각 step마다 아래 정보를 trace에 남긴다.

- `step_name`
- `started_at`
- `ended_at`
- `status`
- `input_paths`
- `output_paths`
- `verdict`
- `average_score`
- `rewrite_requested`
- `note`

이 trace는 `outputs/logs/*agent_runtime_trace*.json`에 저장된다.

### 6. long-running workflow 메시지 정리
단계별 진행 상태를 명시적으로 출력한다.

예:
- `[1/8] Search`
- `[2/8] Reader`
- `[3/8] Relevance`
- `[4/8] Writer`
- `[5/8] Review Loop`
- `[6/8] Visualization`
- `[7/8] Archive`
- `[8/8] DOCX Export`

즉 “작업을 끝까지 수행하는 agent system”이라는 메시지가 더 분명해졌다.

## 관련 파일
### `services/agent_runtime_service.py`
새로 추가된 runtime 공통 서비스 파일이다.

포함 기능:
- `PipelineContext`
- context 저장/직렬화
- step trace 기록
- trace 파일 저장
- latest report / review result / archive / export wrapper

### `run_pipeline.py`
기존 단순 순차 실행 파일에서, runtime orchestrator 역할로 정리되었다.

주요 변화:
- step 함수 분리
- context 기반 상태 갱신
- trace 기록
- Review-Writer loop를 독립 workflow step으로 운영

## 이전 대비 핵심 차이 요약
### 이전
- 각 Agent가 파일을 직접 다시 찾음
- 순차 실행 중심
- 상태 공유 구조 약함
- trace가 약함
- workflow 설명력이 낮음

### 현재
- `PipelineContext`로 공통 상태 공유
- step/task 구조 명시화
- tool wrapper 도입
- Review loop를 하나의 workflow step으로 정리
- 단계별 trace/log 구조화
- Agent Runtime 스타일로 설명 가능

## 데모 설명용 한 문장
본 시스템은 Search, Reader, Relevance, Writer, Review, Visualization, Archive, DOCX Export를 각각 독립 step으로 운영하고, `PipelineContext`와 step trace를 통해 상태와 실행 이력을 공유하는 **Agent Runtime 스타일의 멀티 에이전트 workflow**로 구성된다.
