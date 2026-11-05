from __future__ import annotations

import base64
import html
import json
import re
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from src.config import DATA_DIR
from src.browser.cdp_helper import cdp_evaluate, cdp_real_click, close_cdp_tab, list_cdp_pages
from src.utils.job_tracker import append_or_update_tracker_row, read_tracker_rows

SOCIAL_OR_FOOTER_DOMAINS = (
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "youtube.com",
    "tiktok.com",
    "equal-employment",
    "reasonable-accommodations",
    "doubleclick.net",
    "googleadservices.com",
    "e-verify.gov",
    "eeoc.gov",
    "dol.gov",
    "privacy-notice",
    "privacy-policy",
    "terms-of-use",
)


def extract_linkedin_external_apply_url(ws_url: str) -> Optional[str]:
    """
    Extracts the direct external ATS portal URL from LinkedIn's SDUI HTML (`safety/go/?url=...`)
    without relying on synthetic popup clicks that Chrome blocks.
    """
    raw_html = cdp_evaluate(ws_url, "document.documentElement.innerHTML") or ""
    safety_urls = re.findall(
        r"https://www\.linkedin\.com/safety/go/\?url=[^\"'\s<>]+", raw_html
    )
    candidates: List[str] = []
    for su in safety_urls:
        su_clean = html.unescape(su)
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(su_clean).query)
        if "url" in qs:
            u = qs["url"][0]
            if not any(sd in u.lower() for sd in SOCIAL_OR_FOOTER_DOMAINS):
                candidates.append(u)
    candidates.sort(key=len, reverse=True)
    return candidates[0] if candidates else None


def check_and_heal_workday_vps_error(ws_url: str) -> bool:
    """
    Detects Workday's 'Something went wrong / Error Code: VPS|...' resume parser crash
    after Step 1 (Autofill with Resume) and immediately reloads the page to land cleanly
    on Step 1/2 (My Information).
    Returns True if a VPS error was detected and healed.
    """
    body_text = cdp_evaluate(ws_url, "document.body ? document.body.innerText : ''") or ""
    if "Error Code: VPS|" in body_text or (
        "Something went wrong" in body_text and "Please refresh the page" in body_text
    ):
        cdp_evaluate(ws_url, "location.reload();")
        time.sleep(4.5)
        return True
    return False


def upload_pdf_via_cdp(ws_url: str, pdf_path: str, input_selector: str = "input[type=file]") -> str:
    """
    Uploads a 2-page PDF directly into `<input type='file'>` over CDP using `DataTransfer` + `File`
    constructed from base64 bytes. Works across Workday, SAP SuccessFactors, and SmartRecruiters.
    """
    p = Path(pdf_path).resolve()
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    filename = p.name
    js = f"""
    (() => {{
        const input = document.querySelector({json.dumps(input_selector)}) || document.querySelector("input[type=file]");
        if (!input) return "no_file_input";
        const bin = atob("{b64}");
        const arr = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
        const file = new File([arr], {json.dumps(filename)}, {{type: "application/pdf"}});
        const dt = new DataTransfer();
        dt.items.add(file);
        input.files = dt.files;
        input.dispatchEvent(new Event("input", {{bubbles: true}}));
        input.dispatchEvent(new Event("change", {{bubbles: true}}));
        return "uploaded:" + file.name;
    }})()
    """
    return str(cdp_evaluate(ws_url, js))


