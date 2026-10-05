# jobloop — 프로젝트 컨텍스트 (Claude Code용)

## 이 프로젝트가 무엇인가
한 명의 후보자를 위한 취업 지원 문서(CV, 지원서 문항 답변, 커버레터)를 생성하고 **검증**하는 LangGraph 루프.
핵심 가치는 생성이 아니라 검증이다. 없는 경력을 만들어내는 문장이 단 하나라도 제출되면 실패다.
개인 데이터(`profile_db.json`, `lessons.json`, `applications/`, `runs/`, JD 파일)는 저장소에 넣지 않는다 —
`profile_db.example.json`, `lessons.example.json`은 가상 인물 예시다.

## 아키텍처 (README.md에 상세)
공고 링크 → `/apply` 스킬(공고 수집 → 기업 리서치 brief → 공고 분석·기획 plan → 교훈 검토 → 사용자 승인)
→ `run_application.py`가 문서별로 [작가(Claude) → 배심원단(OpenAI, 병렬) → 집계 → 반송(최대 4회)/통과 → 사람 승인] → .docx
- 문서 종류 → 심사관 목록 매핑은 `router.py`에만 있다.
- 심사관 하나 = 항목 하나. 코드 심사관은 `judges/deterministic.py`, LLM 심사관은 `judges/prompts.py`.
- 거부권 심사관(`fact_grounding`, `known_gaps`)은 하나라도 불합격이면 무조건 반송.
- 작가는 반송 시 불합격 항목의 `fix_instruction`만 받고 나머지 문장은 건드리지 않는다.
- 기업 사실은 brief의 `co_` id로 인용하고, 그 인용문은 저장된 출처 원문에 실재해야 한다(`validate_plan.py`).

## 절대 바꾸지 말 것
1. **작가 모델과 심사관 모델은 다른 회사여야 한다**(현재 작가=Anthropic, 심사관=OpenAI) — 자기 선호 편향 방지.
2. `profile_db.json`이 후보자 사실의 유일한 출처다. 프롬프트나 코드에 후보자 사실을 하드코딩하지 않는다.
3. `known_gaps`에 있는 표현은 어떤 문서에도 나오면 안 된다.
4. 사람 승인 게이트(`human_gate`)를 우회하거나 자동 승인으로 바꾸지 않는다. 입력이 끊기면 미승인으로 처리된다.
5. LLM·세션 산출물은 전부 Pydantic 스키마(`schemas.py`)로 강제한다. 자유 텍스트 파싱 금지.

## profile_db 규칙
- `use: default` = 항상 사용, `use: optional` = JD가 명시적으로 요구할 때만(`when_to_use`).
- `emphasis`/`angle`은 프레이밍 지시일 뿐 — 구체적 사실은 `text`에서만.
- 실패/갈등 서사는 실제 소스를 확인하거나 본인에게 구체적으로 확인한 사실만 기입한다. 각색 금지.

## 교훈 장부 (lessons.json)
- 회고에서 나온 교훈을 층(L1 구조/L2 선택/L3 표현/L4 전략) · 조건 차원(doc_type, question_intent, role_kind, market,
  language, company_size, submission — 값 목록 또는 any) · 상태(가설/확정/폐기)로 관리한다.
- 새 지원 plan은 매칭되는 교훈을 `lessons_checked`에 모두 검토해야 validate를 통과한다. 상태 변경은 사용자 승인 후에만.

## 환경/실행 특이사항
- Windows 기본 로케일(cp949)에서 UTF-8이 깨진다 — 파일 open엔 `encoding="utf-8"`, 진입점엔
  `sys.stdout.reconfigure(encoding="utf-8")`.
- 일부 Claude 모델은 `temperature` 파라미터를 거부한다 — `ChatAnthropic`에 temperature를 넘기지 않는다.
- Claude tool-calling이 가끔 list 필드(또는 객체 전체)를 JSON 문자열로 한 번 더 감싸 보낸다 — `llms.py`가 복구한다.
- 새 OpenAI 조직은 모델별 레이트리밋이 낮다 — 형식/톤류 심사관(`config.LIGHT_JUDGES`)은 경량 모델로 분리.
- 비대화형 셸 테스트: 입력 없이 실행하면 승인 질문은 미승인(n)으로 처리된다. 승인 자동화가 아님.
- 폼에 글자 제한이 없는 문항: 기본 800자 상한(다 채울 필요 없음), 사용자 승인 시 1000자까지(`limit_source`).

## 작업 방식
- 파일을 고치기 전에 README.md와 해당 파일을 먼저 읽는다.
- 심사관 프롬프트는 한 번에 하나만 바꾸고 다시 실행해 효과를 확인한다.
- 실제 API 실행은 비용이 든다. 로직 변경 검증은 `DRY_RUN=1`로 먼저 한다(가능하면 `LOG_DIR`을 임시 폴더로).
- `runs/` 로그는 정확한 파일명으로만 지운다(와일드카드 삭제 금지).
- 최종 .docx는 사용자가 손으로 고칠 수 있다 — 덮어쓰기 전에 원본과 비교한다(`run_application.py`는 기존 파일을 보존).
- 환경변수의 API 키를 파일에 쓰거나 출력하지 않는다.
- 테스트: `python -m unittest discover -s tests`.
