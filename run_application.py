"""
승인된 기획(applications/<slug>/plan.json)대로 문서별 검증 루프를 돌린다.

실행:
  python run_application.py applications/<slug> [--only q1,q2]

순서: validate_plan 검사 → 기획 승인(없으면 요약 출력 후 y/n) → plan.documents 순서대로 main.run_job
(문서마다 human_gate) → 승인본 drafts/<item>.txt, 미승인 drafts/<item>.unapproved.txt →
answers_spec.json + build_answers_docx.py / build_docx.py 로 '지원서 완성본/<Company - Role>/' 생성.

안전장치(2026-10-05 리뷰): 이번 실행에서 승인된 문서의 .docx만 다시 만들고, 대상 .docx가 이미 있으면(사용자가
손으로 고쳤을 수 있음) 덮어쓰지 않고 시각을 붙인 새 파일로 만든다. DRY_RUN은 drafts_dryrun/과
'지원서 완성본/_dryrun/'에만 쓴다. 입력이 끊기면(EOF) 미승인으로 처리한다.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import config
from main import ask, run_job
from schemas import ApplicationPlan, CompanyBrief, DocPlan, JobInput, Posting
from lessons import load_lessons
from validate_plan import load_app, validate

OUT_ROOT = Path("지원서 완성본")


def drafts_dir(app_dir: Path) -> Path:
    return Path(app_dir) / ("drafts_dryrun" if config.DRY_RUN else "drafts")


def output_dir(posting: Posting) -> Path:
    root = OUT_ROOT / "_dryrun" if config.DRY_RUN else OUT_ROOT
    return root / f"{posting.company} - {posting.role}"


def safe_output(path: Path) -> Path:
    """이미 있는 최종 .docx는 사용자가 손으로 고쳤을 수 있으므로 덮어쓰지 않고 시각을 붙인 새 경로를 준다."""
    path = Path(path)
    if not path.exists():
        return path
    return path.with_name(f"{path.stem} ({time.strftime('%Y%m%d-%H%M%S')}){path.suffix}")


def unknown_only_ids(only: set[str], plan: ApplicationPlan) -> list[str]:
    known = {d.item_id for d in plan.documents}
    return sorted(i for i in only if i not in known)


def prior_answers(app_dir: Path, plan: ApplicationPlan, upto_item: str) -> list[str]:
    """같은 지원서에서 upto_item보다 앞선 문항 답변 중 '승인본'만 (중복 검사용)."""
    out = []
    for d in plan.documents:
        if d.item_id == upto_item:
            break
        p = drafts_dir(app_dir) / f"{d.item_id}.txt"
        if d.doc_type == "application_answer" and p.exists():
            out.append(p.read_text(encoding="utf-8").strip())
    return out


def job_for(doc: DocPlan, posting: Posting, brief: CompanyBrief | None, prior: list[str]) -> dict:
    return JobInput(
        doc_type=doc.doc_type, jd_text=posting.jd_text, company=posting.company, role=posting.role,
        question=doc.question, word_limit=doc.word_limit, char_limit=doc.char_limit, language=doc.language,
        prior_answers=prior if doc.doc_type == "application_answer" else [],
        company_brief=[f.model_dump() for f in brief.facts] if brief else [],
        doc_plan=doc.model_dump(),
    ).model_dump()


def answers_spec(app_dir: Path, posting: Posting, plan: ApplicationPlan, candidate_name: str) -> dict:
    items = []
    for d in plan.documents:
        p = drafts_dir(app_dir) / f"{d.item_id}.txt"
        if d.doc_type != "application_answer" or not p.exists():
            continue
        items.append({"question": d.question, "limit": d.word_limit or d.char_limit,
                      "unit": "words" if d.word_limit else "자", "answer_file": str(p)})
    return {"title": f"{posting.company} — {posting.role} application answers ({candidate_name})", "items": items}


def summarize(posting: Posting, plan: ApplicationPlan) -> str:
    lines = [f"[{posting.company} — {posting.role}]  role_kind={plan.role_kind}  recommendation={plan.recommendation}",
             f"rationale: {plan.rationale}", "fit:"]
    lines += [f"  [{r.kind}/{r.status}] {r.requirement}  {r.evidence_ids}" for r in plan.fit]
    lines += ["risks:"] + [f"  - {r}" for r in plan.risks] + ["documents:"]
    for d in plan.documents:
        lim = f"{d.word_limit} words" if d.word_limit else (f"{d.char_limit}자" if d.char_limit else "")
        lines.append(f"  {d.item_id} ({d.doc_type} {lim}) lead={d.lead_evidence_ids} avoid={d.avoid_evidence_ids}")
        lines.append(f"      angle: {d.angle}")
    if plan.manual_fields:
        lines.append(f"manual_fields: {plan.manual_fields}")
    return "\n".join(lines)


def ensure_approved(app_dir: Path, posting: Posting, plan: ApplicationPlan) -> bool:
    if plan.approved_at:
        return True
    print(summarize(posting, plan))
    if config.DRY_RUN:          # 시험 실행: 진행하되 승인 기록은 남기지 않는다
        print("[DRY_RUN] 기획 승인 기록 없이 진행")
        return True
    if ask("\n기획 승인? (y/n): ").strip().lower() not in ("y", "yes"):
        return False
    plan.approved_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    (app_dir / "plan.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    return True


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("app_dir")
    ap.add_argument("--only", help="쉼표로 구분한 item_id만 실행, 예: q1,q2")
    a = ap.parse_args()
    app_dir = Path(a.app_dir)
    profile_db = json.loads(Path("profile_db.json").read_text(encoding="utf-8"))

    errs = validate(app_dir, profile_db, load_lessons())
    if errs:
        print("\n".join(f"[FAIL] {e}" for e in errs))
        sys.exit(1)
    posting, brief, plan = load_app(app_dir)
    if not ensure_approved(app_dir, posting, plan):
        print("기획 미승인 — 종료")
        sys.exit(0)

    only = set(a.only.split(",")) if a.only else None
    if only and unknown_only_ids(only, plan):
        print(f"[FAIL] --only에 plan에 없는 item_id: {unknown_only_ids(only, plan)} "
              f"(가능: {[d.item_id for d in plan.documents]})")
        sys.exit(1)
    dd = drafts_dir(app_dir)
    dd.mkdir(exist_ok=True)
    ran = set()   # 이번 실행에서 승인된 문서 — 이것들의 .docx만 다시 만든다
    for doc in plan.documents:
        if only and doc.item_id not in only:
            continue
        print(f"\n######## {doc.item_id} ({doc.doc_type}) ########")
        job = job_for(doc, posting, brief, prior_answers(app_dir, plan, doc.item_id))
        r = run_job(job, profile_db, log_extra={"app_slug": plan.slug, "item_id": doc.item_id})
        name = f"{doc.item_id}.txt" if r["approved"] else f"{doc.item_id}.unapproved.txt"
        (dd / name).write_text(r["final"] or r["draft"], encoding="utf-8")
        print(f"→ {dd.name}/{name}")
        if r["approved"]:
            ran.add(doc.item_id)

    build_outputs(app_dir, posting, plan, profile_db["candidate"]["name"], ran, output_dir(posting))


def build_outputs(app_dir: Path, posting: Posting, plan: ApplicationPlan, cand: str, ran: set[str], out_dir: Path):
    """이번 실행에서 승인된 문서에 해당하는 .docx만 만든다. 기존 파일은 safe_output으로 보존."""
    answer_ids = {d.item_id for d in plan.documents if d.doc_type == "application_answer"}
    if ran & answer_ids:
        spec = answers_spec(app_dir, posting, plan, cand)
        sp = Path(app_dir) / ("answers_spec_dryrun.json" if config.DRY_RUN else "answers_spec.json")
        sp.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
        target = safe_output(Path(out_dir) / f"{cand} - Application Answers.docx")
        subprocess.run([sys.executable, "build_answers_docx.py", str(sp), str(target)])
    cv = drafts_dir(app_dir) / "cv.txt"
    if "cv" in ran and cv.exists():
        target = safe_output(Path(out_dir) / f"{cand} - CV.docx")
        subprocess.run([sys.executable, "build_docx.py", str(cv), posting.company, posting.role,
                        str(out_dir), target.stem])


if __name__ == "__main__":
    main()
