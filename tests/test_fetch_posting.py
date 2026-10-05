import json
import unittest
from pathlib import Path

from fetch_posting import FetchError, html_to_text, parse_ashby, parse_generic, parse_greenhouse, parse_lever

FIX = Path(__file__).parent / "fixtures"


class AshbyTests(unittest.TestCase):
    def setUp(self):
        job = json.loads((FIX / "ashby_example_job.json").read_text(encoding="utf-8"))
        form = json.loads((FIX / "ashby_example_form.json").read_text(encoding="utf-8"))
        self.p = parse_ashby(job, form, org="acme")

    def test_core_fields(self):
        self.assertEqual(self.p.ats, "ashby")
        self.assertEqual(self.p.company, "Acme")
        self.assertEqual(self.p.role, "Data Scientist, Product")
        self.assertIn("Berlin", self.p.location)
        self.assertIn("London", self.p.location)
        self.assertIn("activation, engagement, and retention", self.p.jd_text)

    def test_questions(self):
        self.assertEqual(len(self.p.questions), 5)
        titles = [q.title for q in self.p.questions]
        self.assertIn("What is the most impressive thing you’ve done in your career?", titles)
        hear = next(q for q in self.p.questions if q.title.startswith("How did you hear"))
        self.assertIn("LinkedIn", hear.options)
        built = next(q for q in self.p.questions if q.title.startswith("Have you built"))
        self.assertFalse(built.required)
        self.assertIn("password", built.description)
        self.assertEqual(self.p.questions[0].id, "q1")


class OtherAtsTests(unittest.TestCase):
    def test_greenhouse(self):
        job = {"title": "Analyst", "location": {"name": "London"}, "company_name": "Acme",
               "content": "&lt;p&gt;Do &amp;amp; analyse&lt;/p&gt;",
               "questions": [{"label": "Why us?", "required": True, "description": None,
                              "fields": [{"name": "q", "type": "textarea", "values": []}]}]}
        p = parse_greenhouse(job, org="acme")
        self.assertEqual((p.company, p.role, p.location), ("Acme", "Analyst", "London"))
        self.assertIn("Do & analyse", p.jd_text)
        self.assertEqual(p.questions[0].type, "textarea")

    def test_lever(self):
        job = {"text": "Data Scientist", "categories": {"location": "London"},
               "descriptionPlain": "About us.", "lists": [{"text": "You will", "content": "<li>Model</li>"}],
               "additionalPlain": "Benefits."}
        p = parse_lever(job, org="acme")
        self.assertEqual(p.company, "Acme")
        self.assertIn("You will", p.jd_text)
        self.assertIn("- Model", p.jd_text)
        self.assertEqual(p.questions, [])


class GenericTests(unittest.TestCase):
    def test_html_to_text(self):
        t = html_to_text("<script>x()</script><h1>Role</h1><ul><li>SQL</li><li>Python</li></ul><p>A&amp;B</p>")
        self.assertNotIn("x()", t)
        self.assertIn("- SQL", t)
        self.assertIn("A&B", t)

    def test_generic_short_page_raises(self):
        with self.assertRaises(FetchError):
            parse_generic("<html><body><div id='root'></div></body></html>", "https://x.kr/1", "C", "R")

    def test_generic_ok(self):
        body = "<p>" + ("Responsibilities include analysis. " * 30) + "</p>"
        p = parse_generic(body, "https://x.kr/1", "C", "R")
        self.assertEqual(p.ats, "generic")


class ReviewFixFetchTests(unittest.TestCase):
    def test_from_text_cli_accepts_url_option(self):
        import subprocess, sys, tempfile
        script = Path(__file__).resolve().parent.parent / "fetch_posting.py"
        with tempfile.TemporaryDirectory() as tmp:
            jd = Path(tmp) / "jd.txt"
            jd.write_text("Job description text", encoding="utf-8")
            r = subprocess.run([sys.executable, str(script), "--from-text", str(jd), "--slug", "t", "--company", "C",
                                "--role", "R", "--url", "https://x.kr/1"], cwd=tmp, capture_output=True, text=True,
                               encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stderr)
            saved = json.loads((Path(tmp) / "applications" / "t" / "posting.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["url"], "https://x.kr/1")

    def test_network_error_becomes_fetch_error(self):
        import urllib.error
        from unittest import mock
        import fetch_posting
        with mock.patch.object(fetch_posting, "_get", side_effect=urllib.error.URLError("dns")):
            with self.assertRaises(FetchError):
                fetch_posting.fetch("https://jobs.lever.co/acme/123")

    def test_malformed_greenhouse_url_becomes_fetch_error(self):
        import fetch_posting
        with self.assertRaises(FetchError):
            fetch_posting.fetch("https://boards.greenhouse.io/acme/jobs")

    def test_generic_page_without_role_words_raises(self):
        body = "<p>" + ("Cookie settings and site navigation footer. " * 30) + "</p>"
        with self.assertRaises(FetchError):
            parse_generic(body, "https://x.kr/1", "Acme", "Data Analyst")


if __name__ == "__main__":
    unittest.main()
