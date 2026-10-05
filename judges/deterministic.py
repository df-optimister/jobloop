"""
코드로 100% 판정 가능한 검사. LLM에 맡기면 비싸고 틀리는 것들.
각 함수는 (draft, job, profile_db) -> JudgeVerdict.
"""
import re

import config
from schemas import JudgeVerdict


def known_gaps(draft, job, profile_db) -> JudgeVerdict:
    """profile_db.known_gaps 의 금지 표현이 본문에 나오면 즉시 불합격(거부권).
    단어 경계 매칭 — 짧은 금지어(예: GAM)가 다른 단어(game) 안에서 오탐되는 것을 막는다."""
    text = draft["content"].lower()
    hits = [g for g in profile_db.get("known_gaps", [])
            if re.search(r"\b" + re.escape(g.lower()) + r"\b", text)]
    return JudgeVerdict(
        judge="known_gaps", score=0 if hits else 5, passed=not hits, evidence=hits,
        fix_instruction=f"Remove or rephrase these forbidden claims entirely: {hits}" if hits else None,
    )


def claims_integrity(draft, job, profile_db) -> JudgeVerdict:
    """모든 claim이 evidence_id를 갖고, 그 id가 profile_db(후보자 사실) 또는 company_brief(co_, 기업 사실)에
    실재하는지. 승인된 기획(doc_plan)이 이 문서에서 제외한 항목(avoid_evidence_ids)을 인용하면 불합격."""
    ids = {e["id"] for e in profile_db["entries"]} | {f["id"] for f in job.get("company_brief") or []}
    avoid = set((job.get("doc_plan") or {}).get("avoid_evidence_ids") or [])
    missing, unknown, avoided = [], [], []
    for c in draft["claims"]:
        if not c["evidence_ids"]:
            missing.append(c["text"][:80])
        unknown += [i for i in c["evidence_ids"] if i not in ids]
        avoided += [i for i in c["evidence_ids"] if i in avoid]
    ok = not missing and not unknown and not avoided
    fix = None
    if not ok:
        fix = (f"Sentences with no evidence: {missing}. " if missing else "") + \
              (f"Unknown evidence ids: {unknown}. Use only ids from profile_db or company_brief (co_*). "
               if unknown else "") + \
              (f"These entries are excluded from this document by the approved plan: {sorted(set(avoided))} — "
               f"remove the sentences that rely on them." if avoided else "")
    return JudgeVerdict(judge="claims_integrity", score=5 if ok else 0, passed=ok,
                        evidence=missing + unknown + avoided, fix_instruction=fix)


def char_limit(draft, job, profile_db) -> JudgeVerdict:
    """job.char_limit이 있으면 실제 글자수(공백 포함)로, 없으면 기존처럼 단어 수로 판정한다.
    글자수 기준일 때는 LLM이 자기 출력 글자수를 정확히 세지 못해 매 라운드 조금씩 초과하는 문제가
    있어, config.CHAR_LIMIT_TOLERANCE(기본 100자)까지 초과는 통과로 인정한다(제출 전 수동 트리밍 전제).
    word_limit(영문 문서)에는 이 허용치를 적용하지 않는다."""
    if job.get("char_limit"):
        limit, n, unit = job["char_limit"], len(draft["content"]), "characters"
        tolerance = config.CHAR_LIMIT_TOLERANCE
    else:
        limit = job.get("word_limit") or config.DEFAULT_CHAR_LIMIT.get(job["doc_type"])
        n, unit = len(draft["content"].split()), "words"
        tolerance = 0
    ok = limit is None or n <= limit + tolerance
    within_tolerance = limit is not None and n > limit and ok
    score = 5 if (limit is None or n <= limit) else (4 if within_tolerance else 1)
    evidence = [f"{n} {unit} / limit {limit}" + (f" (within +{tolerance} tolerance)" if within_tolerance else "")]
    return JudgeVerdict(judge="char_limit", score=score, passed=ok, evidence=evidence,
                        fix_instruction=None if ok else f"Cut to at most {limit + tolerance} {unit} (currently {n}).")


_STOP = set("and or the a an to of in for with on by at as is are be we you your our this that".split())


def _keywords(jd: str) -> set[str]:
    """JD에서 2회 이상 등장하는 명사성 토큰을 핵심 키워드로 본다(간단한 휴리스틱)."""
    toks = re.findall(r"[a-zA-Z][a-zA-Z+#\.\-]{2,}", jd.lower())
    freq = {}
    for t in toks:
        if t not in _STOP:
            freq[t] = freq.get(t, 0) + 1
    return {t for t, f in freq.items() if f >= 2}


