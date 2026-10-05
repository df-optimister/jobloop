import json
import unittest
from unittest import mock

import judges.run as jr
import writer
from schemas import Claim, Draft, JudgeVerdict


class Capture:
    def __init__(self, ret):
        self.ret, self.messages = ret, None

    def invoke(self, messages):
        self.messages = messages
        return self.ret


JOB = {"doc_type": "application_answer", "company": "Acme", "role": "DS", "question": "Why?", "word_limit": 200,
       "jd_text": "JD", "company_brief": [{"id": "co_1", "text": "Acme ships fast.", "source_url": "u", "quote": "q"},
                                          {"id": "co_2", "text": "Other.", "source_url": "u", "quote": "q"}],
       "doc_plan": {"item_id": "q1", "lead_evidence_ids": ["edu_msc"], "angle": "lead with X"}}


class WiringTests(unittest.TestCase):
    def test_writer_payload_has_brief_and_plan(self):
        cap = Capture(Draft(doc_type="application_answer", content="c", claims=[]))
        with mock.patch.object(writer, "writer_llm", return_value=cap):
            writer.write(JOB, {"entries": [], "known_gaps": []}, None, [], 1)
        payload = cap.messages[1]["content"]
        self.assertIn('"company_brief"', payload)
        self.assertIn("lead with X", payload)
        self.assertIn("co_", writer.SYSTEM)
        self.assertIn("doc_plan", writer.SYSTEM)

    def test_judge_gets_only_cited_company_facts(self):
        cap = Capture(JudgeVerdict(judge="x", score=5, passed=True))
        d = {"content": "c", "claims": [Claim(text="Acme ships fast.", evidence_ids=["co_1"]).model_dump()]}
        with mock.patch.object(jr, "judge_llm", return_value=cap):
            jr.run_judge("fact_grounding", d, JOB, {"entries": [], "known_gaps": []}, 1)
        body = json.loads(cap.messages[1]["content"].rsplit("\nJUDGE=", 1)[0])
        self.assertEqual([f["id"] for f in body["company_facts"]], ["co_1"])

    def test_company_specificity_gets_full_brief(self):
        cap = Capture(JudgeVerdict(judge="x", score=5, passed=True))
        d = {"content": "c", "claims": []}
        with mock.patch.object(jr, "judge_llm", return_value=cap):
            jr.run_judge("company_specificity", d, JOB, {"entries": [], "known_gaps": []}, 1)
        body = json.loads(cap.messages[1]["content"].rsplit("\nJUDGE=", 1)[0])
        self.assertEqual(len(body["company_brief"]), 2)


if __name__ == "__main__":
    unittest.main()
