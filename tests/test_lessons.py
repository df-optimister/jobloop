import json
import tempfile
import unittest
from pathlib import Path

from lessons import doc_kind, matching_lessons
from schemas import ApplicationPlan, DocPlan, Lesson
from validate_plan import validate

PROFILE = {"entries": [{"id": "edu_msc"}], "known_gaps": []}


def lesson(lid, status="확정", **cond):
    return Lesson(id=lid, layer="L1 구조", rule="r", mechanism="m", status=status, status_reason="s",
                  updated_at="2026-10-05", conditions=cond)


def plan(docs, **over):
    base = dict(slug="acme-ds", role_kind="technical", fit=[], risks=[], recommendation="go", rationale="r",
                market="영미권", language="en", company_size="스타트업", submission="CV+문항", documents=docs)
    base.update(over)
    return ApplicationPlan(**base)


ANSWER = DocPlan(item_id="q1", doc_type="application_answer", question="Why?", char_limit=800,
                 limit_source="default", question_intent="지원동기", lead_evidence_ids=["edu_msc"], angle="a")
CV = DocPlan(item_id="cv", doc_type="cv", lead_evidence_ids=["edu_msc"], angle="a")


class MatchTests(unittest.TestCase):
    def test_any_matches_everything(self):
        self.assertEqual([l.id for l in matching_lessons([lesson("L-1")], plan([CV]))], ["L-1"])

    def test_plan_level_condition(self):
        ls = [lesson("L-ko", market=["한국 공채"]), lesson("L-size", company_size=["스타트업", "중소"])]
        self.assertEqual([l.id for l in matching_lessons(ls, plan([CV]))], ["L-size"])

    def test_doc_level_condition_needs_one_matching_doc(self):
        ls = [lesson("L-motive", doc_type=["서술형"], question_intent=["지원동기"]),
              lesson("L-trend", question_intent=["트렌드·제품"])]
        self.assertEqual([l.id for l in matching_lessons(ls, plan([CV, ANSWER]))], ["L-motive"])
        self.assertEqual(matching_lessons(ls, plan([CV])), [])

    def test_retired_lessons_never_match(self):
        self.assertEqual(matching_lessons([lesson("L-old", status="폐기")], plan([CV])), [])

    def test_short_field_kind(self):
        short = ANSWER.model_copy(update={"char_limit": 200})
        self.assertEqual((doc_kind(ANSWER), doc_kind(short), doc_kind(CV)), ("서술형", "짧은 칸", "cv"))


class ValidateLessonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name) / "acme-ds"
        self.d.mkdir()
        (self.d / "posting.json").write_text(json.dumps({
            "url": None, "ats": "manual", "company": "Acme", "role": "DS", "jd_text": "JD", "fetched_at": "t"}),
            encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, p):
        (self.d / "plan.json").write_text(p.model_dump_json(), encoding="utf-8")
        return self.d

    def test_missing_confirmed_lesson_fails(self):
        errs = validate(self.write(plan([ANSWER])), PROFILE, lessons=[lesson("L-1")])
        self.assertTrue(any("L-1" in e for e in errs), errs)

    def test_missing_hypothesis_lesson_fails(self):
        errs = validate(self.write(plan([ANSWER])), PROFILE, lessons=[lesson("L-2", status="가설")])
        self.assertTrue(any("L-2" in e for e in errs), errs)

    def test_checked_lessons_pass(self):
        p = plan([ANSWER], lessons_checked=[{"lesson_id": "L-1", "applies": True, "how": "q1 slot"},
                                            {"lesson_id": "L-2", "applies": False, "how": "not relevant because x"}])
        self.assertEqual(validate(self.write(p), PROFILE, lessons=[lesson("L-1"), lesson("L-2", status="가설")]), [])

    def test_confirmed_not_applied_needs_reason(self):
        p = plan([ANSWER], lessons_checked=[{"lesson_id": "L-1", "applies": False, "how": " "}])
        errs = validate(self.write(p), PROFILE, lessons=[lesson("L-1")])
        self.assertTrue(any("L-1" in e and "reason" in e for e in errs), errs)

    def test_unknown_lesson_id_fails(self):
        p = plan([ANSWER], lessons_checked=[{"lesson_id": "L-9", "applies": True, "how": "x"}])
        errs = validate(self.write(p), PROFILE, lessons=[])
        self.assertTrue(any("L-9" in e for e in errs), errs)

    def test_facets_and_intent_required_for_new_plans(self):
        p = plan([ANSWER.model_copy(update={"question_intent": None})], company_size=None)
        errs = validate(self.write(p), PROFILE, lessons=[])
        self.assertTrue(any("company_size" in e for e in errs), errs)
        self.assertTrue(any("question_intent" in e for e in errs), errs)

    def test_retro_plans_skip_lesson_checks(self):
        p = plan([ANSWER], retro=True, company_size=None)
        self.assertEqual(validate(self.write(p), PROFILE, lessons=[lesson("L-1")]), [])


if __name__ == "__main__":
    unittest.main()