def normalize_workday_profile_and_titles(
    ws_url: str,
    master_profile: Optional[Dict[str, Any]] = None,
    tailored_resume: Optional[Dict[str, Any]] = None,
    target_role_1_title: Optional[str] = None,
    target_role_2_title: Optional[str] = None,
) -> Dict[str, Any]:
    """
    1. Fixes Workday OCR uppercase name alerts using the candidate's first/last name from `master_profile.json`.
    2. Synchronizes Workday Step 3 (My Experience) Role 1 (2024-Present) and Role 2 (03/2020-2024)
       job title inputs with target titles so Workday's saved profile titles always match the compatible senior leadership titles in the PDF.
    """
    if not master_profile and (DATA_DIR / "master_profile.json").exists():
        try:
            master_profile = json.loads((DATA_DIR / "master_profile.json").read_text(encoding="utf-8"))
        except Exception:
            master_profile = {}
    contact = (master_profile or {}).get("contact", {})
    first_name = contact.get("first_name", "")
    last_name = contact.get("last_name", "")

    role1_title = target_role_1_title or ""
    role2_title = target_role_2_title or ""
    if not role1_title and tailored_resume:
        exp = tailored_resume.get("tailored_experience", [])
        role1_title = exp[0].get("title", "") if len(exp) > 0 else ""
        role2_title = exp[1].get("title", "") if len(exp) > 1 else ""

    js = f"""
    (() => {{
        function setReactInput(el, val) {{
            if (!el || !val) return false;
            const proto = el instanceof HTMLTextAreaElement ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
            const desc = Object.getOwnPropertyDescriptor(proto, "value");
            const setter = desc ? desc.set : null;
            if (el._valueTracker) {{
                el._valueTracker.setValue("" + Math.random());
            }}
            el.focus();
            if (setter) {{
                setter.call(el, val);
            }} else {{
                el.value = val;
            }}
            el.dispatchEvent(new Event("input", {{bubbles: true}}));
            el.dispatchEvent(new Event("change", {{bubbles: true}}));
            el.dispatchEvent(new Event("blur", {{bubbles: true}}));
            return true;
        }}
        const actions = [];
        const targetFirst = {json.dumps(first_name)};
        const targetLast = {json.dumps(last_name)};
        // Fix First/Last Name casing if on My Information
        const fn = document.querySelector('input[data-automation-id*="legalNameSection_firstName"], input[id*="firstName"]');
        const ln = document.querySelector('input[data-automation-id*="legalNameSection_lastName"], input[id*="lastName"]');
        if (fn && targetFirst && (fn.value === fn.value.toUpperCase() || fn.value.toLowerCase() === targetFirst.toLowerCase())) {{
            setReactInput(fn, targetFirst);
            actions.push("fixed_firstName");
        }}
        if (ln && targetLast && (ln.value === ln.value.toUpperCase() || ln.value.toLowerCase() === targetLast.toLowerCase())) {{
            setReactInput(ln, targetLast);
            actions.push("fixed_lastName");
        }}

        // Synchronize Role 1 and Role 2 titles if on My Experience
        const titleInputs = Array.from(document.querySelectorAll('input[data-automation-id="jobTitle"], input[id*="jobTitle"]'));
        if (titleInputs.length >= 1 && {json.dumps(role1_title)}) {{
            setReactInput(titleInputs[0], {json.dumps(role1_title)});
            actions.push("synced_role1_title");
        }}
        if (titleInputs.length >= 2 && {json.dumps(role2_title)}) {{
            setReactInput(titleInputs[1], {json.dumps(role2_title)});
            actions.push("synced_role2_title");
        }}
        return {{updated: actions}};
    }})()
    """
    return cdp_evaluate(ws_url, js) or {}


def sync_submitted_applications_from_tabs_and_gmail() -> List[str]:
    """
    Checks open Chrome tabs and the Gmail inbox (`APPLICANT_EMAIL`) for application
    confirmation screens/emails and automatically marks matching rows in `Job_Search_Tracker.xlsx`
    as `Applied (YYYY-MM-DD)`.
    """
    pages = list_cdp_pages()
    gmail_tab = next((p for p in pages if "mail.google.com" in p.get("url", "")), None)
    inbox_text = ""
    if gmail_tab:
        try:
            inbox_text = (
                cdp_evaluate(
                    gmail_tab["webSocketDebuggerUrl"],
                    "document.body ? document.body.innerText.slice(0, 6000) : ''",
                    timeout=5,
                )
                or ""
            ).lower()
        except Exception:
            pass

    rows = read_tracker_rows()
    unapplied_companies = {
        r.get("Company", "").strip().lower().split()[0]
        for r in rows
        if not r.get("Application Status", "").lower().startswith("applied") and r.get("Company")
    }

    open_tab_texts = []
    ats_keywords = ("workday", "greenhouse", "lever.co", "icims", "brassring", "oraclecloud", "ashbyhq", "smartrecruiters", "hireez", "jobtasks", "application")
    for p in pages:
        u = p.get("url", "")
        if "mail.google.com" in u:
            continue
        u_lower = u.lower()
        is_relevant = any(k in u_lower for k in ats_keywords) or any(c in u_lower for c in unapplied_companies if len(c) > 3) or ("linkedin.com/jobs/view" in u_lower)
        if not is_relevant:
            continue
        try:
            t_text = (
                cdp_evaluate(
                    p["webSocketDebuggerUrl"],
                    "document.body ? document.body.innerText.slice(0, 2000) : ''",
                    timeout=3,
                )
                or ""
            ).lower()
            open_tab_texts.append((p.get("id", ""), u_lower, t_text))
        except Exception:
            continue
    updated_companies: List[str] = []
    today_str = datetime.now().strftime("%Y-%m-%d")

    for r in rows:
        status = r.get("Application Status", "")
        if status.lower().startswith("applied"):
            continue
        comp = r.get("Company", "").strip()
        title = r.get("Job Title", "").strip()
        if not comp:
            continue

        comp_lower = comp.lower()
        confirmed = False
        matched_tab_id = ""
        # Check if Gmail has a confirmation email from this company
        if comp_lower in inbox_text and any(
            kw in inbox_text
            for kw in ("thank you for applying", "application received", "thanks for applying", "submitted")
        ):
            confirmed = True

        # Check if an open tab shows a post-submit thank-you message
        for tab_id, tab_url, tab_body in open_tab_texts:
            if comp_lower.split()[0] in tab_url or comp_lower in tab_body:
                if any(
                    kw in tab_body
                    for kw in (
                        "thank you for applying",
                        "thanks for applying",
                        "application has been submitted",
                        "your application was submitted",
                        "you have successfully applied",
                        "successfully applied",
                        "application submitted",
                        "congratulations",
                    )
                ) or "jobtasks/completed/application" in tab_url:
                    confirmed = True
                    matched_tab_id = tab_id
                    break

        if confirmed:
            append_or_update_tracker_row(
                company=comp,
                job_title=title,
                location=r.get("Location / Work Type", ""),
                salary=r.get("Salary (listed)", "Not listed"),
                job_url=r.get("Job Link", ""),
                resume_status=r.get("Resume Status", "Approved & Uploaded (2-page PDF)"),
                resume_folder=r.get("Resume Folder", ""),
                application_status=f"Applied ({today_str})",
                notes=r.get("Notes", ""),
            )
            if matched_tab_id:
                close_cdp_tab(matched_tab_id)
            updated_companies.append(f"{comp} — {title}")

    # Also triage any new recruiter availability / interview emails in Gmail into "Jobs Awaiting response"
    try:
        triage_recruiter_availability_emails_cdp()
    except Exception:
        pass

    return updated_companies


