"""
실행:
  DRY_RUN=1 python main.py --doc-type cv --jd jd.example.txt --profile profile_db.example.json \
      --company "Example FC" --role "Football Data Scientist"
  python main.py --doc-type application_answer --question "Describe a time you failed" --word-limit 250 ...
  python main.py --doc-type cover_letter --word-limit 400 ...
"""
import argparse
import json
import os
import sys
import time
import uuid

sys.stdout.reconfigure(encoding="utf-8")

from langgraph.types import Command

import config
from graph import build
from schemas import JobInput


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--doc-type", required=True, choices=["cv", "application_answer", "cover_letter"])
    p.add_argument("--jd", required=True, help="JD 텍스트 파일")
    p.add_argument("--profile", required=True, help="profile_db.json")
    p.add_argument("--company", required=True)
    p.add_argument("--role", required=True)
    p.add_argument("--question")
    p.add_argument("--word-limit", type=int)
    p.add_argument("--char-limit", type=int, help="글자수 제한(공백 포함). word-limit과 동시 사용 금지")
    p.add_argument("--language", default="English", help="작성 언어, 예: Korean")
    p.add_argument("--prior-answers", help="이전 문항 답변들이 담긴 JSON 리스트 파일")
    a = p.parse_args()

    job = JobInput(
        doc_type=a.doc_type, jd_text=open(a.jd, encoding="utf-8").read(), company=a.company, role=a.role,
        question=a.question, word_limit=a.word_limit, char_limit=a.char_limit, language=a.language,
        prior_answers=json.load(open(a.prior_answers, encoding="utf-8")) if a.prior_answers else [],
    ).model_dump()
    profile_db = json.load(open(a.profile, encoding="utf-8"))
    run_job(job, profile_db)


def ask(prompt: str) -> str:
    """사람 승인 입력. 입력이 끊기면(EOF — `echo n |`로 첫 답만 흘려보낸 비대화형 실행 등) 미승인 'n'으로 본다.
    자동 승인이 아니라 자동 '미승인'이므로 human_gate 규칙에 어긋나지 않는다."""
    try:
        return input(prompt)
    except EOFError:
        print("(입력 없음 → n)")
        return "n"


def log_path(doc_type: str, log_extra: dict | None = None) -> str:
    """runs/<시각>_<doc_type>[_<item>]_<6자리>.json — 같은 초에 끝난 실행끼리 로그를 덮어쓰지 않게 한다."""
    item = (log_extra or {}).get("item_id")
    name = f"{time.strftime('%Y%m%d-%H%M%S')}_{doc_type}{'_' + item if item else ''}_{uuid.uuid4().hex[:6]}.json"
    return os.path.join(config.LOG_DIR, name)


def run_job(job: dict, profile_db: dict, log_extra: dict | None = None) -> dict:
    """그래프 1회 실행: 작가↔배심원단 루프 → human_gate(사람 승인) → runs/ 로그 저장."""
    app = build()
    thread = {"configurable": {"thread_id": str(uuid.uuid4())}}
    state = app.invoke({"job": job, "profile_db": profile_db, "round": 0, "verdicts": []}, thread)

    # human_gate에서 멈춘 상태. interrupt payload를 보여주고 승인 여부를 받는다.
    pending = state["__interrupt__"][0].value
    print("\n=== 배심원단 결과 ===")
    print(f"decision={pending['decision']}  round={pending['round']}")
    for f in pending["failed"]:
        print(f"  ✗ {f['judge']}: {f['fix']}")
    print("\n=== 초안 ===\n" + pending["draft"] + "\n")

    answer = "y" if config.DRY_RUN else ask("제출 승인? (y/n): ")
    state = app.invoke(Command(resume=answer), thread)

    # 라운드별 전체 로그 저장 — 나중에 '자주 놓치는 항목'을 분석해 프롬프트를 고칠 재료
    os.makedirs(config.LOG_DIR, exist_ok=True)
    path = log_path(job["doc_type"], log_extra)
    json.dump({**(log_extra or {}), "job": job, "rounds": state["round"], "decision": state["decision"],
               "approved": state["approved"], "verdicts": state["verdicts"],
               "final": state["final"]}, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"approved={state['approved']}  log={path}")
    return {"approved": state["approved"], "final": state["final"], "draft": state["draft"]["content"],
            "decision": state["decision"], "log": path}


if __name__ == "__main__":
    main()
