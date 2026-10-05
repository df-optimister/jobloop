"""
심사관 실행기. 이름을 받아 코드 검사인지 LLM 검사인지 판단해 JudgeVerdict를 돌려준다.
"""
import json

from llms import judge_llm
from judges.deterministic import REGISTRY as DETERMINISTIC
from judges.prompts import COMMON, JUDGES
from schemas import JudgeVerdict


def _relevant_entries(draft: dict, profile_db: dict) -> list[dict]:
    """심사관에게는 초안이 인용한 profile_db 항목만 보여준다(토큰 절약 + 집중)."""
    cited = {i for c in draft["claims"] for i in c["evidence_ids"]}
    return [e for e in profile_db["entries"] if e["id"] in cited]


def _cited_company_facts(draft: dict, job: dict) -> list[dict]:
    """초안이 인용한 기업 사실(co_ id, 기획 단계 brief에서 출처 검증됨)만 보여준다."""
    cited = {i for c in draft["claims"] for i in c["evidence_ids"]}
    return [f for f in job.get("company_brief") or [] if f["id"] in cited]


def run_judge(name: str, draft: dict, job: dict, profile_db: dict, round_no: int) -> JudgeVerdict:
    if name in DETERMINISTIC:
        v = DETERMINISTIC[name](draft, job, profile_db)
    else:
        messages = [
            {"role": "system", "content": COMMON + "\n" + JUDGES[name]},
            {"role": "user", "content": json.dumps({
                "JUDGE": name, "ROUND": round_no,                      # 모의 객체용 마커도 겸함
                "doc_type": job["doc_type"], "company": job["company"], "role": job["role"],
                "question": job.get("question"), "prior_answers": job.get("prior_answers", []),
                "jd_text": job["jd_text"],
                "draft": draft["content"], "claims": draft["claims"],
                "profile_db_entries": _relevant_entries(draft, profile_db),
                "known_gaps": profile_db.get("known_gaps", []),
                "company_facts": _cited_company_facts(draft, job),
            }, ensure_ascii=False)},
        ]
        if name == "company_specificity" and job.get("company_brief"):
            body = json.loads(messages[1]["content"])
            body["company_brief"] = job["company_brief"]
            messages[1]["content"] = json.dumps(body, ensure_ascii=False)
        # 모의 객체 마커(문자열 검색용)
        messages[1]["content"] += f"\nJUDGE={name} ROUND={round_no}"
        v = judge_llm(name).invoke(messages)
    v.judge, v.round = name, round_no
    return v
