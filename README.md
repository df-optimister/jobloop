# jobloop — CV·지원서 문항·커버레터 공용 검증 루프

> 제 구직 지원을 위해 직접 만들어 쓰고 있는 시스템입니다. 핵심은 생성이 아니라 **검증** — 없는 경력을 만들어내는
> 문장이 하나라도 제출되면 실패라는 원칙으로, 모든 문장이 프로필 DB 근거를 인용하고 서로 다른 회사의 모델들이 심사하며
> 사람 승인 없이는 아무것도 확정되지 않습니다.
> *A system I built and use for my own job applications: verification over generation.*
>
> 이 저장소에는 구조만 공개합니다. 개인 프로필·지원 기록·교훈 장부는 비공개이며, `profile_db.example.json`과
> `lessons.example.json`은 가상 인물 예시입니다.

작가(Claude) → 배심원단(다른 모델 패밀리, 병렬) → 집계 → 반송/통과 → 사람 승인. LangGraph 기반.

**빠른 시작(API 없이)**: `pip install -r requirements.txt` →
`DRY_RUN=1 python main.py --doc-type cv --jd jd.example.txt --profile profile_db.example.json --company "Example Co" --role "Data Analyst"`
→ 테스트: `python -m unittest discover -s tests`

## 파일 구조

```
config.py               모델 이름, 라운드 상한, 임계값 (여기만 고치면 됨)
schemas.py              Draft / Claim / JudgeVerdict / LoopState — 모든 LLM 출력의 고정 스키마
llms.py                 모델 팩토리 + DRY_RUN 모의 객체
router.py               문서종류 → 심사관 목록, 거부권 심사관 목록
writer.py               작가 노드 (초안 / fix_instruction만 받아 수정)
judges/deterministic.py 코드 심사관 4개 (known_gaps, claims_integrity, char_limit, jd_keyword_coverage)
judges/prompts.py       LLM 심사관 프롬프트 7개 (심사관 하나 = 항목 하나)
judges/run.py           심사관 실행기 — 이름으로 코드/LLM 분기
graph.py                LangGraph 조립 (Send로 병렬 fan-out, interrupt로 사람 승인)
main.py                 CLI + 라운드 로그 저장
profile_db.json         단일 진실 소스 (entries + known_gaps) — 비공개. profile_db.example.json은 가상 인물 예시(DRY_RUN mock과 id 일치)
jd.example.txt          JD 예시
.env.example            필요한 환경변수 템플릿 (.env로 복사해서 실제 키 입력, .gitignore 등록됨)
fetch_posting.py        공고 링크 → applications/<slug>/posting.json (Ashby/Greenhouse/Lever API, 그 외 HTML/수동)
validate_plan.py        지원 폴더 검증: 스키마, brief 인용문 실재, evidence id, 문항 제한
run_application.py      승인된 plan대로 문서별 루프 실행 → drafts/ → 지원서 완성본/ .docx
.claude/skills/apply/   /apply 스킬: 기업 리서치·공고 분석·기획(Claude Code 세션)
applications/<slug>/    posting.json, sources/, brief.json, plan.json, outcome.json, drafts/ (과거 건은 retro.md)
lessons.json / lessons.py  교훈 장부(회고 → 교훈) + 공고 매칭. `python lessons.py` → lessons.md
tests/                  python -m unittest discover -s tests
```

## 지원 단위 흐름 (2026-10-05~)

```
/apply <url> → fetch_posting → 기업 리서치(brief, 사실마다 출처 인용) → 공고 분석·기획(plan) → validate_plan
→ 사용자 기획 승인 → python run_application.py applications/<slug> → 문서별 [writer → judges → aggregate → human_gate]
→ drafts/ → .docx
```

- 기업 사실 문장은 brief의 `co_` id를 Claim으로 인용하고 `claims_integrity`·`fact_grounding`이 검사한다
  (jd_text만 근거인 기업 문장은 기존처럼 Claim 없이 허용).
- plan의 `doc_plan`(lead/avoid/angle/closing_note)은 프레이밍 지시일 뿐 사실 출처가 아니다. `avoid_evidence_ids`를
  인용하면 `claims_integrity`에서 불합격.
- CV 헤더 날짜는 profile_db `period`와 정확히 같아야 한다(`cv_structure`).
- `outcome.json`은 결과 장부(상태·단계·피드백·원인 가설) — 회고·피드백 루프의 입력.
- 설계: `docs/superpowers/specs/2026-10-05-application-planning-stage-design.md`

## 흐름

```
START → writer ──Send×N──▶ judge(병렬) → aggregate
          ▲                                  │ revise (round < MAX_ROUNDS)
          └──────────────────────────────────┤
                                             ├ pass / escalate → human_gate(interrupt) → END
```

