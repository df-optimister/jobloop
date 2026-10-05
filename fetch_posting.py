"""
공고 링크 → applications/<slug>/posting.json. LLM 없이 ATS 공개 API(또는 HTML)로 수집한다.

실행:
  python fetch_posting.py <url> --slug acme-ds-product [--company X --role Y]
  python fetch_posting.py --from-text applications/<slug>/jd.txt --slug <slug> --company X --role Y [--url U]

지원: Ashby(jobs.ashbyhq.com), Greenhouse(boards./job-boards.greenhouse.io), Lever(jobs.lever.co).
그 외 사이트는 HTML 텍스트를 시도하고, 본문이 짧으면(JS 렌더링 등) 수동 붙여넣기 경로를 안내하며 실패한다.
"""
import argparse
import html as htmllib
import json
import re
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from schemas import FormQuestion, Posting

APPS_DIR = Path("applications")
MIN_JD_CHARS = 500
UA = {"User-Agent": "Mozilla/5.0 (jobloop fetch_posting)"}


class FetchError(Exception):
    pass


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def html_to_text(html: str) -> str:
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", html)
    s = re.sub(r"(?i)<li[^>]*>", "\n- ", s)
    s = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|ul|ol|tr)>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = htmllib.unescape(s).replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n\n", s)
    return s.strip()


