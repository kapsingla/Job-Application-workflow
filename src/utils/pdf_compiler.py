from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Tuple, Optional
from src.config import DATA_DIR, OUTPUT_DIR, APPLICATIONS_LOG_PATH
from src.utils.job_tracker import get_next_job_folder, append_or_update_tracker_row


LATEX_SPECIAL_CHARS = {
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def latex_escape(text: Any) -> str:
    """Escapes special LaTeX characters in plain strings."""
    if text is None:
        return ""
    s = str(text)
    s = s.replace("\\", r"\textbackslash{}")
    for char, replacement in LATEX_SPECIAL_CHARS.items():
        s = s.replace(char, replacement)
    return s


def latex_rich(text: Any) -> str:
    """
    Converts HTML `<strong>...</strong>` or `<b>...</b>` tags and `**...**` markdown
    into LaTeX `\\textbf{...}` while escaping all other LaTeX special characters (`%`, `$`, `&`, etc.).
    """
    if text is None:
        return ""
    s = str(text)
    s = re.sub(r"\\textbf\{(.*?)\}", r"<strong>\1</strong>", s)
    s = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"<b>(.*?)</b>", r"<strong>\1</strong>", s, flags=re.IGNORECASE)

    parts = re.split(r"(<strong>.*?</strong>)", s, flags=re.IGNORECASE | re.DOTALL)
    out: list[str] = []
    for part in parts:
        m = re.match(r"^<strong>(.*?)</strong>$", part, flags=re.IGNORECASE | re.DOTALL)
        if m:
            out.append(f"\\textbf{{{latex_escape(m.group(1))}}}")
        else:
            out.append(latex_escape(part))
    return "".join(out)


def _to_dict(obj: Any) -> Dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return dict(obj)


