"""
모델 팩토리. 실제 API 클라이언트와 DRY_RUN용 모의 객체를 같은 인터페이스로 제공한다.
모든 호출은 `llm.invoke(messages)` 한 가지 형태만 쓴다.
"""
import json
from typing import Type

from pydantic import BaseModel

import config
from schemas import Claim, Draft, JudgeVerdict


class _MockStructured:
    """DRY_RUN 전용. 스키마별로 그럴듯한 객체를 돌려준다."""

    def __init__(self, schema: Type[BaseModel], role: str):
        self.schema, self.role = schema, role

    def invoke(self, messages):
        text = "\n".join(m.get("content", "") if isinstance(m, dict) else str(m) for m in messages)
        if self.schema is Draft:
            doc_type = "cv" if "doc_type: cv" in text else (
                "application_answer" if "doc_type: application_answer" in text else "cover_letter")
            return Draft(
                doc_type=doc_type,
                content="Built a reproducible analysis pipeline in Python during an MSc dissertation "
                        "(First Class), covering data engineering and model evaluation.",
                claims=[Claim(text="Built a reproducible analysis pipeline in Python during an MSc dissertation "
                                   "(First Class), covering data engineering and model evaluation.",
                              evidence_ids=["edu_msc", "proj_pipeline"])],
            )
        if self.schema is JudgeVerdict:
            # 1라운드에서 과장 탐지관만 일부러 떨어뜨려 루프가 도는 것을 보여준다.
            fail = "JUDGE=exaggeration_redteam" in text and "ROUND=1" in text
            return JudgeVerdict(
                judge="mock", score=2 if fail else 4, passed=not fail,
                evidence=["(mock)"],
                fix_instruction="Replace 'covering data engineering' with the specific step you did."
                if fail else None,
            )
        raise ValueError(self.schema)


def _repair_double_encoded_list_fields(schema: Type[BaseModel], args: dict) -> dict:
    """Claude tool-calling이 가끔 list[object] 필드(예: Draft.claims)를 그 배열을 담은 JSON
    문자열로 한 번 더 감싸서 내보낸다(관찰된 실패율 최대 80%). 문자열 내용 자체는 유효한 JSON이라
    파싱해서 복구한다. 실패하면 원본을 그대로 반환해 평소처럼 스키마 검증 에러가 나게 둔다."""
    fixed = dict(args)
    for name, field in schema.model_fields.items():
        val = fixed.get(name)
        if isinstance(val, str) and getattr(field.annotation, "__origin__", None) is list:
            try:
                parsed = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(parsed, dict) and name in parsed:
                # 객체 전체(예: Draft 전체)를 이 칸에 문자열로 넣어 보낸 경우 — 비어 있는 다른 필드도 꺼내 채운다
                # (2026-10-05 실제 실행에서 8회 연속 관찰). 최상위에 이미 있는 값이 우선.
                for k, v in parsed.items():
                    if k != name and k in schema.model_fields and k not in fixed:
                        fixed[k] = v
                parsed = parsed[name]
            if isinstance(parsed, list):
                fixed[name] = parsed
    return fixed


class _ToolCallWithRepair:
    """with_structured_output 대신 저수준 bind_tools로 호출해, 위 이중 인코딩 문제를 검증 전에
    복구한다. 인터페이스는 with_structured_output과 동일하게 .invoke(messages) -> schema 인스턴스."""

    def __init__(self, llm, schema: Type[BaseModel]):
        self.schema = schema
        self.bound = llm.bind_tools([schema], tool_choice={"type": "tool", "name": schema.__name__})

    def invoke(self, messages):
        resp = self.bound.invoke(messages)
        if not resp.tool_calls:
            raise ValueError(f"{self.schema.__name__}: no tool call in response")
        args = _repair_double_encoded_list_fields(self.schema, resp.tool_calls[0]["args"])
        return self.schema(**args)


def _real(model: str, schema: Type[BaseModel]):
    if model.startswith("claude"):
        from langchain_anthropic import ChatAnthropic
        llm = ChatAnthropic(model=model, max_tokens=8192)
        return _ToolCallWithRepair(llm, schema)
    elif model.startswith("gemini"):
        from langchain_google_genai import ChatGoogleGenerativeAI
        llm = ChatGoogleGenerativeAI(model=model, temperature=0)
    else:
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(model=model, temperature=0)
    return llm.with_structured_output(schema)


def writer_llm():
    return _MockStructured(Draft, "writer") if config.DRY_RUN else _real(config.WRITER_MODEL, Draft)


def judge_llm(judge_name: str):
    if judge_name == "exaggeration_redteam":
        model = config.REDTEAM_MODEL
    elif judge_name in config.LIGHT_JUDGES:
        model = config.JUDGE_MODEL_LIGHT
    else:
        model = config.JUDGE_MODEL
    return _MockStructured(JudgeVerdict, judge_name) if config.DRY_RUN else _real(model, JudgeVerdict)