def _get(url: str, data: bytes | None = None, headers: dict | None = None) -> str:
    req = urllib.request.Request(url, data=data, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


# ---------- Ashby ----------
_ASHBY_FORM_QUERY = (
    "query ApiJobPosting($organizationHostedJobsPageName: String!, $jobPostingId: String!) { "
    "jobPosting(organizationHostedJobsPageName: $organizationHostedJobsPageName, jobPostingId: $jobPostingId) { "
    "id title applicationForm { sections { title fieldEntries { field isRequired descriptionHtml } } } } }"
)


def parse_ashby(job: dict, form: dict | None, org: str) -> Posting:
    locs = [job.get("location")] + [l.get("location") for l in job.get("secondaryLocations", [])]
    questions = []
    sections = (((form or {}).get("data") or {}).get("jobPosting") or {}).get("applicationForm", {}).get("sections", [])
    for sec in sections:
        for e in sec.get("fieldEntries", []):
            f = e["field"]
            questions.append(FormQuestion(
                id=f"q{len(questions) + 1}", title=f["title"], type=f.get("type", ""), required=e.get("isRequired", False),
                description=html_to_text(e["descriptionHtml"]) if e.get("descriptionHtml") else None,
                options=[v["label"] for v in f.get("selectableValues") or []],
            ))
    return Posting(url=job.get("jobUrl"), ats="ashby", company=org.replace("-", " ").title(), role=job["title"],
                   location=" / ".join(l for l in locs if l), jd_text=job["descriptionPlain"].strip(),
                   questions=questions, fetched_at=_now())


def _fetch_ashby(org: str, job_id: str) -> Posting:
    board = json.loads(_get(f"https://api.ashbyhq.com/posting-api/job-board/{org}?includeCompensation=true"))
    job = next((j for j in board["jobs"] if j["id"] == job_id), None)
    if job is None:
        raise FetchError(f"Ashby board '{org}' has no listed job {job_id} (closed or unlisted?)")
    body = json.dumps({"operationName": "ApiJobPosting", "query": _ASHBY_FORM_QUERY,
                       "variables": {"organizationHostedJobsPageName": org, "jobPostingId": job_id}}).encode()
    try:
        form = json.loads(_get("https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobPosting", data=body,
                               headers={"Content-Type": "application/json"}))
    except Exception as e:  # 폼은 부가정보 — 실패해도 JD는 저장하고 경고만
        print(f"[WARN] Ashby form fetch failed: {e}")
        form = None
    return parse_ashby(job, form, org)


# ---------- Greenhouse ----------
def parse_greenhouse(job: dict, org: str) -> Posting:
    content = html_to_text(htmllib.unescape(job.get("content", "")))
    questions = []
    for q in job.get("questions", []):
        fields = q.get("fields") or [{}]
        questions.append(FormQuestion(
            id=f"q{len(questions) + 1}", title=q["label"], type=fields[0].get("type", ""),
            required=bool(q.get("required")), description=q.get("description"),
            options=[v["label"] for v in fields[0].get("values") or []],
        ))
    return Posting(url=job.get("absolute_url"), ats="greenhouse", company=job.get("company_name") or org.title(),
                   role=job["title"], location=(job.get("location") or {}).get("name"), jd_text=content,
                   questions=questions, fetched_at=_now())


# ---------- Lever ----------
def parse_lever(job: dict, org: str) -> Posting:
    parts = [job.get("descriptionPlain", "")]
    for lst in job.get("lists", []):
        parts.append(lst.get("text", "") + "\n" + html_to_text(lst.get("content", "")))
    parts.append(job.get("additionalPlain", ""))
    return Posting(url=job.get("hostedUrl"), ats="lever", company=org.replace("-", " ").title(), role=job["text"],
                   location=(job.get("categories") or {}).get("location"),
                   jd_text="\n\n".join(p.strip() for p in parts if p and p.strip()), fetched_at=_now())


# ---------- generic / manual ----------
def _paste_hint(url: str, company: str | None, role: str | None) -> str:
    return ("Paste the JD into a text file and run:\n"
            f"  python fetch_posting.py --from-text <jd.txt> --slug <slug> --company \"{company or '<company>'}\" "
            f"--role \"{role or '<role>'}\" --url {url}")


def parse_generic(html: str, url: str, company: str, role: str) -> Posting:
    text = html_to_text(html)
    if len(text) < MIN_JD_CHARS:
        raise FetchError(f"Page text is only {len(text)} chars (likely JS-rendered). " + _paste_hint(url, company, role))
    # 본문이 길어도 메뉴·쿠키 안내·푸터뿐일 수 있다 — 직무명 단어의 절반 이상이 본문에 있어야 공고로 본다
    role_words = [w for w in re.findall(r"\w+", role.lower()) if len(w) >= 2]
    if role_words and sum(w in text.lower() for w in role_words) * 2 < len(role_words):
        raise FetchError(f"Page text does not mention the role '{role}' (menu/footer only?). " +
                         _paste_hint(url, company, role))
    return Posting(url=url, ats="generic", company=company, role=role, jd_text=text, fetched_at=_now())


def from_text(path: str, company: str, role: str, url: str | None = None) -> Posting:
    return Posting(url=url, ats="manual", company=company, role=role,
                   jd_text=Path(path).read_text(encoding="utf-8").strip(), fetched_at=_now())


def fetch(url: str, company: str | None = None, role: str | None = None) -> Posting:
    """네트워크·파싱 실패는 전부 FetchError(수동 붙여넣기 안내 포함)로 바꿔 올린다."""
    try:
        return _fetch(url, company, role)
    except FetchError:
        raise
    except Exception as e:
        raise FetchError(f"Could not fetch/parse {url}: {type(e).__name__}: {e}. " + _paste_hint(url, company, role))


def _fetch(url: str, company: str | None = None, role: str | None = None) -> Posting:
    u = urlparse(url)
    parts = [p for p in u.path.split("/") if p]
    if u.netloc == "jobs.ashbyhq.com" and len(parts) >= 2:
        p = _fetch_ashby(parts[0], parts[1])
    elif u.netloc in ("boards.greenhouse.io", "job-boards.greenhouse.io") and "jobs" in parts:
        org, job_id = parts[0], parts[parts.index("jobs") + 1]
        p = parse_greenhouse(json.loads(_get(
            f"https://boards-api.greenhouse.io/v1/boards/{org}/jobs/{job_id}?questions=true")), org)
    elif u.netloc == "jobs.lever.co" and len(parts) >= 2:
        p = parse_lever(json.loads(_get(f"https://api.lever.co/v0/postings/{parts[0]}/{parts[1]}")), parts[0])
    else:
        if not (company and role):
            raise FetchError("Unknown job site — pass --company and --role (or use --from-text).")
        p = parse_generic(_get(url), url, company, role)
    if company:
        p.company = company
    if role:
        p.role = role
    return p


def save(posting: Posting, slug: str) -> Path:
    d = APPS_DIR / slug
    d.mkdir(parents=True, exist_ok=True)
    out = d / "posting.json"
    out.write_text(posting.model_dump_json(indent=2), encoding="utf-8")
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--company")
    ap.add_argument("--role")
    ap.add_argument("--from-text")
    ap.add_argument("--url", dest="url_opt", help="--from-text일 때 원 공고 URL(기록용)")
    a = ap.parse_args()
    try:
        if a.from_text:
            if not (a.company and a.role):
                raise FetchError("--from-text needs --company and --role")
            p = from_text(a.from_text, a.company, a.role, a.url_opt or a.url)
        elif a.url:
            p = fetch(a.url, a.company, a.role)
        else:
            raise FetchError("Give a URL or --from-text")
    except FetchError as e:
        print(f"[FAIL] {e}")
        sys.exit(1)
    out = save(p, a.slug)
    print(f"saved: {out}  ({p.ats}, {len(p.jd_text)} chars, {len(p.questions)} form questions)")
    for q in p.questions:
        print(f"  {q.id} [{q.type}{', required' if q.required else ''}] {q.title}")


if __name__ == "__main__":
    main()