def render_latex_resume(
    master_profile: Dict[str, Any],
    tailored_resume: Any,
) -> str:
    """Renders `data/resume_template.tex` (or pure-Python fallback if Jinja2 is not installed) into a complete `.tex` document."""
    tailored = _to_dict(tailored_resume)
    contact = master_profile["contact"]
    education = master_profile.get("education", [])
    certifications = master_profile.get("certifications", [])

    try:
        from jinja2 import Environment

        tex_template_path = DATA_DIR / "resume_template.tex"
        template_source = tex_template_path.read_text(encoding="utf-8")
        env = Environment(
            block_start_string=r"\BLOCK{",
            block_end_string="}",
            variable_start_string=r"\VAR{",
            variable_end_string="}",
            comment_start_string=r"\#{",
            comment_end_string="}",
            trim_blocks=True,
            autoescape=False,
        )
        env.filters["latex_escape"] = latex_escape
        env.filters["latex_rich"] = latex_rich
        template = env.from_string(template_source)
        return template.render(
            contact=contact,
            education=education,
            certifications=certifications,
            tailored=tailored,
        )
    except ImportError:
        pass

    # Pure-Python LaTeX generator (zero external dependencies)
    lines = [
        r"\documentclass[10pt,letterpaper]{article}",
        r"\usepackage[utf8]{inputenc}",
        r"\usepackage[T1]{fontenc}",
        r"\usepackage[top=0.42in, bottom=0.42in, left=0.48in, right=0.48in]{geometry}",
        r"\usepackage{enumitem}",
        r"\usepackage{titlesec}",
        r"\usepackage[hidelinks]{hyperref}",
        r"\usepackage{tabularx}",
        r"\usepackage{multicol}",
        r"\usepackage{xcolor}",
        r"\pagenumbering{gobble}",
        r"\setlength{\parindent}{0pt}",
        r"\definecolor{navy}{HTML}{1E3A5F}",
        r"\definecolor{darkgray}{HTML}{334155}",
        r"\titleformat{\section}{\large\bfseries\color{navy}}{}{0em}{}[\titlerule]",
        r"\titlespacing*{\section}{0pt}{7pt}{4pt}",
        r"\setlist[itemize]{leftmargin=1.2em, itemsep=1.5pt, topsep=2pt, parsep=0pt}",
        r"\begin{document}",
        r"\begin{center}",
        rf"  {{\LARGE \textbf{{\color{{navy}}{latex_escape(contact['full_name'])}}}}} \\[3pt]",
        rf"  {{\small {latex_escape(contact['phone'])} \ \textbar\ \href{{mailto:{latex_escape(contact['email'])}}}{{{latex_escape(contact['email'])}}} \ \textbar\ {latex_escape(contact['address']['city'])}, {latex_escape(contact['address']['state_code'])} \ \textbar\ \href{{{latex_escape(contact.get('linkedin_url', 'https://www.linkedin.com'))}}}{{{latex_escape(contact.get('linkedin', 'linkedin.com'))}}}}}",
        r"\end{center}",
        r"\vspace{-6pt}",
        r"\section{Professional Summary}",
        rf"{{\small {latex_rich(tailored.get('tailored_summary', ''))}}}",
    ]

    if tailored.get("core_competencies"):
        lines.extend([
            r"\section{Core Competencies}",
            r"\begin{multicols}{2}",
            r"\begin{itemize}[itemsep=1pt, topsep=0pt]",
        ])
        for comp in tailored["core_competencies"]:
            lines.append(rf"  \item {{\small {latex_escape(comp)}}}")
        lines.extend([r"\end{itemize}", r"\end{multicols}", r"\vspace{-4pt}"])

    lines.append(r"\section{Professional Experience}")
    for exp in tailored.get("tailored_experience", []):
        lines.append(
            rf"\textbf{{{latex_escape(exp['title'])}}} \hfill \textit{{\color{{darkgray}}{latex_escape(exp['start_date'])} -- {latex_escape(exp['end_date'])}}} \\"
        )
        lines.append(rf"\textit{{\color{{darkgray}}{latex_escape(exp['company'])}}} \\[2pt]")
        if exp.get("leadership_summary"):
            lines.append(rf"{{\small \hspace*{{1em}}{latex_rich(exp['leadership_summary'])}}} \\[2pt]")
        exp_bullets = exp.get("bullets") or exp.get("highlights")
        if exp_bullets:
            lines.append(r"{\small \hspace*{1em}\textbf{\textit{Key Initiatives \& Delivery:}}}")
            lines.append(r"\begin{itemize}")
            for b in exp_bullets:
                lines.append(rf"  \item {{\small {latex_rich(b)}}}")
            lines.append(r"\end{itemize}")
        lines.append(r"\vspace{4pt}")

    lines.append(r"\section{Education}")
    for edu in education:
        lines.append(
            rf"\textbf{{{latex_escape(edu['school'])}}} \hfill {{\color{{darkgray}}{latex_escape(edu['graduation_year'])}}} \\"
        )
        lines.append(
            rf"\textit{{{latex_escape(edu['degree'])} --- {latex_escape(edu['field_of_study'])}}}"
        )
        if edu.get("coursework"):
            lines.append(
                rf"\\ {{\footnotesize \color{{darkgray}}Key Coursework: {latex_escape(edu['coursework'])}}}"
            )
        lines.append(r"\\[3pt]")

    if certifications:
        lines.extend([
            r"\section{Certifications \& Professional Development}",
            r"\begin{itemize}[itemsep=1pt, topsep=1pt]",
        ])
        for cert in certifications:
            lines.append(rf"  \item {{\small {latex_escape(cert)}}}")
        lines.append(r"\end{itemize}")

    lines.extend([
        r"\section{Technical Proficiencies}",
        r"\begin{tabularx}{\textwidth}{@{} >{\bfseries\small}p{1.35in} >{\small}X @{}}",
    ])
    for cat in tailored.get("prioritized_skills", []):
        skills_str = ", ".join(cat.get("skills", []))
        lines.append(
            rf"{latex_escape(cat['category'])} & {latex_escape(skills_str)} \\[2pt]"
        )
    lines.extend([r"\end{tabularx}", r"\end{document}"])
    return "\n".join(lines)


