---
name: apply
description: 채용공고 링크(또는 JD 텍스트)를 받아 jobloop 지원 폴더를 만들고 기업 분석·공고 분석·지원서 기획까지 한 뒤 사용자 승인을 받는다. 사용자가 공고 링크를 주며 지원/분석/기획을 요청할 때, 또는 /apply <url> 로 호출할 때 사용.
---

# /apply — 공고 → 기업·공고 분석 → 기획 → (승인) → 루프

스펙: docs/superpowers/specs/2026-10-05-application-planning-stage-design.md. 결과는 전부 `applications/<slug>/`.
slug는 `<company>-<role-short>` 소문자·하이픈(예: `acme-ds-product`).

## 1. 공고 수집
`python fetch_posting.py <url> --slug <slug>` → posting.json. 실패(JS 렌더링 사이트 등)하면 사용자에게 JD 본문을
붙여넣어 달라고 하고 `applications/<slug>/jd.txt`에 저장 → `--from-text` 경로. 폼 문항을 못 얻었으면 문항 전문과
글자수/단어수 제한을 사용자에게 묻는다(제한을 추측하지 않는다).
수집 후 `posting.json`의 jd_text 앞부분을 직접 읽어 실제 공고 본문인지(메뉴·쿠키 안내·푸터가 아닌지), company/role 표기가
맞는지(Ashby/Lever는 URL slug에서 회사명을 만든다 — 예: 'Openai') 확인하고 틀리면 `--company`/`--role`로 다시 받는다.

## 2. 기업 리서치 → brief.json
- 출처 우선순위: 회사 공식 사이트·채용 페이지·공식 블로그/뉴스룸 > 신뢰할 언론 > 기타. 공고 본문 자체도 출처다
  (`posting.json`의 jd_text를 `sources/`에 저장하고 공고 URL로 index에 등록).
- 읽은 출처마다 본문 텍스트를 `sources/NN.txt`로 저장하고 `sources/index.json`에 `{url: "NN.txt"}` 기록.
  WebFetch는 요약을 돌려주므로 인용문용 원문은 `curl` + `fetch_posting.html_to_text`로 받는다
  (JS 렌더링 페이지라 본문이 안 나오면 그 출처는 brief.facts에 쓰지 않는다).
- `facts`: 문서에 써도 되는 기업 사실만, `co_1`부터. 각 `quote`는 저장한 원문에 그대로 있는 구절.
  제3자 추정치(밸류에이션·ARR 추정 등)는 facts에 넣지 않고 `analysis`에 "추정"으로만.
- `analysis`: 문화·팀·제품·데이터 스택·채용 절차·시사점(기획자용 해석).

## 3. 공고 분석 → plan.json
- `fit`: JD 요구를 must/nice로 쪼개 profile_db id에 매핑(met/partial/gap/unknown). profile_db 밖의 사실을 만들지 않는다.
- 필수조건(연차, 근무지·노동허가/비자, 도메인 경력) 미충족은 `risks`와 `recommendation`(go/stretch/no_go)에.
  지원 여부는 사용자가 결정한다.
- `role_kind`: technical(데이터/ML/엔지니어링) vs generalist — writer 3b 분기.
- `documents`: 폼에서 작가가 쓸 문서만(CV, 서술형 문항, 커버레터). 단답형(전화번호·연봉·비자 Y/N 등)은
  `manual_fields`. 폼에 분량 제한이 없는 서술형은 `limit_source: "default"` + `char_limit: 800`(공백 포함 800자 상한 —
  강점을 충분히 드러냈다면 다 채우지 않아도 됨). 더 필요하면 사용자 승인을 받은 뒤에만 `limit_raise_approved: true`로
  1000자까지 올린다(validate_plan이 강제, 사용자 규칙 2026-10-05).
- 기획 규칙(2026-10-05 회고):
  - CV `angle`에 "PROJECTS는 JD 관련성 순"을 명시(시간순은 동점일 때만). 단, 현재 `cv_structure`가 역시간순을
    결정적으로 강제하므로 관련성 순이 역시간순과 다르면 루프가 반송된다 — 그 경우 사용자에게 알리고 결정을 받는다
    (회고 논의 안건, 2026-10-05).
  - 실패·결함 서술 항목(profile_db에서 실패담으로 표시한 항목)은 CV `avoid_evidence_ids`에 — 문항 답변에서만 허용.
  - 문항끼리 주 근거(`lead_evidence_ids`)가 겹치지 않게 배분, `closing_note`는 서로 다른 형태.
  - 헤더 headline이 JD와 안 맞으면 `manual_fields`에 표시.
  - optional 항목은 JD가 명시적으로 요구할 때만 lead에.
- 공고 차원 값: `market`(한국 공채/영미권), `language`(ko/en), `company_size`(대기업/중견/중소/스타트업),
  `submission`(CV 단독/CV+문항/문항만). 서술형·커버레터 문서마다 `question_intent`
  (지원동기/직무역량/경험/가치관/트렌드·제품/자유).
- **교훈 검토(필수)**: `lessons.json`에서 이번 공고에 매칭되는 교훈(`lessons.matching_lessons`)을 모두
  `lessons_checked`에 기록 — 확정은 기본 적용(안 하면 구체 사유), 가설은 적용 여부를 판단해 이유와 함께.
  `how`에는 어느 문항·슬롯에 무엇을 넣었는지를 적는다. 슬롯은 문장 템플릿이 아니다(L-002).
- `outcome.json`을 `{"status": "planned"}`로 생성.

## 4. 검증과 승인
`python validate_plan.py applications/<slug>` 통과까지 고친다. 그다음 사용자에게 한국어로 요약(기업 분석 핵심,
적합도표, 리스크·권고, 문서별 방향, **교훈 검토 표(lessons_checked)**, 사용자가 직접 입력할 항목)을 보여주고 수정 요청을 반영한다.
사용자가 승인하면 실행 안내: `python run_application.py applications/<slug>` (실제 API 비용 발생 —
human_gate 승인은 사용자가 직접; 비대화형 테스트만 `echo n |`).

## 5. 루프 후 사후 점검과 교훈 갱신
- 초안이 나오면 `lessons_checked`의 각 교훈을 실제 초안에 대조해 어긋난 곳을 사용자에게 알린다(제출 전).
- 결과(`outcome.json`)가 들어오면 회고(retro.md) → `lessons.json` 추가·갱신. 가설→확정, 폐기는 사용자 승인 후에만.
  확정이 객관 판정 가능하면 심사관/코드 검사로 승격하고 `promoted_to`에 기록. 갱신 후 `python lessons.py`로 lessons.md 재생성.