def jd_keyword_coverage(draft, job, profile_db) -> JudgeVerdict:
    kws = _keywords(job["jd_text"])
    if not kws:
        return JudgeVerdict(judge="jd_keyword_coverage", score=5, passed=True, evidence=["no keywords"])
    text = draft["content"].lower()
    hit = {k for k in kws if k in text}
    cov = len(hit) / len(kws)
    ok = cov >= config.JD_KEYWORD_MIN_COVERAGE
    return JudgeVerdict(
        judge="jd_keyword_coverage", score=round(cov * 5), passed=ok,
        evidence=[f"coverage {cov:.0%}", f"missing: {sorted(kws - hit)[:10]}"],
        fix_instruction=None if ok else
        f"Coverage {cov:.0%} < {config.JD_KEYWORD_MIN_COVERAGE:.0%}. Work in these JD terms ONLY where "
        f"profile_db genuinely supports them: {sorted(kws - hit)[:10]}",
    )


_CV_SECTION_RE = re.compile(r"^(PROFILE|SUMMARY|PROJECTS|EXPERIENCE|EDUCATION|SKILLS|ADDITIONAL)\s*$", re.MULTILINE)
_DATE_RE = re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\.?\s+(\d{4})\b")
_MONTH_TOKEN = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\.?\s+\d{4}"
_HEADER_DATE_RE = re.compile(rf"^{_MONTH_TOKEN}\s*[–-]\s*(?:present|{_MONTH_TOKEN})$", re.IGNORECASE)
_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}


def _date_order_key(header_line: str):
    """헤더 줄의 날짜를 (종료 시점, 시작 시점) 정렬 키로 변환. present는 최신으로 취급."""
    dates = [(_MONTHS.get(mon[:3], 0), int(yr)) for mon, yr in _DATE_RE.findall(header_line)]
    if not dates:
        return None
    start = dates[0]
    end = (13, 9999) if "present" in header_line.lower() else dates[-1]
    return (end[1], end[0], start[1], start[0])


def _blocks(section_text: str, header_name: str) -> list[str]:
    """섹션 헤더 아래 내용을 빈 줄 기준으로 개별 항목(회사/프로젝트) 블록으로 쪼갠다."""
    body = section_text[len(header_name):].strip()
    return [b for b in re.split(r"\n\s*\n", body) if b.strip()]


def _norm_period(s: str) -> str:
    s = re.sub(r"\s*[–—-]\s*", " - ", s.strip())
    return re.sub(r"\s+", " ", s).lower()


def _block_cited_ids(lines: list[str], draft: dict) -> set[str]:
    """이 CV 블록(헤더+불릿) 안의 줄과 텍스트가 겹치는 claim들이 인용한 id. 다른 블록의 claim은 섞이지 않는다."""
    block = [n for n in (_norm_period(l.strip().lstrip("-•*").strip()) for l in lines) if len(n) >= 8]
    ids = set()
    for c in draft.get("claims", []):
        ct = _norm_period(c["text"].strip().lstrip("-•*").strip())
        if len(ct) >= 8 and any(ct in n or n in ct for n in block):
            ids |= set(c["evidence_ids"])
    return ids


def _dated_entry(entry_id: str, by_id: dict) -> dict | None:
    """기간이 있는 항목. 자식 항목은 같은 type의 부모 기간을 물려받는다(예: 모델링 하위 항목 → 상위 프로젝트).
    type이 다른 부모(예: 아르바이트 경험 → 그곳에서 진행한 프로젝트)의 기간은 물려받지 않는다."""
    e = by_id.get(entry_id)
    if not e:
        return None
    if e.get("period"):
        return e
    p = by_id.get(e.get("parent"))
    return p if p and p.get("period") and p.get("type") == e.get("type") else None


def _period_issue(lines: list[str], draft: dict, profile_db: dict) -> str | None:
    """CV 블록 헤더 날짜가 그 블록이 인용한 profile_db 항목의 period와 정확히 같은지.
    인용 항목에 기간이 없으면 날짜를 지어내지 말고 물어보라고 한다. 블록에 매칭되는 claim이 없을 때만 전체 period와
    대조하고, 그때도 제목이 확실히 닮은 항목(단어 2개 이상 겹침)이 있을 때만 정답 기간을 제시한다."""
    title, date_part = (x.strip() for x in lines[0].strip().rsplit("|", 1))
    by_id = {e["id"]: e for e in profile_db["entries"]}
    cited = {i for i in _block_cited_ids(lines, draft) if i in by_id}
    if cited:
        dated = {e["id"]: e for e in (_dated_entry(i, by_id) for i in cited) if e}
        if not dated:
            return (f'"{title[:70]}" cites {sorted(cited)}, which have no period in profile_db — do not invent a date; '
                    f"ask the user for it (or drop the dated header for this entry).")
        if any(_norm_period(e["period"]) == _norm_period(date_part) for e in dated.values()):
            return None
        periods = sorted({e["period"] for e in dated.values()})
        return (f'"{title[:70]}" date "{date_part}" does not match the period of the entry it cites — profile_db says '
                f"{' / '.join(repr(p) for p in periods)}. Use exactly that.")
    with_period = [e for e in profile_db["entries"] if e.get("period")]
    if any(_norm_period(e["period"]) == _norm_period(date_part) for e in with_period):
        return None
    words = {w for w in re.findall(r"\w+", title.lower()) if len(w) >= 3}
    overlap = lambda e: len(words & set(re.findall(r"\w+", e["text"].lower())))
    best = max(with_period, key=overlap, default=None)
    if best and overlap(best) >= 2:
        return (f'"{title[:70]}" date "{date_part}" does not match any profile_db period — profile_db says '
                f'"{best["period"]}" ({best["id"]}). Use the exact period.')
    return (f'"{title[:70]}" date "{date_part}" does not match any profile_db period — use the exact period of the '
            f"entry this block describes; if it has none, ask the user rather than invent one.")