def render_html_resume(
    master_profile: Dict[str, Any],
    tailored_resume: Any,
) -> str:
    """Renders `data/resume_template.html` (or pure-Python fallback) for PDF rendering."""
    tailored = _to_dict(tailored_resume)
    contact = master_profile["contact"]
    education = master_profile.get("education", [])
    certifications = master_profile.get("certifications", [])

    try:
        from jinja2 import Template

        html_template_path = DATA_DIR / "resume_template.html"
        html_template = Template(html_template_path.read_text(encoding="utf-8"))
        return html_template.render(
            contact=contact,
            education=education,
            certifications=certifications,
            tailored=tailored,
        )
    except ImportError:
        pass

    comp_items = "".join(
        f"<li>{c}</li>" for c in tailored.get("core_competencies", [])
    )
    exp_blocks = []
    for exp in tailored.get("tailored_experience", []):
        lead = (
            f'<p class="leadership-para">{exp["leadership_summary"]}</p>'
            if exp.get("leadership_summary")
            else ""
        )
        bullets_html = ""
        if exp.get("bullets"):
            b_items = "".join(f"<li>{b}</li>" for b in exp["bullets"])
            bullets_html = f'<div class="key-init-label">Key Initiatives &amp; Delivery:</div><ul>{b_items}</ul>'
        exp_blocks.append(
            f'<div class="role-block">'
            f'<div class="role-header"><span>{exp["title"]}</span><span class="role-date">{exp["start_date"]} – {exp["end_date"]}</span></div>'
            f'<div class="role-sub">{exp["company"]}</div>'
            f"{lead}{bullets_html}</div>"
        )
    edu_blocks = []
    for edu in education:
        cw = (
            f'<div class="edu-coursework">Key Coursework: {edu["coursework"]}</div>'
            if edu.get("coursework")
            else ""
        )
        edu_blocks.append(
            f'<div class="edu-block"><div class="edu-row"><span>{edu["school"]}</span>'
            f'<span style="font-weight:400;color:#475569;">{edu["graduation_year"]}</span></div>'
            f'<div class="edu-sub">{edu["degree"]} — {edu["field_of_study"]}</div>{cw}</div>'
        )
    cert_items = "".join(f"<li>{c}</li>" for c in certifications)
    skill_rows = "".join(
        f'<div class="skill-row"><div class="skill-category">{cat["category"]}</div>'
        f'<div class="skill-items">{", ".join(cat.get("skills", []))}</div></div>'
        for cat in tailored.get("prioritized_skills", [])
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>{contact["full_name"]} - Resume</title>
  <style>
    @page {{ size: letter; margin: 0.27in 0.40in; }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: Georgia, "Times New Roman", serif; font-size: 8.3pt; line-height: 1.18; color: #111827; }}
    header {{ text-align: center; padding-bottom: 2px; margin-bottom: 2px; }}
    h1 {{ font-size: 15.0pt; font-weight: 700; letter-spacing: 0.5px; color: #1e3a5f; }}
    .contact-bar {{ font-size: 8.2pt; color: #334155; margin-top: 1px; }}
    .contact-bar span + span::before {{ content: "  |  "; padding: 0 4px; color: #64748b; }}
    .contact-bar a {{ color: #334155; text-decoration: none; }}
    section {{ margin-bottom: 2.5px; }}
    h2 {{ font-size: 9.2pt; font-weight: 700; color: #1e3a5f; border-bottom: 1px solid #1e3a5f; padding-bottom: 1px; margin-bottom: 1.5px; }}
    .summary {{ font-size: 8.1pt; text-align: justify; }}
    .competencies-grid {{ display: grid; grid-template-columns: 1fr 1fr; column-gap: 14px; margin-left: 12px; font-size: 8.0pt; }}
    .role-block {{ margin-bottom: 2.5px; }}
    .role-header {{ display: flex; justify-content: space-between; align-items: baseline; font-weight: 700; font-size: 8.6pt; }}
    .role-date {{ font-weight: 400; font-style: italic; color: #475569; }}
    .role-sub {{ font-style: italic; font-size: 8.1pt; color: #475569; margin-bottom: 0.5px; }}
    .leadership-para {{ text-indent: 8px; text-align: justify; margin-bottom: 1px; font-size: 8.0pt; }}
    .key-init-label {{ font-weight: 700; font-style: italic; margin-left: 8px; margin-top: 0.5px; margin-bottom: 0.5px; font-size: 8.1pt; }}
    ul {{ margin-left: 14px; }}
    li {{ margin-bottom: 0.8px; text-align: justify; font-size: 8.0pt; }}
    .edu-block {{ margin-bottom: 1.5px; }}
    .edu-row {{ display: flex; justify-content: space-between; font-weight: 700; font-size: 8.4pt; }}
    .edu-sub {{ font-style: italic; font-size: 8.1pt; }}
    .edu-coursework {{ font-size: 7.6pt; color: #475569; }}
    .skills-grid {{ display: table; width: 100%; font-size: 8.0pt; }}
    .skill-row {{ display: table-row; }}
    .skill-category {{ display: table-cell; font-weight: 700; width: 25%; padding-bottom: 1px; vertical-align: top; }}
    .skill-items {{ display: table-cell; padding-bottom: 1px; }}
  </style>
</head>
<body>
  <header>
    <h1>{contact["full_name"]}</h1>
    <div class="contact-bar">
      <span>{contact["phone"]}</span>
      <span>{contact["email"]}</span>
      <span>{contact["address"]["city"]}, {contact["address"]["state_code"]}</span>
      <span>{contact.get("linkedin", "linkedin.com")}</span>
    </div>
  </header>
  <section><h2>Professional Summary</h2><p class="summary">{tailored.get("tailored_summary", "")}</p></section>
  <section><h2>Core Competencies</h2><ul class="competencies-grid">{comp_items}</ul></section>
  <section><h2>Professional Experience</h2>{"".join(exp_blocks)}</section>
  <section><h2>Education</h2>{"".join(edu_blocks)}</section>
  <section><h2>Certifications &amp; Professional Development</h2><ul>{cert_items}</ul></section>
  <section><h2>Technical Proficiencies</h2><div class="skills-grid">{skill_rows}</div></section>
</body>
</html>"""


def _find_latex_engine() -> Optional[Tuple[str, str]]:
    """Checks for an installed LaTeX compiler (`tectonic`, `pdflatex`, `xelatex`, `lualatex`)."""
    local_tectonic = Path.home() / ".gemini" / "antigravity" / "bin" / "tectonic"
    if local_tectonic.exists():
        return ("tectonic", str(local_tectonic))

    for engine in ("tectonic", "pdflatex", "xelatex", "lualatex"):
        found = shutil.which(engine)
        if found:
            return (engine, found)

    for mac_tex_dir in (Path("/Library/TeX/texbin"), Path("/opt/homebrew/bin")):
        for engine in ("tectonic", "pdflatex", "xelatex"):
            candidate = mac_tex_dir / engine
            if candidate.exists():
                return (engine, str(candidate))
    return None


def compile_tex_file_to_pdf(tex_path: Path, pdf_path: Path) -> bool:
    """
    Compiles `tex_path` into `pdf_path` using `tectonic` or `pdflatex`/`xelatex` if available.
    Returns True if native LaTeX compilation succeeded.
    """
    engine_info = _find_latex_engine()
    if not engine_info:
        return False

    engine_name, binary = engine_info
    out_dir = pdf_path.parent
    if engine_name == "tectonic":
        cmd = [binary, "-X", "compile", str(tex_path), "--outdir", str(out_dir)]
    else:
        cmd = [
            binary,
            "-interaction=nonstopmode",
            "-halt-on-error",
            f"-output-directory={out_dir}",
            str(tex_path),
        ]

    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return res.returncode == 0 and pdf_path.exists()


async def compile_tailored_resume_to_pdf(
    master_profile: Dict[str, Any],
    tailored_resume: Any,
    company_name: str,
    job_title: str,
    job_url: str = "",
    location: str = "United States (Remote)",
    raw_jd_text: str = "",
    recruiter_verdict: Optional[Any] = None,
) -> Tuple[str, str, str, str]:
    """
    1. Creates a numbered job folder (`output/Job Applications/NN_Company_Title/`) matching `Job_Search_Tracker.xlsx`.
    2. Generates the tailored resume in LaTeX format (`.tex`) from `data/resume_template.tex`.
    3. Compiles `.tex` into `.pdf` for upload (via `tectonic`/`pdflatex`, Playwright, or local macOS Chrome headless).
    4. Appends a row in `Job_Search_Tracker.xlsx` (`Job Tracker` sheet) and `output/applications_log.json`.
    Returns `(pdf_path, tex_path, html_path, json_path)`.
    """
    job_folder = get_next_job_folder(company_name, job_title)

    safe_company = re.sub(r"[^a-zA-Z0-9]+", "_", company_name).strip("_")
    safe_title = re.sub(r"[^a-zA-Z0-9]+", "_", job_title).strip("_")
    cand_name = master_profile.get("contact", {}).get("full_name", "Candidate")
    safe_cand = re.sub(r"[^a-zA-Z0-9]+", "_", cand_name).strip("_")
    base_filename = f"{safe_cand}_{safe_company}_{safe_title}"

    tex_path = job_folder / f"{base_filename}.tex"
    html_path = job_folder / f"{base_filename}.html"
    pdf_path = job_folder / f"{base_filename}.pdf"
    json_path = job_folder / f"{base_filename}.json"
    jd_txt_path = job_folder / "job_description.txt"

    if raw_jd_text:
        jd_txt_path.write_text(raw_jd_text, encoding="utf-8")

    # Step 1: Render and write the LaTeX (.tex) resume
    rendered_tex = render_latex_resume(master_profile, tailored_resume)
    tex_path.write_text(rendered_tex, encoding="utf-8")

    # Also render HTML and JSON for preview/archival
    rendered_html = render_html_resume(master_profile, tailored_resume)
    html_path.write_text(rendered_html, encoding="utf-8")

    verdict_dict = _to_dict(recruiter_verdict) if recruiter_verdict else None
    tailored_dict = _to_dict(tailored_resume)

    json_path.write_text(
        json.dumps(
            {
                "company_name": company_name,
                "job_title": job_title,
                "job_url": job_url,
                "tex_path": str(tex_path),
                "pdf_path": str(pdf_path),
                "recruiter_verdict": verdict_dict,
                "tailored_resume": tailored_dict,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # Step 2: Compile the LaTeX (.tex) resume to PDF (.pdf)
    compiled_ok = compile_tex_file_to_pdf(tex_path, pdf_path)

    if not compiled_ok:
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.set_content(rendered_html, wait_until="networkidle")
                await page.pdf(
                    path=str(pdf_path),
                    format="Letter",
                    print_background=True,
                    margin={
                        "top": "0.4in",
                        "bottom": "0.4in",
                        "left": "0.45in",
                        "right": "0.45in",
                    },
                )
                await browser.close()
            compiled_ok = pdf_path.exists()
        except Exception:
            pass

    if not compiled_ok:
        chrome_bin = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        if chrome_bin.exists():
            subprocess.run(
                [
                    str(chrome_bin),
                    "--headless",
                    "--disable-gpu",
                    "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf_path}",
                    f"file://{html_path}",
                ],
                capture_output=True,
                check=False,
            )

    # Step 3: Record in `Job_Search_Tracker.xlsx` (exact 16-column format)
    score_note = (
        f"10s Recruiter Verdict: {verdict_dict['verdict']} ({verdict_dict['score_out_of_100']}/100) — {verdict_dict['ten_second_gut_reaction']}"
        if verdict_dict
        else "Tailored via Antigravity Harness"
    )
    append_or_update_tracker_row(
        company=company_name,
        job_title=job_title,
        location=location,
        job_url=job_url,
        resume_status="Approved & Uploaded (2-page PDF)",
        resume_folder=f"Job Applications/{job_folder.name}",
        application_status="Pending review / Ready to submit",
        notes=score_note,
    )

    _append_application_log(
        company_name=company_name,
        job_title=job_title,
        job_url=job_url,
        verdict_dict=verdict_dict,
        tex_path=str(tex_path),
        pdf_path=str(pdf_path),
        json_path=str(json_path),
    )

    return str(pdf_path), str(tex_path), str(html_path), str(json_path)


def _append_application_log(
    company_name: str,
    job_title: str,
    job_url: str,
    verdict_dict: Optional[Dict[str, Any]],
    tex_path: str,
    pdf_path: str,
    json_path: str,
) -> None:
    entries = []
    if APPLICATIONS_LOG_PATH.exists():
        try:
            entries = json.loads(APPLICATIONS_LOG_PATH.read_text(encoding="utf-8"))
        except Exception:
            entries = []

    entries.append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "company_name": company_name,
            "job_title": job_title,
            "job_url": job_url,
            "recruiter_decision": (
                verdict_dict.get("verdict") if verdict_dict else None
            ),
            "recruiter_score": (
                verdict_dict.get("score_out_of_100") if verdict_dict else None
            ),
            "tex_path": tex_path,
            "pdf_path": pdf_path,
            "json_path": json_path,
        }
    )
    APPLICATIONS_LOG_PATH.write_text(json.dumps(entries, indent=2), encoding="utf-8")
