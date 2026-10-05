import json
import unittest

from llms import _repair_double_encoded_list_fields
from schemas import Draft


class RepairTests(unittest.TestCase):
    def test_existing_case_claims_list_as_string(self):
        args = {"doc_type": "cv", "content": "c", "claims": json.dumps([{"text": "t", "evidence_ids": ["a"]}])}
        d = Draft(**_repair_double_encoded_list_fields(Draft, args))
        self.assertEqual(d.claims[0].evidence_ids, ["a"])

    def test_whole_draft_nested_inside_claims_string(self):
        # 2026-10-05 실제 실행: Claude가 Draft 전체를 JSON 문자열로 만들어 claims 칸에만 넣어 보냄
        nested = {"doc_type": "application_answer", "content": "Answer text.",
                  "claims": [{"text": "Answer text.", "evidence_ids": ["proj_pipeline"]}]}
        args = {"claims": json.dumps(nested)}
        d = Draft(**_repair_double_encoded_list_fields(Draft, args))
        self.assertEqual(d.content, "Answer text.")
        self.assertEqual(d.doc_type, "application_answer")
        self.assertEqual(d.claims[0].evidence_ids, ["proj_pipeline"])

    def test_top_level_fields_win_over_nested(self):
        nested = {"doc_type": "cv", "content": "nested", "claims": []}
        args = {"doc_type": "application_answer", "content": "top", "claims": json.dumps(nested)}
        fixed = _repair_double_encoded_list_fields(Draft, args)
        self.assertEqual((fixed["content"], fixed["doc_type"]), ("top", "application_answer"))


if __name__ == "__main__":
    unittest.main()
