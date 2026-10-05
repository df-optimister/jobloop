"""
전역 설정. 모델 이름·임계값·루프 상한은 전부 여기서만 바꾼다.
"""
import os

from dotenv import load_dotenv

load_dotenv()  # .env가 있으면 ANTHROPIC_API_KEY/OPENAI_API_KEY 등을 여기서 로드. .env는 git에 커밋하지 않는다.

# 작가와 심사관은 반드시 다른 모델 패밀리로 둔다 (자기 선호 편향 방지).
WRITER_MODEL = os.getenv("WRITER_MODEL", "claude-sonnet-5")            # Anthropic
JUDGE_MODEL = os.getenv("JUDGE_MODEL", "gpt-5")                       # OpenAI
# 과장 탐지관. 제3 패밀리(Gemini 등) 키가 생기면 여기만 바꾸면 된다.
# 지금은 OpenAI 두 번째 모델을 쓴다 — 작가(Claude)와는 다른 패밀리이므로 자기 선호 편향은 피한다.
REDTEAM_MODEL = os.getenv("REDTEAM_MODEL", "gpt-5")
# 형식/톤류 심사관(사실 검증이 아닌)은 저비용 모델로 — 여전히 OpenAI라 "심사관 전원=OpenAI" 규칙은 유지되고,
# gpt-5와 별도의 레이트리밋 버킷을 쓰므로 병렬 fan-out 시 gpt-5 쪽 TPM/RPD 부담이 줄어든다.
JUDGE_MODEL_LIGHT = os.getenv("JUDGE_MODEL_LIGHT", "gpt-5-mini")
LIGHT_JUDGES = {"tone_length", "uk_cv_convention", "bullet_format"}

MAX_ROUNDS = int(os.getenv("MAX_ROUNDS", "4"))   # 작가 ↔ 배심원단 반복 상한
PASS_SCORE = 3                                   # 일반 심사관 통과 최소 점수 (0~5)

# 결정적(코드) 검사 기본값
DEFAULT_CHAR_LIMIT = {
    # CV는 반드시 1페이지여야 한다 — 초과하면 탈락. 480 words는 build_docx.py의 타이트 서식
    # (여백 0.35in, 본문 9.5~10pt)으로 실측한 1페이지 상한(약 476 words)에서 역산한 값.
    # 이건 라운드마다 싼 프록시일 뿐, 최종 판정은 build_docx.py가 실제 .docx를 만들어
    # Word COM(get_page_count.py)으로 페이지 수를 직접 세는 것이 권위 있는 기준이다.
    "cv": 480,
    "application_answer": 300,  # 문항 기본값(words 기준). 입력에서 덮어쓸 수 있음
    "cover_letter": 450,
}
JD_KEYWORD_MIN_COVERAGE = 0.6   # JD 핵심 키워드 최소 커버율
# 작가(LLM)가 스스로 글자수를 정확히 세지 못해 char_limit에서 계속 escalate되는 문제 완화용.
# char_limit(글자수 기준일 때만)을 최대 이만큼 넘어도 통과로 인정한다. word_limit(영문)에는 적용하지 않음.
CHAR_LIMIT_TOLERANCE = int(os.getenv("CHAR_LIMIT_TOLERANCE", "100"))

DRY_RUN = os.getenv("DRY_RUN", "0") == "1"       # 1이면 LLM 호출 없이 모의 객체로 전체 루프 실행
LOG_DIR = os.getenv("LOG_DIR", "runs")
