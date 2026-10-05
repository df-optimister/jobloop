"""
문서 종류 → 배심원단 구성. 새 문서 유형을 추가할 때 고치는 곳은 이 파일뿐이다.
"""

# 항상 켜지는 심사관. 하나라도 불합격이면 무조건 반송(거부권).
ALWAYS_ON = ["fact_grounding", "known_gaps"]
VETO = set(ALWAYS_ON)

# 문서 종류별 추가 심사관
PANEL = {
    "cv": [
        "char_limit",               # 코드: config.DEFAULT_CHAR_LIMIT["cv"](480 words) — 1페이지 분량의 값싼 프록시
        "jd_keyword_coverage",      # 코드
        "cv_structure",             # 코드: PROFILE 금지, PROJECTS가 EXPERIENCE보다 먼저, 프로젝트당 불릿<=4, 월+연도 날짜
        "uk_cv_convention",         # LLM
        "bullet_format",            # LLM
        "quantification",           # LLM: profile_db에 숫자가 있으면 반드시 그 숫자를 써야 함
    ],
    "application_answer": [
        "char_limit",               # 코드
        "question_alignment",       # LLM
        "cross_answer_duplication", # LLM
    ],
    "cover_letter": [
        "char_limit",               # 코드
        "company_specificity",      # LLM
        "exaggeration_redteam",     # LLM (제3 모델)
        "tone_length",              # LLM
    ],
}

# 코드로 판정하는 심사관(LLM 호출 없음)
DETERMINISTIC = {"known_gaps", "jd_keyword_coverage", "char_limit", "claims_integrity", "cv_structure"}


def panel_for(doc_type: str) -> list[str]:
    # claims_integrity: 모든 evidence_id가 profile_db에 실재하는지 — 사실 대조관보다 먼저 싸게 거른다.
    return ALWAYS_ON + ["claims_integrity"] + PANEL[doc_type]
