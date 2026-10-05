import unittest

from pydantic import ValidationError

from schemas import ApplicationPlan, DocPlan, JobInput, Outcome, Posting


class SchemaTests(unittest.TestCase):
    def test_jobinput_backward_compatible(self):
        j = JobInput(doc_type="cv", jd_text="x", company="C", role="R")
        self.assertEqual(j.company_brief, [])
        self.assertIsNone(j.doc_plan)

    def test_plan_roundtrip(self):
        plan = ApplicationPlan(
            slug="acme-ds", role_kind="technical", fit=[], risks=[], recommendation="go", rationale="r",
            documents=[DocPlan(item_id="cv", doc_type="cv", lead_evidence_ids=["edu_msc"], angle="a")])
        self.assertEqual(ApplicationPlan.model_validate_json(plan.model_dump_json()), plan)

    def test_posting_rejects_unknown_ats(self):
        with self.assertRaises(ValidationError):
            Posting(url=None, ats="workday", company="C", role="R", jd_text="x", fetched_at="t")

    def test_outcome_status_enum(self):
        self.assertEqual(Outcome(status="planned").hypotheses, [])
        with self.assertRaises(ValidationError):
            Outcome(status="ghosted")


if __name__ == "__main__":
    unittest.main()
