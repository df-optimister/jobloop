import tempfile
import unittest
from pathlib import Path

from run_application import answers_spec, job_for, prior_answers
from schemas import ApplicationPlan, CompanyBrief, DocPlan, Posting

POSTING = Posting(url="u", ats="manual", company="Acme", role="DS", jd_text="JD", fetched_at="t")
DOCS = [DocPlan(item_id="cv", doc_type="cv", lead_evidence_ids=[], angle="a"),
        DocPlan(item_id="q1", doc_type="application_answer", question="Why?", word_limit=200,
                lead_evidence_ids=[], angle="a"),
        DocPlan(item_id="q2", doc_type="application_answer", question="Best?", word_limit=250,
                lead_evidence_ids=[], angle="a")]
PLAN = ApplicationPlan(slug="acme-ds", role_kind="technical", fit=[], risks=[], recommendation="go",
                       rationale="r", documents=DOCS)


class RunAppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        (self.d / "drafts").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_prior_answers_from_drafts(self):
        (self.d / "drafts" / "q1.txt").write_text("Answer one.", encoding="utf-8")
        (self.d / "drafts" / "cv.txt").write_text("CV text", encoding="utf-8")
        self.assertEqual(prior_answers(self.d, PLAN, "q2"), ["Answer one."])
        self.assertEqual(prior_answers(self.d, PLAN, "q1"), [])

    def test_unapproved_draft_not_used_as_prior(self):
        (self.d / "drafts" / "q1.unapproved.txt").write_text("Draft.", encoding="utf-8")
        self.assertEqual(prior_answers(self.d, PLAN, "q2"), [])

    def test_job_for(self):
        brief = CompanyBrief(company="Acme", analysis="a", researched_at="t", facts=[])
        job = job_for(DOCS[1], POSTING, brief, ["prev"])
        self.assertEqual((job["question"], job["word_limit"], job["prior_answers"]), ("Why?", 200, ["prev"]))
        self.assertEqual(job["doc_plan"]["item_id"], "q1")
        self.assertEqual(job["company_brief"], [])

    def test_answers_spec(self):
        (self.d / "drafts" / "q1.txt").write_text("A1", encoding="utf-8")
        spec = answers_spec(self.d, POSTING, PLAN, "Jane Doe")
        self.assertEqual(len(spec["items"]), 1)   # q2 승인본 없음 → 제외, cv는 문항 아님
        self.assertEqual(spec["items"][0]["unit"], "words")
        self.assertIn("Jane Doe", spec["title"])


class LogPathTests(unittest.TestCase):
    def test_same_second_logs_do_not_collide(self):
        from main import log_path
        a = log_path("application_answer", {"item_id": "q11"})
        b = log_path("application_answer", {"item_id": "q12"})
        c = log_path("application_answer", None)
        d = log_path("application_answer", None)
        self.assertEqual(len({a, b, c, d}), 4)
        self.assertIn("q11", a)


class ReviewFixRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_eof_on_prompt_means_no(self):
        from unittest import mock
        import main
        with mock.patch("builtins.input", side_effect=EOFError):
            self.assertEqual(main.ask("제출 승인? (y/n): "), "n")

    def test_existing_docx_is_not_overwritten(self):
        from run_application import safe_output
        target = self.d / "Jane - CV.docx"
        self.assertEqual(safe_output(target), target)
        target.write_text("hand edited", encoding="utf-8")
        other = safe_output(target)
        self.assertNotEqual(other, target)
        self.assertEqual(other.parent, target.parent)
        self.assertTrue(other.name.startswith("Jane - CV"))
        self.assertEqual(other.suffix, ".docx")

    def test_unknown_only_ids_rejected(self):
        from run_application import unknown_only_ids
        self.assertEqual(unknown_only_ids({"Q12", "q1"}, PLAN), ["Q12"])

    def test_outputs_built_only_for_items_that_ran(self):
        from unittest import mock
        import run_application as ra
        dd = ra.drafts_dir(self.d)
        dd.mkdir(parents=True)
        (dd / "cv.txt").write_text("CV", encoding="utf-8")
        (dd / "q1.txt").write_text("A1", encoding="utf-8")
        with mock.patch.object(ra.subprocess, "run") as run:
            ra.build_outputs(self.d, POSTING, PLAN, "Jane", ran={"q1"}, out_dir=self.d / "out")
        scripts = [c.args[0][1] for c in run.call_args_list]
        self.assertEqual(scripts, ["build_answers_docx.py"])
        with mock.patch.object(ra.subprocess, "run") as run:
            ra.build_outputs(self.d, POSTING, PLAN, "Jane", ran=set(), out_dir=self.d / "out")
        self.assertEqual(run.call_count, 0)

    def test_dry_run_isolated_from_real_drafts_and_outputs(self):
        from unittest import mock
        import run_application as ra
        with mock.patch.object(ra.config, "DRY_RUN", True):
            self.assertEqual(ra.drafts_dir(self.d).name, "drafts_dryrun")
            self.assertIn("_dryrun", str(ra.output_dir(POSTING)))
        with mock.patch.object(ra.config, "DRY_RUN", False):
            self.assertEqual(ra.drafts_dir(self.d).name, "drafts")
            self.assertNotIn("_dryrun", str(ra.output_dir(POSTING)))

    def test_plan_approval_eof_means_not_approved(self):
        from unittest import mock
        import run_application as ra
        plan = PLAN.model_copy(deep=True)
        with mock.patch.object(ra.config, "DRY_RUN", False), mock.patch("builtins.input", side_effect=EOFError):
            self.assertFalse(ra.ensure_approved(self.d, POSTING, plan))
        self.assertIsNone(plan.approved_at)


if __name__ == "__main__":
    unittest.main()
