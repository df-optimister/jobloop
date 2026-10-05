"""
applications/<slug>/ 의 posting·brief·plan·outcome을 결정적으로 검증한다. 루프 실행 전 관문.

실행:
  python validate_plan.py applications/<slug>

검사: Pydantic 스키마 / brief 사실의 인용문이 저장된 출처 원문에 실재 / co_ id 유일 /
plan의 모든 evidence id가 profile_db에 실재 / item_id 유일 / 문항 답변은 word_limit·char_limit 중 정확히 하나 /
lead·avoid 겹침 없음 / plan.slug == 폴더명.
"""
import json
import re
import sys
from pathlib import Path

from pydantic import ValidationError

from lessons import load_lessons, matching_lessons
from schemas import ApplicationPlan, CompanyBrief, Lesson, Outcome, Posting

# 폼에 분량 제한이 없는 문항: 공백 포함 800자 상한, 사용자 승인 시 1000자까지(사용자 규칙 2026-10-05)
DEFAULT_LIMIT, DEFAULT_LIMIT_RAISED = 800, 1000

_TRANS = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-", "\xa0": " ", "…": "..."})


def normalise(s: str) -> str:
    return re.sub(r"\s+", " ", s.translate(_TRANS)).strip().lower()


def load_app(app_dir: Path):
    app_dir = Path(app_dir)
    posting = Posting.model_validate_json((app_dir / "posting.json").read_text(encoding="utf-8"))
    bp = app_dir / "brief.json"
    brief = CompanyBrief.model_validate_json(bp.read_text(encoding="utf-8")) if bp.exists() else None
    plan = ApplicationPlan.model_validate_json((app_dir / "plan.json").read_text(encoding="utf-8"))
    return posting, brief, plan


def _check_brief(app_dir: Path, brief: CompanyBrief) -> list[str]:
    errs = []
    ids = [f.id for f in brief.facts]
    errs += [f"brief: duplicate fact id {i}" for i in {i for i in ids if ids.count(i) > 1}]
    errs += [f"brief: fact id {i} must start with 'co_'" for i in ids if not i.startswith("co_")]
    idx_path = app_dir / "sources" / "index.json"
    index = json.loads(idx_path.read_text(encoding="utf-8")) if idx_path.exists() else {}
    cache = {}
    for f in brief.facts:
        fname = index.get(f.source_url)
        src = app_dir / "sources" / fname if fname else None
        if not src or not src.exists():
            errs.append(f"brief: {f.id} source not saved in sources/ ({f.source_url})")
            continue
        if fname not in cache:
            cache[fname] = normalise(src.read_text(encoding="utf-8"))
        if normalise(f.quote) not in cache[fname]:
            errs.append(f"brief: {f.id} quote not found in source {fname}: \"{f.quote[:80]}\"")
    return errs


def _check_plan(app_dir: Path, plan: ApplicationPlan, profile_db: dict) -> list[str]:
    errs = []
    known = {e["id"] for e in profile_db["entries"]}
    if plan.slug != app_dir.name:
        errs.append(f"plan: slug '{plan.slug}' != folder name '{app_dir.name}'")
    for row in plan.fit:
        errs += [f"plan.fit: unknown evidence id {i} ({row.requirement[:40]})" for i in row.evidence_ids if i not in known]
    seen = set()
    for d in plan.documents:
        if d.item_id in seen:
            errs.append(f"plan: duplicate item_id {d.item_id}")
        seen.add(d.item_id)
        for i in d.lead_evidence_ids + d.avoid_evidence_ids:
            if i not in known:
                errs.append(f"plan.{d.item_id}: unknown evidence id {i}")
        for i in set(d.lead_evidence_ids) & set(d.avoid_evidence_ids):
            errs.append(f"plan.{d.item_id}: {i} is both lead and avoid")
        if d.doc_type == "application_answer":
            if not d.question:
                errs.append(f"plan.{d.item_id}: application_answer needs question")
            if (d.word_limit is None) == (d.char_limit is None):
                errs.append(f"plan.{d.item_id}: set exactly one of word_limit/char_limit")
            if d.limit_source == "default":
                cap = DEFAULT_LIMIT_RAISED if d.limit_raise_approved else DEFAULT_LIMIT
                if d.char_limit is None:
                    errs.append(f"plan.{d.item_id}: form has no limit → use char_limit (default {DEFAULT_LIMIT})")
                elif d.char_limit > cap:
                    errs.append(f"plan.{d.item_id}: char_limit {d.char_limit} > {cap} — form has no limit, so the "
                                f"default cap is {DEFAULT_LIMIT} chars; up to {DEFAULT_LIMIT_RAISED} only with the "
                                f"user's approval (limit_raise_approved)")
    return errs


def _check_lessons(plan: ApplicationPlan, lessons: list[Lesson]) -> list[str]:
    """새 지원(retro 아님): 공고 차원 값·문항 의도가 채워져 있고, 매칭되는 교훈을 모두 검토했는지."""
    if plan.retro:
        return []
    errs = [f"plan: {dim} is required (lesson matching)" for dim in ("market", "language", "company_size", "submission")
            if getattr(plan, dim) is None]
    errs += [f"plan.{d.item_id}: question_intent is required for {d.doc_type}" for d in plan.documents
             if d.doc_type != "cv" and d.question_intent is None]
    if errs:
        return errs
    known = {les.id for les in lessons}
    checked = {c.lesson_id: c for c in plan.lessons_checked}
    errs += [f"plan.lessons_checked: unknown lesson {i}" for i in checked if i not in known]
    for les in matching_lessons(lessons, plan):
        c = checked.get(les.id)
        if c is None:
            errs.append(f"plan.lessons_checked: {les.id} ({les.status}) matches this posting but was not reviewed")
        elif not c.how.strip():
            errs.append(f"plan.lessons_checked: {les.id} needs how it was applied or the reason it was not")
        elif les.status == "확정" and not c.applies and len(c.how.strip()) < 10:
            errs.append(f"plan.lessons_checked: {les.id} is 확정 but not applied — give a concrete reason")
    return errs


def validate(app_dir: Path, profile_db: dict, lessons: list[Lesson] | tuple = ()) -> list[str]:
    app_dir = Path(app_dir)
    try:
        _, brief, plan = load_app(app_dir)
        op = app_dir / "outcome.json"
        if op.exists():
            Outcome.model_validate_json(op.read_text(encoding="utf-8"))
    except (ValidationError, FileNotFoundError, json.JSONDecodeError) as e:
        return [f"schema/load: {e}"]
    errs = _check_brief(app_dir, brief) if brief else []
    return errs + _check_plan(app_dir, plan, profile_db) + _check_lessons(plan, list(lessons))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    app_dir = Path(sys.argv[1])
    profile_db = json.loads(Path("profile_db.json").read_text(encoding="utf-8"))
    errs = validate(app_dir, profile_db, load_lessons())
    for e in errs:
        print(f"[FAIL] {e}")
    print("OK" if not errs else f"{len(errs)} problem(s)")
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
