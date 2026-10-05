import json
import tempfile
import unittest
from pathlib import Path

from validate_plan import normalise, validate

PROFILE = {"entries": [{"id": "edu_msc"}, {"id": "proj_pipeline"}, {"id": "proj_app_failure"}],
           "known_gaps": []}


def make_app(root: Path, plan_over=None, fact_quote="We ship fast, with low ego.", with_brief=True):
    d = root / "acme-ds"
    (d / "sources").mkdir(parents=True)
    (d / "posting.json").write_text(json.dumps({
        "url": "https://x", "ats": "manual", "company": "Acme", "role": "DS", "jd_text": "JD",
        "questions": [], "fetched_at": "t"}), encoding="utf-8")
    if with_brief:
        (d / "sources" / "01.txt").write_text("About us\nWe ship fast,\nwith low ego. Our team…",
                                              encoding="utf-8")
        (d / "sources" / "index.json").write_text(json.dumps({"https://acme.com/about": "01.txt"}),
                                                  encoding="utf-8")
        (d / "brief.json").write_text(json.dumps({
            "company": "Acme", "analysis": "a", "researched_at": "t",
            "facts": [{"id": "co_1", "text": "Acme ships fast.", "source_url": "https://acme.com/about",
                       "quote": fact_quote}]}), encoding="utf-8")
    plan = {"slug": "acme-ds", "role_kind": "technical", "fit": [], "risks": [], "recommendation": "go",
            "rationale": "r", "market": "영미권", "language": "en", "company_size": "스타트업", "submission": "CV+문항",
            "documents": [
                {"item_id": "cv", "doc_type": "cv", "lead_evidence_ids": ["proj_pipeline"],
                 "avoid_evidence_ids": ["proj_app_failure"], "angle": "a"},
                {"item_id": "q1", "doc_type": "application_answer", "question": "Why?", "word_limit": 200,
                 "question_intent": "지원동기", "lead_evidence_ids": ["edu_msc"], "angle": "a"}]}
    plan.update(plan_over or {})
    (d / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    return d


class ValidateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_ok(self):
        self.assertEqual(validate(make_app(self.root), PROFILE), [])

    def test_quote_normalisation(self):
        self.assertEqual(normalise("It’s  a test – ok"), normalise("it's a test - ok"))
        errs = validate(make_app(self.root, fact_quote="We never ship."), PROFILE)
        self.assertTrue(any("co_1" in e and "quote" in e for e in errs), errs)

    def test_unknown_evidence_id(self):
        docs = [{"item_id": "cv", "doc_type": "cv", "lead_evidence_ids": ["proj_unknown"], "angle": "a"}]
        errs = validate(make_app(self.root, {"documents": docs}), PROFILE)
        self.assertTrue(any("proj_unknown" in e for e in errs), errs)

    def test_lead_avoid_overlap(self):
        docs = [{"item_id": "cv", "doc_type": "cv", "lead_evidence_ids": ["edu_msc"],
                 "avoid_evidence_ids": ["edu_msc"], "angle": "a"}]
        errs = validate(make_app(self.root, {"documents": docs}), PROFILE)
        self.assertTrue(any("both lead and avoid" in e for e in errs), errs)

    def test_answer_needs_exactly_one_limit(self):
        docs = [{"item_id": "q1", "doc_type": "application_answer", "question": "Why?",
                 "lead_evidence_ids": ["edu_msc"], "angle": "a"}]
        errs = validate(make_app(self.root, {"documents": docs}), PROFILE)
        self.assertTrue(any("exactly one of word_limit/char_limit" in e for e in errs), errs)

    def test_duplicate_item_and_slug_mismatch(self):
        docs = [{"item_id": "cv", "doc_type": "cv", "lead_evidence_ids": [], "angle": "a"}] * 2
        errs = validate(make_app(self.root, {"documents": docs, "slug": "other"}), PROFILE)
        self.assertTrue(any("duplicate item_id" in e for e in errs), errs)
        self.assertTrue(any("slug" in e for e in errs), errs)

    def test_brief_optional(self):
        self.assertEqual(validate(make_app(self.root, with_brief=False), PROFILE), [])

    def test_missing_source_file(self):
        d = make_app(self.root)
        (d / "sources" / "01.txt").unlink()
        self.assertTrue(any("source" in e for e in validate(d, PROFILE)))

    def test_default_limit_is_800_chars(self):
        docs = [{"item_id": "q1", "doc_type": "application_answer", "question": "Why?", "char_limit": 900,
                 "limit_source": "default", "lead_evidence_ids": ["edu_msc"], "angle": "a"}]
        errs = validate(make_app(self.root, {"documents": docs}), PROFILE)
        self.assertTrue(any("800" in e for e in errs), errs)

    def test_default_limit_raise_to_1000_needs_approval(self):
        base = {"item_id": "q1", "doc_type": "application_answer", "question": "Why?", "char_limit": 1000,
                "limit_source": "default", "question_intent": "지원동기", "lead_evidence_ids": ["edu_msc"], "angle": "a"}
        self.assertEqual(validate(make_app(self.root, {"documents": [dict(base, limit_raise_approved=True)]}),
                                  PROFILE), [])

    def test_default_limit_never_above_1000(self):
        docs = [{"item_id": "q1", "doc_type": "application_answer", "question": "Why?", "char_limit": 1200,
                 "limit_source": "default", "limit_raise_approved": True, "lead_evidence_ids": ["edu_msc"],
                 "angle": "a"}]
        errs = validate(make_app(self.root, {"documents": docs}), PROFILE)
        self.assertTrue(any("1000" in e for e in errs), errs)

    def test_default_limit_must_be_chars_not_words(self):
        docs = [{"item_id": "q1", "doc_type": "application_answer", "question": "Why?", "word_limit": 200,
                 "limit_source": "default", "lead_evidence_ids": ["edu_msc"], "angle": "a"}]
        errs = validate(make_app(self.root, {"documents": docs}), PROFILE)
        self.assertTrue(any("char_limit" in e for e in errs), errs)


if __name__ == "__main__":
    unittest.main()
