"""
루프 안을 오가는 모든 데이터의 고정 스키마.
LLM 출력은 전부 이 스키마로 강제(structured output)한다 — 자유 텍스트 금지.
"""
import operator
from typing import Annotated, Literal, Optional, TypedDict, Union

from pydantic import BaseModel, Field

DocType = Literal["cv", "application_answer", "cover_letter"]


# ---------- 작가(Generator) 출력 ----------
class Claim(BaseModel):
    """문장 하나 = 주장 하나. 반드시 profile_db 항목 id를 인용해야 한다."""
    text: str = Field(description="The exact sentence or bullet as it appears in the draft")
    evidence_ids: list[str] = Field(
        description="profile_db entry ids that support this sentence. Empty list is NOT allowed "
                    "for any factual statement about the candidate."
    )


class Draft(BaseModel):
    doc_type: DocType
    content: str = Field(description="The full document text, ready to submit")
    claims: list[Claim] = Field(description="One Claim per factual sentence/bullet in content")


# ---------- 심사관(Judge) 출력 ----------
class JudgeVerdict(BaseModel):
    judge: str
    round: int = 0
    score: int = Field(ge=0, le=5, description="0=fail badly, 5=perfect")
    passed: bool
    evidence: list[str] = Field(
        default_factory=list,
        description="Quotes or locations in the draft that justify the score"
    )
    fix_instruction: Optional[str] = Field(
        default=None,
        description="If not passed: one concrete, actionable instruction for the writer. "
                    "Do not rewrite the document yourself."
    )


# ---------- 입력 ----------
class JobInput(BaseModel):
    doc_type: DocType
    jd_text: str
    company: str
    role: str
    question: Optional[str] = None          # application_answer 전용
    word_limit: Optional[int] = None        # 문항/커버레터 단어 제한 (영어 문서용)
    char_limit: Optional[int] = None        # 문항/커버레터 글자수 제한, 공백 포함 (한국어 등 문서용)
    language: str = "English"               # 작가가 작성할 언어. 예: "Korean"
    prior_answers: list[str] = []           # 같은 지원서의 다른 문항 답변(중복 경험 검사용)
    company_brief: list[dict] = []          # 기획 단계 brief.facts (BriefFact.model_dump()) — 기업 사실 출처(co_ id)
    doc_plan: Optional[dict] = None         # 승인된 DocPlan.model_dump() — 프레이밍 지시(사실 출처 아님)


# ---------- LangGraph 상태 ----------
def _append(a: list, b: list) -> list:
    return a + b


class LoopState(TypedDict, total=False):
    job: dict                                   # JobInput.model_dump()
    profile_db: dict                            # 단일 진실 소스
    round: int
    draft: Optional[dict]                       # Draft.model_dump()
    verdicts: Annotated[list[dict], _append]    # 전 라운드 누적. round 필드로 구분
    decision: Literal["pass", "revise", "escalate"]
    approved: Optional[bool]
    final: Optional[str]


# ---------- 지원 기획 단계 (applications/<slug>/) ----------
class FormQuestion(BaseModel):
    id: str                                 # "q1"... 폼 수집 순서
    title: str
    type: str                               # "LongText", "String", "Boolean", "File", "ValueSelect" ...
    required: bool
    description: Optional[str] = None
    options: list[str] = []


class Posting(BaseModel):
    url: Optional[str]                      # 과거 지원 정리 시 URL을 모르면 None
    ats: Literal["ashby", "greenhouse", "lever", "generic", "manual"]
    company: str
    role: str
    location: Optional[str] = None
    jd_text: str
    questions: list[FormQuestion] = []
    fetched_at: str


class BriefFact(BaseModel):
    id: str                                 # "co_1"... 작가가 Claim에서 인용하는 키
    text: str                               # 문서에 쓸 수 있는 기업 사실 한 문장
    source_url: str
    quote: str                              # 출처 원문에 그대로 있는 구절 — validate_plan이 실재 여부 검사


class CompanyBrief(BaseModel):
    company: str
    facts: list[BriefFact]
    analysis: str                           # 기획자용 해석. 문서의 사실 출처로 쓰지 않는다
    researched_at: str


