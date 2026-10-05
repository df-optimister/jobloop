import unittest

from judges.deterministic import claims_integrity, cv_structure

PROFILE = {"entries": [
    {"id": "work_coordinator", "period": "Jul 2024 – Sep 2024", "text": "Project Coordinator, Example Ltd."},
    {"id": "edu_msc", "period": "Oct 2024 – Dec 2025", "text": "MSc Data Science, Example University."},
    {"id": "proj_app", "period": "May 2026 – present", "text": "Booking app."},
    {"id": "proj_app_failure", "text": "fallback"}], "known_gaps": []}


def draft(content, claims):
    return {"doc_type": "cv", "content": content, "claims": claims}


class ClaimsIntegrityTests(unittest.TestCase):
    def test_co_id_allowed_when_in_brief(self):
        job = {"doc_type": "application_answer", "company_brief": [{"id": "co_1"}]}
        v = claims_integrity(draft("x", [{"text": "Acme ships.", "evidence_ids": ["co_1"]}]), job, PROFILE)
        self.assertTrue(v.passed, v.fix_instruction)

    def test_unknown_co_id_rejected(self):
        job = {"doc_type": "application_answer", "company_brief": [{"id": "co_1"}]}
        v = claims_integrity(draft("x", [{"text": "Acme ships.", "evidence_ids": ["co_9"]}]), job, PROFILE)
        self.assertFalse(v.passed)
        self.assertIn("co_9", v.fix_instruction)

    def test_avoided_id_rejected(self):
        job = {"doc_type": "cv", "doc_plan": {"avoid_evidence_ids": ["proj_app_failure"]}}
        v = claims_integrity(draft("x", [{"text": "fell back", "evidence_ids": ["proj_app_failure"]}]), job, PROFILE)
        self.assertFalse(v.passed)
        self.assertIn("approved plan", v.fix_instruction)

    def test_legacy_job_without_new_fields(self):
        v = claims_integrity(draft("x", [{"text": "t", "evidence_ids": ["edu_msc"]}]), {"doc_type": "cv"}, PROFILE)
        self.assertTrue(v.passed)


CV_OK = """PROJECTS

Booking app, GymApp | May 2026 – Present
- Built it.

EXPERIENCE

Project Coordinator, Example Ltd | Jul 2024 - Sep 2024
- Bridged three organisations.

EDUCATION

MSc Data Science, Example University | Oct 2024 – Dec 2025
- Merit.
"""


class CvDateTests(unittest.TestCase):
    def claims(self):
        return [{"text": "Booking app, GymApp | May 2026 – Present", "evidence_ids": ["proj_app"]},
                {"text": "Project Coordinator, Example Ltd | Jul 2024 - Sep 2024",
                 "evidence_ids": ["work_coordinator"]}]

    def test_cv_dates_match_with_dash_and_case_variants(self):
        v = cv_structure(draft(CV_OK, self.claims()), {"doc_type": "cv"}, PROFILE)
        self.assertTrue(v.passed, v.evidence)

    def test_cv_dates_wrong_month_fails_with_correct_period(self):
        bad = CV_OK.replace("Jul 2024 - Sep 2024", "Jul 2024 – Oct 2024")
        v = cv_structure(draft(bad, []), {"doc_type": "cv"}, PROFILE)
        self.assertFalse(v.passed)
        self.assertTrue(any("Jul 2024 – Sep 2024" in e for e in v.evidence), v.evidence)

    def test_cv_dates_msc_start_wrong(self):
        bad = CV_OK.replace("Oct 2024 – Dec 2025", "Sep 2024 – Dec 2025")
        v = cv_structure(draft(bad, []), {"doc_type": "cv"}, PROFILE)
        self.assertFalse(v.passed)
        self.assertTrue(any("Oct 2024 – Dec 2025" in e for e in v.evidence), v.evidence)


PROFILE2 = {"entries": [
    {"id": "work_coordinator", "type": "experience", "period": "Jul 2024 – Sep 2024",
     "text": "Project Coordinator, Example Ltd."},
    {"id": "edu_msc", "type": "education", "period": "Oct 2024 – Dec 2025", "text": "MSc Data Science, Example University."},
    {"id": "proj_app", "type": "project", "period": "May 2026 – present", "text": "Booking app."},
    {"id": "work_parttime", "type": "experience", "parent": "proj_app",
     "text": "Worked a part-time job at the gym."},
    {"id": "proj_pipeline", "type": "project", "period": "May 2025 – Aug 2025", "text": "MSc dissertation pipeline."},
    {"id": "proj_pipeline_models", "type": "project", "parent": "proj_pipeline", "text": "Trained CatBoost."}],
    "known_gaps": []}


class CvDateBlockTests(unittest.TestCase):
    def test_swapped_period_fails_when_bullet_cites_entry(self):
        cv = """EXPERIENCE

Project Coordinator, Example Ltd | Oct 2024 – Dec 2025
- Coordinated three partner organisations.
"""
        claims = [{"text": "Coordinated three partner organisations.", "evidence_ids": ["work_coordinator"]}]
        v = cv_structure(draft(cv, claims), {"doc_type": "cv"}, PROFILE2)
        self.assertFalse(v.passed)
        self.assertTrue(any("Jul 2024 – Sep 2024" in e for e in v.evidence), v.evidence)

    def test_short_title_not_confused_with_other_blocks_claims(self):
        cv = """PROJECTS

GymApp | May 2026 – present
- Built the loyalty app alone.

Churn dissertation, Example University | May 2025 – Aug 2025
- Unlike GymApp, this was a research project.
- Trained CatBoost models on event data.
"""
        claims = [{"text": "Built the loyalty app alone.", "evidence_ids": ["proj_app"]},
                  {"text": "Unlike GymApp, this was a research project.", "evidence_ids": ["proj_pipeline"]},
                  {"text": "Trained CatBoost models on event data.", "evidence_ids": ["proj_pipeline_models"]}]
        v = cv_structure(draft(cv, claims), {"doc_type": "cv"}, PROFILE2)
        self.assertTrue(v.passed, v.evidence)

    def test_undated_entry_gets_no_invented_date_hint(self):
        cv = """EXPERIENCE

Part-time Receptionist, GymApp | May 2026 – present
- Proposed a loyalty feature to the owner.
"""
        claims = [{"text": "Proposed a loyalty feature to the owner.", "evidence_ids": ["work_parttime"]}]
        v = cv_structure(draft(cv, claims), {"doc_type": "cv"}, PROFILE2)
        self.assertFalse(v.passed)
        msg = " ".join(v.evidence)
        self.assertNotIn("profile_db says", msg)
        self.assertIn("ask", msg)


if __name__ == "__main__":
    unittest.main()