def triage_recruiter_availability_emails_cdp(
    target_label: str = "Jobs Awaiting response",
) -> List[Dict[str, str]]:
    """
    Scans the active Gmail Inbox tab (`mail.google.com`) via CDP for emails where a recruiter
    or hiring team reached out for interview availability, phone screen scheduling, or next-step
    assessments, and moves them into the `Jobs Awaiting response` label.
    """
    pages = list_cdp_pages()
    gmail_tab = next((p for p in pages if "mail.google.com" in p.get("url", "")), None)
    if not gmail_tab:
        return []

    ws = gmail_tab["webSocketDebuggerUrl"]
    cdp_evaluate(ws, 'location.href = "https://mail.google.com/mail/u/0/#inbox";')
    time.sleep(3.5)

    selected = (
        cdp_evaluate(
            ws,
            """(() => {
        const tables = Array.from(document.querySelectorAll("table.F.cf.zt"));
        const activeTable = tables.find(t => t.getBoundingClientRect().width > 0) || tables[0];
        if (!activeTable) return [];
        const trs = Array.from(activeTable.querySelectorAll("tr.zA"));
        const matched = [];
        const ignoreSubjKeywords = [
            "application received",
            "thank you for applying",
            "thanks for applying",
            "we received your application",
            "your application was received",
            "verification code",
            "security code",
            "one-time access code",
            "multifactor authentication",
            "reset your password",
            "daily digest"
        ];
        const availabilityKeywords = [
            "availability",
            "available to chat",
            "available to speak",
            "schedule a call",
            "schedule a phone",
            "schedule a time",
            "phone screen",
            "virtual interview",
            "invite you to interview",
            "time to connect",
            "time to chat",
            "days and times",
            "let me know a few days",
            "reviewed your background",
            "complete next steps",
            "complete a pre-screen",
            "next step in our selection process",
            "calendly.com"
        ];
        for (const tr of trs) {
            const sender = ((tr.querySelector(".yX .yW") || {}).textContent || "").trim();
            const subj = ((tr.querySelector(".bog") || {}).textContent || "").trim();
            const snip = ((tr.querySelector(".y2") || {}).textContent || "").trim();
            const subjLow = subj.toLowerCase();
            const combinedLow = (subj + " " + snip).toLowerCase();
            if (ignoreSubjKeywords.some(k => subjLow.includes(k))) {
                continue;
            }
            if (availabilityKeywords.some(k => combinedLow.includes(k))) {
                const cb = tr.querySelector("div[role=checkbox]");
                if (cb && cb.getAttribute("aria-checked") !== "true") {
                    cb.click();
                }
                matched.push({sender, subject: subj});
            }
        }
        return matched;
    })()""",
        )
        or []
    )

    if not selected:
        return []

    time.sleep(1.0)
    move_btn = cdp_evaluate(
        ws,
        """(() => {
        const btns = Array.from(document.querySelectorAll('[aria-label="Move to"], [data-tooltip="Move to"]'));
        const b = btns.find(el => el.getBoundingClientRect().width > 0);
        if (!b) return null;
        const r = b.getBoundingClientRect();
        return {x: r.x + r.width / 2, y: r.y + r.height / 2};
    })()""",
    )
    if move_btn:
        cdp_real_click(ws, move_btn["x"], move_btn["y"])
        time.sleep(1.5)
        item = cdp_evaluate(
            ws,
            f"""(() => {{
            const items = Array.from(document.querySelectorAll('[role=menuitem], .J-N, .J-LC'));
            const target = items.find(el => el.textContent && el.textContent.toLowerCase().includes({json.dumps(target_label.lower())}) && el.getBoundingClientRect().width > 0);
            if (!target) return null;
            const r = target.getBoundingClientRect();
            return {{x: r.x + r.width / 2, y: r.y + r.height / 2}};
        }})()""",
        )
        if item:
            cdp_real_click(ws, item["x"], item["y"])
            time.sleep(2.0)

    return selected