class FitRow(BaseModel):
    requirement: str
    kind: Literal["must", "nice"]
    status: Literal["met", "partial", "gap", "unknown"]
    evidence_ids: list[str] = []
    note: str = ""


Market = Literal["한국 공채", "영미권"]
Language = Literal["ko", "en"]
CompanySize = Literal["대기업", "중견", "중소", "스타트업"]
Submission = Literal["CV 단독", "CV+문항", "문항만"]
DocKind = Literal["cv", "서술형", "커버레터", "짧은 칸"]
QuestionIntent = Literal["지원동기", "직무역량", "경험", "가치관", "트렌드·제품", "자유"]


class DocPlan(BaseModel):
    item_id: str                            # "cv", "q1"...
    doc_type: DocType
    question: Optional[str] = None
    word_limit: Optional[int] = None
    char_limit: Optional[int] = None
    # 폼에 분량 제한이 없으면 "default": 공백 포함 800자 상한(다 채울 필요 없음). 사용자가 승인하면
    # limit_raise_approved=True로 1000자까지 — validate_plan이 강제한다(사용자 규칙 2026-10-05).
    limit_source: Literal["form", "default"] = "form"
    limit_raise_approved: bool = False
    language: str = "English"
    lead_evidence_ids: list[str]
    avoid_evidence_ids: list[str] = []
    angle: str
    closing_note: Optional[str] = None
    question_intent: Optional[QuestionIntent] = None   # 서술형·커버레터는 필수(교훈 매칭용), cv는 비움


class LessonCheck(BaseModel):
    lesson_id: str
    applies: bool
    how: str                                # 적용했으면 어떻게(어느 문항·슬롯), 안 했으면 사유


class ApplicationPlan(BaseModel):
    slug: str
    role_kind: Literal["technical", "generalist"]
    fit: list[FitRow]
    risks: list[str]
    recommendation: Literal["go", "stretch", "no_go"]
    rationale: str
    documents: list[DocPlan]
    manual_fields: list[str] = []
    approved_at: Optional[str] = None
    # 교훈 매칭용 공고 차원 값 + 검토 기록(2026-10-05). 과거 지원 회고용 plan은 retro=True로 검사 제외.
    retro: bool = False
    market: Optional[Market] = None
    language: Optional[Language] = None
    company_size: Optional[CompanySize] = None
    submission: Optional[Submission] = None
    lessons_checked: list[LessonCheck] = []


class Outcome(BaseModel):
    status: Literal["planned", "submitted", "rejected", "interview", "offer", "withdrawn", "unknown"]
    submitted_at: Optional[str] = None
    stage_reached: Optional[str] = None
    feedback_raw: Optional[str] = None
    submitted_files: list[str] = []
    hypotheses: list[str] = []


# ---------- 교훈 장부 (lessons.json) ----------
Any_ = Literal["any"]


class LessonConditions(BaseModel):
    """차원마다 값 목록 또는 "any"(= 이 차원은 따지지 않음, 나중에 추가되는 값도 포함)."""
    doc_type: Union[Any_, list[DocKind]] = "any"
    question_intent: Union[Any_, list[QuestionIntent]] = "any"
    role_kind: Union[Any_, list[Literal["technical", "generalist"]]] = "any"
    market: Union[Any_, list[Market]] = "any"
    language: Union[Any_, list[Language]] = "any"
    company_size: Union[Any_, list[CompanySize]] = "any"
    submission: Union[Any_, list[Submission]] = "any"


class Lesson(BaseModel):
    id: str
    layer: Literal["L1 구조", "L2 선택", "L3 표현", "L4 전략"]
    rule: str
    slots: list[str] = []                   # 채울 칸(문장 템플릿이 아님)
    conditions: LessonConditions = LessonConditions()
    mechanism: str                          # 왜 통하는가 — 조건 범위의 근거
    status: Literal["가설", "확정", "폐기"]
    status_reason: str
    evidence: list[str] = []
    counterexamples: list[str] = []
    promoted_to: Optional[str] = None
    updated_at: str


class LessonBook(BaseModel):
    lessons: list[Lesson]