- `verdicts`는 라운드 누적 리스트. `aggregate`는 현재 라운드만 본다.
- 거부권 심사관(`fact_grounding`, `known_gaps`)은 하나라도 불합격이면 무조건 반송.
- 작가는 반송 시 **불합격 항목의 `fix_instruction`만** 받고, 나머지 문장은 건드리지 말라는 지시를 받는다.
- 상한 도달 시 `escalate`로 사람에게 넘어가며 불합격 사유가 함께 표시된다. 상한(`MAX_ROUNDS`) 기본값은 4.
- 형식/톤류 심사관(`tone_length`, `uk_cv_convention`, `bullet_format`)은 `gpt-5-mini`로 돌아 `gpt-5`와
  별도의 레이트리밋 버킷을 쓴다 — 새 OpenAI 조직은 모델별 TPM/RPD가 낮아서(gpt-5 기준 TPM 10,000·RPD 50
  실측) 병렬 fan-out 시 이 분리가 없으면 금방 막힌다.

## 실행

```bash
pip install -r requirements.txt

# API 키는 .env 파일로 관리한다 (.env.example을 .env로 복사 후 실제 키 입력, .gitignore에 등록됨)
# 작가=Claude(claude-sonnet-5), 심사관 전원=OpenAI(gpt-5, 가벼운 형식류는 gpt-5-mini)

# 1) API 없이 전체 루프 동작 확인
DRY_RUN=1 python main.py --doc-type cv --jd jd.example.txt --profile profile_db.json \
    --company "Example FC" --role "Football Data Scientist"

# 2) 실제 실행
python main.py --doc-type cv ...
python main.py --doc-type application_answer --question "Describe a time you failed" --word-limit 250 ...
python main.py --doc-type cover_letter --word-limit 400 ...
```

Windows에서 실행 시 파일/콘솔 인코딩이 cp949로 깨지는 문제가 있어 `main.py`가 UTF-8을 강제한다 —
다른 스크립트를 새로 짤 때도 `open(path, encoding="utf-8")`과 `sys.stdout.reconfigure(encoding="utf-8")`을 넣을 것.

`runs/` 에 라운드별 모든 verdict가 JSON으로 남는다. 20건쯤 쌓이면 어떤 심사관이 자주 떨어뜨리는지, 어떤 심사관이 아무것도 못 잡는지 보고 프롬프트를 조정한다.

## profile_db.json 규칙

- `entries[].id`는 작가가 인용할 유일한 키. 문장 하나에 인용 못 하는 항목이 있으면 `claims_integrity`에서 자동 탈락.
  단, `candidate`(이름/연락처)는 `entries` 밖의 별도 필드라 id가 없다 — 인용 대상이 아니며 claim도 만들지 않는다.
- `known_gaps`는 **본문에 나오면 안 되는 표현** 목록. 단어 경계로 매칭하므로("GAM"이 "game"에 오탐되지 않음)
  짧은 문구도 안전하게 쓸 수 있지만, 여전히 실제로 쓸 법한 문구로 적는다.
- 사실이 바뀌면 이 파일만 고친다. 프롬프트에 사실을 적지 않는다.
- 실패/갈등 서사를 추가할 땐 실제 소스(논문, 프로젝트 문서 등)를 확인하거나 본인에게 구체적으로 확인한 사실만
  적는다 — 강점은 `emphasis`/`angle`로 프레이밍하되 각색하지 않는다.

## 확장

| 하고 싶은 것 | 고칠 곳 |
|---|---|
| 새 문서 유형(예: 포트폴리오 설명) | `router.PANEL`에 키 추가, `writer.SYSTEM`에 지침 한 줄 |
| 심사관 추가 | `judges/prompts.py`에 항목 추가 → `router.PANEL`에 이름 추가 |
| 코드 심사관 추가 | `judges/deterministic.py`에 함수 + `REGISTRY` 등록 → `router.DETERMINISTIC`에 이름 추가 |
| 모델 교체 | `config.py`의 `WRITER_MODEL`/`JUDGE_MODEL`/`REDTEAM_MODEL`/`JUDGE_MODEL_LIGHT` |
| 심사관을 저비용 모델로 돌리기 | `config.LIGHT_JUDGES`에 이름 추가 (여전히 OpenAI여야 함 — "심사관 전원 OpenAI" 규칙) |
| 승인 UI를 CLI 대신 웹으로 | `human_gate_node`의 interrupt payload를 그대로 화면에 띄우고 `Command(resume=...)`로 재개 |
| 여러 문항 한 번에 | 문항마다 `main.py`를 호출하되 이전 답변을 `--prior-answers`로 넘김 |

## 다음 단계로 붙이면 좋은 것

1. `InMemorySaver` → `SqliteSaver`로 바꿔 중단 후 재개 가능하게.
2. `jd_keyword_coverage`의 키워드 추출을 LLM 1회 호출로 교체(현재는 빈도 휴리스틱).
3. `runs/` 로그로 심사관별 불합격률 대시보드 — 어떤 심사관이 실제로 값을 하는지 측정.
4. 최종 통과본은 `.docx`로 내보내기(별도 스크립트).
