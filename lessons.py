"""
교훈 장부(lessons.json) 로드와 공고 매칭. 과거 지원 회고에서 나온 교훈 중 이번 공고·문서의 차원 값에
해당하는 것만 골라, 기획 단계에서 반드시 검토(확정=기본 적용, 가설=적용 여부 결정)하게 한다.

실행(사람이 읽는 표 생성):
  python lessons.py            → lessons.md
"""
import json
import sys
from pathlib import Path

from schemas import ApplicationPlan, DocPlan, Lesson, LessonBook

LESSONS_PATH = Path("lessons.json")
SHORT_FIELD_MAX_CHARS = 300   # 이하면 '짧은 칸'(예: 해외경험 200자 폼)

PLAN_DIMS = ("role_kind", "market", "language", "company_size", "submission")
DOC_DIMS = ("doc_type", "question_intent")


def load_lessons(path: Path = LESSONS_PATH) -> list[Lesson]:
    if not Path(path).exists():
        return []
    return LessonBook.model_validate_json(Path(path).read_text(encoding="utf-8")).lessons


def doc_kind(doc: DocPlan) -> str:
    if doc.doc_type == "cv":
        return "cv"
    if doc.doc_type == "cover_letter":
        return "커버레터"
    return "짧은 칸" if doc.char_limit is not None and doc.char_limit <= SHORT_FIELD_MAX_CHARS else "서술형"


def _ok(cond, value) -> bool:
    return cond == "any" or value in cond


def matching_lessons(lessons: list[Lesson], plan: ApplicationPlan) -> list[Lesson]:
    """폐기되지 않았고, 공고 차원이 모두 맞고, 문서 차원이 맞는 문서가 하나 이상 있는 교훈."""
    out = []
    for les in lessons:
        if les.status == "폐기":
            continue
        c = les.conditions
        if not all(_ok(getattr(c, dim), getattr(plan, dim)) for dim in PLAN_DIMS):
            continue
        if any(_ok(c.doc_type, doc_kind(d)) and _ok(c.question_intent, d.question_intent) for d in plan.documents):
            out.append(les)
    return out


def render_md(lessons: list[Lesson]) -> str:
    def fmt(v):
        return "any" if v == "any" else ", ".join(v)
    lines = ["# 교훈 장부 (lessons.json에서 생성 — 직접 고치지 말 것)", "",
             "| id | 층 | 상태 | 규칙 | 조건(any 아닌 것만) | 작동 이유 | 근거 |", "|---|---|---|---|---|---|---|"]
    icon = {"확정": "✅ 확정", "가설": "🟡 가설", "폐기": "⛔ 폐기"}
    for les in lessons:
        cond = "; ".join(f"{k}={fmt(v)}" for k, v in les.conditions.model_dump().items() if v != "any") or "전부 any"
        lines.append(f"| {les.id} | {les.layer} | {icon[les.status]}<br>({les.status_reason}) | {les.rule} | {cond} | "
                     f"{les.mechanism} | {', '.join(les.evidence)} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    Path("lessons.md").write_text(render_md(load_lessons()), encoding="utf-8")
    print("saved: lessons.md")
