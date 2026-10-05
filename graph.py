"""
LangGraph 그래프 정의.

  START → writer ──Send×N──▶ judge(병렬) → aggregate
            ▲                                  │
            └──────── revise (round < MAX) ────────┤
                                                   ├── pass → human_gate → END
                                                   └── escalate (round == MAX) → human_gate → END

가벼운 형식류 심사관(tone_length/uk_cv_convention/bullet_format)은 gpt-5-mini로 돌아
gpt-5와 별도 레이트리밋 버킷을 쓴다(config.LIGHT_JUDGES, llms.judge_llm). 그래서 병렬
fan-out으로도 gpt-5 쪽 TPM/RPD 부담이 예전만큼 크지 않다.
"""
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt

import config
from judges.run import run_judge
from router import VETO, panel_for
from schemas import LoopState
from writer import write


# ---------- 노드 ----------
def writer_node(state: LoopState) -> dict:
    round_no = state.get("round", 0) + 1
    fixes = [v["fix_instruction"] for v in state.get("verdicts", [])
             if v["round"] == round_no - 1 and not v["passed"] and v["fix_instruction"]]
    draft = write(state["job"], state["profile_db"], state.get("draft"), fixes, round_no)
    return {"draft": draft.model_dump(), "round": round_no}


def fan_out(state: LoopState):
    """작가가 끝나면 문서 종류에 맞는 심사관들에게 동시에 보낸다."""
    return [Send("judge", {"judge_name": name, "draft": state["draft"], "job": state["job"],
                           "profile_db": state["profile_db"], "round": state["round"]})
            for name in panel_for(state["job"]["doc_type"])]


def judge_node(payload: dict) -> dict:
    v = run_judge(payload["judge_name"], payload["draft"], payload["job"], payload["profile_db"], payload["round"])
    return {"verdicts": [v.model_dump()]}


def aggregate_node(state: LoopState) -> dict:
    cur = [v for v in state["verdicts"] if v["round"] == state["round"]]
    veto_fail = [v for v in cur if v["judge"] in VETO and not v["passed"]]
    other_fail = [v for v in cur if v["judge"] not in VETO and not v["passed"]]
    if not veto_fail and not other_fail:
        return {"decision": "pass"}
    if state["round"] >= config.MAX_ROUNDS:
        return {"decision": "escalate"}
    return {"decision": "revise"}


def route_after_aggregate(state: LoopState) -> str:
    return "writer" if state["decision"] == "revise" else "human_gate"


def human_gate_node(state: LoopState) -> dict:
    """사람 승인. interrupt()로 실행을 멈추고, Command(resume=...)로 재개된다."""
    cur = [v for v in state["verdicts"] if v["round"] == state["round"]]
    answer = interrupt({
        "decision": state["decision"],
        "round": state["round"],
        "draft": state["draft"]["content"],
        "failed": [{"judge": v["judge"], "fix": v["fix_instruction"]} for v in cur if not v["passed"]],
    })
    approved = str(answer).strip().lower() in ("y", "yes", "approve")
    return {"approved": approved, "final": state["draft"]["content"] if approved else None}


# ---------- 조립 ----------
def build():
    g = StateGraph(LoopState)
    g.add_node("writer", writer_node)
    g.add_node("judge", judge_node)
    g.add_node("aggregate", aggregate_node)
    g.add_node("human_gate", human_gate_node)

    g.add_edge(START, "writer")
    g.add_conditional_edges("writer", fan_out, ["judge"])
    g.add_edge("judge", "aggregate")
    g.add_conditional_edges("aggregate", route_after_aggregate, ["writer", "human_gate"])
    g.add_edge("human_gate", END)
    return g.compile(checkpointer=InMemorySaver())
