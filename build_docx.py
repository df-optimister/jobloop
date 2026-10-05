"""
CV 텍스트 초안(섹션: PROJECTS/EXPERIENCE/EDUCATION/SKILLS/ADDITIONAL, "Title | Mon YYYY - Mon YYYY" 헤더,
선택적 "Repository:"/"Blog:" 링크 줄, "- " 불릿)을 .docx로 변환한다.
날짜는 헤더 라인 오른쪽 정렬, Repository/Blog는 제목 아래 작은 글씨 하이퍼링크로 렌더링한다.

실행:
  python build_docx.py <draft.txt> <company> <role> [output_dir]
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.shared import Pt, Inches, RGBColor

SECTION_NAMES = {"PROJECTS", "EXPERIENCE", "EDUCATION", "SKILLS", "ADDITIONAL"}
LINK_RE = re.compile(r"^(Repository|Blog):\s*(\S+)\s*$")


def add_hyperlink(paragraph, url, text, size=8, color="0563C1", underline=True):
    """python-docx는 하이퍼링크를 기본 지원하지 않아 관계(relationship)를 직접 추가한다."""
    part = paragraph.part
    r_id = part.relate_to(
        url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)

    new_run = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")

    sz = OxmlElement("w:sz")
    sz.set(qn("w:val"), str(size * 2))
    rPr.append(sz)

    if color:
        c = OxmlElement("w:color")
        c.set(qn("w:val"), color)
        rPr.append(c)

    if underline:
        u = OxmlElement("w:u")
        u.set(qn("w:val"), "single")
        rPr.append(u)

    new_run.append(rPr)
    t = OxmlElement("w:t")
    t.text = text
    new_run.append(t)
    hyperlink.append(new_run)
    paragraph._p.append(hyperlink)
    return hyperlink


def add_right_tab(paragraph):
    """제목은 왼쪽, 날짜는 오른쪽 끝에 붙도록 탭 스톱을 페이지 우측 여백에 맞춘다."""
    section = paragraph.part.document.sections[0]
    usable_width = section.page_width - section.left_margin - section.right_margin
    paragraph.paragraph_format.tab_stops.add_tab_stop(usable_width, WD_TAB_ALIGNMENT.RIGHT)


def parse_sections(text: str) -> dict:
    lines = text.splitlines()
    header_positions = []
    for i, line in enumerate(lines):
        if line.strip() in SECTION_NAMES:
            header_positions.append((line.strip(), i))
    sections = {}
    for idx, (name, start) in enumerate(header_positions):
        end = header_positions[idx + 1][1] if idx + 1 < len(header_positions) else len(lines)
        sections[name] = lines[start + 1:end]
    header_lines = lines[:header_positions[0][1]] if header_positions else lines
    return header_lines, sections


def split_blocks(section_lines: list[str]) -> list[list[str]]:
    blocks, cur = [], []
    for line in section_lines:
        if line.strip() == "":
            if cur:
                blocks.append(cur)
                cur = []
        else:
            cur.append(line)
    if cur:
        blocks.append(cur)
    return blocks


def build(draft_path: str, company: str, role: str, out_dir: str, out_name: str | None = None):
    text = Path(draft_path).read_text(encoding="utf-8")
    header_lines, sections = parse_sections(text)

    doc = docx.Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10)
    for s in doc.sections:
        s.top_margin = s.bottom_margin = Inches(0.35)
        s.left_margin = s.right_margin = Inches(0.5)

    # ---- 헤더 (이름/헤드라인/위치/연락처) ----
    name_p = doc.add_paragraph()
    name_run = name_p.add_run(header_lines[0].strip())
    name_run.bold = True
    name_run.font.size = Pt(14)
    name_p.paragraph_format.space_after = Pt(1)

    for extra in header_lines[1:]:
        if not extra.strip():
            continue
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(1)
        parts = [seg.strip() for seg in extra.strip().split("|")]
        for i, seg in enumerate(parts):
            if i > 0:
                p.add_run(" | ").font.size = Pt(10)
            low = seg.lower()
            if low.startswith(("linkedin.com", "github.com")):
                add_hyperlink(p, "https://" + seg, seg, size=10, underline=False)
            else:
                p.add_run(seg).font.size = Pt(10)

    # ---- 섹션 ----
    for section_name in ["PROJECTS", "EXPERIENCE", "EDUCATION", "SKILLS", "ADDITIONAL"]:
        if section_name not in sections or not any(l.strip() for l in sections[section_name]):
            continue

        h = doc.add_paragraph()
        h.paragraph_format.space_before = Pt(6)
        h.paragraph_format.space_after = Pt(2)
        hr = h.add_run(section_name)
        hr.bold = True
        hr.font.size = Pt(11)
        hr.font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)
        pPr = h._p.get_or_add_pPr()
        bottom = OxmlElement("w:pBdr")
        b = OxmlElement("w:bottom")
        b.set(qn("w:val"), "single")
        b.set(qn("w:sz"), "6")
        b.set(qn("w:space"), "1")
        b.set(qn("w:color"), "1F3A5F")
        bottom.append(b)
        pPr.append(bottom)

        blocks = split_blocks(sections[section_name])

        if section_name in ("SKILLS", "ADDITIONAL"):
            for block in blocks:
                for line in block:
                    p = doc.add_paragraph(line.strip())
                    p.paragraph_format.space_after = Pt(1)
                    p.runs[0].font.size = Pt(9.5)
            continue

        if section_name == "EDUCATION":
            for block in blocks:
                header_line, *detail_lines = block
                header_line = header_line.strip()
                title, date = (header_line.split("|", 1) + [""])[:2] if "|" in header_line else (header_line, "")
                title, date = title.strip(), date.strip()
                p = doc.add_paragraph()
                p.paragraph_format.space_after = Pt(1)
                if date:
                    add_right_tab(p)
                    tr = p.add_run(title)
                    tr.bold = True
                    tr.font.size = Pt(10.5)
                    dr = p.add_run("\t" + date)
                    dr.font.size = Pt(10)
                    dr.italic = True
                else:
                    tr = p.add_run(title)
                    tr.bold = True
                    tr.font.size = Pt(10.5)

                for line in detail_lines:
                    line = line.strip()
                    if not line:
                        continue
                    detail_text = line[1:].strip() if line.startswith("-") else line
                    dp = doc.add_paragraph(style="List Bullet")
                    dp.paragraph_format.space_after = Pt(1)
                    dp.paragraph_format.line_spacing = 1.0
                    dr = dp.add_run(detail_text)
                    dr.font.size = Pt(9.5)
            continue

        for block in blocks:
            title_line = block[0]
            rest = block[1:]

            title, date = (title_line.split("|", 1) + [""])[:2] if "|" in title_line else (title_line, "")
            title, date = title.strip(), date.strip()

            title_p = doc.add_paragraph()
            title_p.paragraph_format.space_before = Pt(4)
            title_p.paragraph_format.space_after = Pt(0)
            if date:
                add_right_tab(title_p)
                tr = title_p.add_run(title)
                tr.bold = True
                tr.font.size = Pt(11)
                date_run = title_p.add_run("\t" + date)
                date_run.font.size = Pt(10)
                date_run.italic = True
            else:
                tr = title_p.add_run(title)
                tr.bold = True
                tr.font.size = Pt(11)

            link_line = None
            body = rest
            if rest and LINK_RE.match(rest[0].strip()):
                link_line = rest[0].strip()
                body = rest[1:]

            if link_line:
                label, url = LINK_RE.match(link_line).groups()
                link_p = doc.add_paragraph()
                link_p.paragraph_format.space_after = Pt(0)
                add_hyperlink(link_p, url, label, size=8)

            for line in body:
                line = line.strip()
                if not line:
                    continue
                bullet_text = line[1:].strip() if line.startswith("-") else line
                bp = doc.add_paragraph(style="List Bullet")
                bp.paragraph_format.space_after = Pt(0)
                bp.paragraph_format.line_spacing = 1.0
                br = bp.add_run(bullet_text)
                br.font.size = Pt(9.5)

    out_path = Path(out_dir) / f"{out_name or Path(draft_path).stem}.docx"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    return out_path


if __name__ == "__main__":
    draft_path, company, role = sys.argv[1], sys.argv[2], sys.argv[3]
    out_dir = sys.argv[4] if len(sys.argv) > 4 else "."
    out_name = sys.argv[5] if len(sys.argv) > 5 else None
    p = build(draft_path, company, role, out_dir, out_name)
    print(f"saved: {p}")

    # 1페이지 규칙: 초과하면 탈락(비정상 종료) — Word COM으로 실제 렌더링 페이지 수를 확인한다.
    try:
        from get_page_count import page_count
        n = page_count(str(p))
        if n > 1:
            print(f"[FAIL] cv_one_page: {n} pages — CV MUST fit on exactly 1 page. Cut content and rebuild.")
            sys.exit(1)
        print(f"[PASS] cv_one_page: {n} page")
    except ImportError:
        print("[SKIP] cv_one_page: pywin32/get_page_count.py not available — page count not verified.")