def cv_structure(draft, job, profile_db) -> JudgeVerdict:
    """CV 전용 구조 검사: PROFILE/SUMMARY 섹션 금지, PROJECTS가 EXPERIENCE보다 먼저 나와야 하고,
    프로젝트당 불릿은 4개 이하, 모든 경력/프로젝트 항목에 월 단위 날짜가 있어야 한다.
    헤더 날짜는 profile_db period와 정확히 같아야 한다(2026-10-05)."""
    if job.get("doc_type") != "cv":
        return JudgeVerdict(judge="cv_structure", score=5, passed=True, evidence=["not a cv"])

    text = draft["content"]
    headers = [(m.group(1), m.start()) for m in _CV_SECTION_RE.finditer(text)]
    names = [h[0] for h in headers]
    issues = []

    if "PROFILE" in names or "SUMMARY" in names:
        issues.append("A PROFILE/SUMMARY section is present — CVs must not include one; delete it entirely.")

    if "PROJECTS" not in names:
        issues.append("No PROJECTS section header found — CVs must have a PROJECTS section.")
    elif "EXPERIENCE" in names and names.index("PROJECTS") > names.index("EXPERIENCE"):
        issues.append("EXPERIENCE appears before PROJECTS — PROJECTS must come first.")

    for section in ("PROJECTS", "EXPERIENCE", "EDUCATION"):
        if section not in names:
            continue
        idx = names.index(section)
        start = headers[idx][1]
        end = min([h[1] for h in headers if h[1] > start], default=len(text))
        order_keys = []
        for block in _blocks(text[start:end], section):
            lines = [l for l in block.splitlines() if l.strip()]
            if not lines:
                continue
            title = lines[0].strip()[:70]
            bullets = [l for l in lines if l.strip().startswith("-")]
            if section == "PROJECTS" and len(bullets) > 4:
                issues.append(f'Project "{title}" has {len(bullets)} bullets — max 4 allowed.')
            if not _DATE_RE.search(block):
                issues.append(f'"{title}" has no month+year date (e.g. "Mar 2025") in its header.')
            else:
                order_keys.append((title, _date_order_key(lines[0])))
            header_line = lines[0].strip()
            if "|" not in header_line:
                issues.append(
                    f'"{title}" header has no " | " before the date — the renderer needs the exact format '
                    f'"Title | Mon YYYY – Mon YYYY" (or "– present") to right-align the date. Add the pipe.'
                )
            else:
                date_part = header_line.rsplit("|", 1)[1].strip()
                if not _HEADER_DATE_RE.match(date_part):
                    issues.append(
                        f'"{title}" header text after " | " is "{date_part}", not exactly "Mon YYYY – Mon YYYY" '
                        f'or "Mon YYYY – present" — remove anything else (e.g. a parenthetical grade/honours '
                        f"note) from after the date; put it on its own line in the body instead."
                    )
                else:
                    issue = _period_issue(lines, draft, profile_db)
                    if issue:
                        issues.append(issue)

        for (t1, k1), (t2, k2) in zip(order_keys, order_keys[1:]):
            if k1 is not None and k2 is not None and k1 < k2:
                issues.append(
                    f'{section} is not reverse-chronological: "{t1}" comes before "{t2}" but is older — '
                    f"default order is most-recent-first (ongoing/\"present\" entries first)."
                )

    passed = not issues
    return JudgeVerdict(judge="cv_structure", score=5 if passed else 0, passed=passed, evidence=issues,
                        fix_instruction="; ".join(issues) if issues else None)


REGISTRY = {
    "known_gaps": known_gaps,
    "claims_integrity": claims_integrity,
    "char_limit": char_limit,
    "jd_keyword_coverage": jd_keyword_coverage,
    "cv_structure": cv_structure,
}
