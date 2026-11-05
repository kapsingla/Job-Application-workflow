from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional
from src.config import DATA_DIR, APPLICANT_EMAIL
from src.browser.cdp_helper import (
    cdp_command,
    cdp_evaluate,
    cdp_real_click,
    close_cdp_tab,
)
from src.browser.ats_adapters import upload_pdf_via_cdp


def _load_default_profile() -> Dict[str, Any]:
    profile_path = DATA_DIR / "master_profile.json"
    if profile_path.exists():
        try:
            return json.loads(profile_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _load_default_contact() -> Dict[str, Any]:
    return _load_default_profile().get("contact", {})


def click_and_type(ws: str, selector: str, text: str) -> bool:
    """Focuses, clears, and types text natively into a form field using CDP."""
    rect = cdp_evaluate(
        ws,
        f"""(() => {{
        const el = document.querySelector({json.dumps(selector)});
        if (!el) return null;
        el.scrollIntoView({{behavior: 'instant', block: 'center'}});
        const r = el.getBoundingClientRect();
        return {{x: r.x + r.width/2, y: r.y + r.height/2}};
    }})()""",
    )
    if not rect:
        return False
    time.sleep(0.1)
    cdp_real_click(ws, rect["x"], rect["y"])
    time.sleep(0.12)
    # Clear existing text
    cdp_evaluate(
        ws,
        f"""(() => {{
        const el = document.querySelector({json.dumps(selector)});
        if (el) {{
            el.focus();
            el.select();
            document.execCommand('delete');
        }}
    }})()""",
    )
    time.sleep(0.05)
    for ch in text:
        cdp_command(ws, "Input.dispatchKeyEvent", {"type": "keyDown", "text": ch})
        cdp_command(ws, "Input.dispatchKeyEvent", {"type": "keyUp"})
    time.sleep(0.08)
    return True


def select_react_select(ws: str, input_id: str, label_val: str) -> bool:
    """Sets a React Select dropdown value directly through its fiber onChange prop."""
    js = f"""(() => {{
        const el = document.querySelector('#' + {json.dumps(input_id)});
        if (!el) return false;
        const fKey = Object.keys(el).find(k => k.startsWith('__reactFiber'));
        let f = el[fKey];
        while (f) {{{{
            if (f.memoizedProps && f.memoizedProps.inputId === {json.dumps(input_id)} && f.memoizedProps.onChange) {{{{
                f.memoizedProps.onChange(
                    {{ value: {json.dumps(label_val)}, label: {json.dumps(label_val)} }},
                    {{ action: 'select-option', name: {json.dumps(input_id)} }}
                );
                return true;
            }}}}
            f = f.return;
        }}}}
        return false;
    }})()"""
    return bool(cdp_evaluate(ws, js))


def select_react_country(ws: str, country_code: str = "us", country_label: str = "United States +1") -> bool:
    """Sets the phone country dropdown to US."""
    js = f"""(() => {{
        const el = document.querySelector('#country');
        if (!el) return false;
        const fKey = Object.keys(el).find(k => k.startsWith('__reactFiber'));
        let f = el[fKey];
        while (f) {{{{
            if (f.memoizedProps && f.memoizedProps.inputId === 'country' && f.memoizedProps.onChange) {{{{
                f.memoizedProps.onChange(
                    {{ value: {json.dumps(country_code)}, label: {json.dumps(country_label)} }},
                    {{ action: 'select-option', name: 'country' }}
                );
                return true;
            }}}}
            f = f.return;
        }}}}
        return false;
    }})()"""
    return bool(cdp_evaluate(ws, js))


def fill_and_submit_greenhouse(
    ws_url: str,
    tab_id: str,
    candidate_info: Dict[str, Any],
    pdf_path: str,
    education_info: Optional[Dict[str, Any]] = None,
    custom_answers: Optional[Dict[str, Any]] = None,
    pause_before_submit: bool = False,
) -> Dict[str, Any]:
    """
    Fills all Greenhouse application form fields natively via CDP and automatically submits.
    """
    time.sleep(2.0)
    default_prof = _load_default_profile()
    default_edu_list = default_prof.get("education", [])
    default_edu = default_edu_list[0] if default_edu_list else {}
    edu = education_info or {
        "school": default_edu.get("school", ""),
        "degree": default_edu.get("degree", "Master of Business Administration (M.B.A.)"),
        "start_year": str(default_edu.get("start_year", "2011")),
        "end_year": str(default_edu.get("graduation_year", "2014")),
    }

    default_contact = default_prof.get("contact", {})
    default_phone = "".join(c for c in default_contact.get("phone", "") if c.isdigit())

    # 1. First Name, Last Name, Email, Phone
    click_and_type(ws_url, "#first_name", candidate_info.get("first_name") or default_contact.get("first_name", ""))
    click_and_type(ws_url, "#last_name", candidate_info.get("last_name") or default_contact.get("last_name", ""))
    click_and_type(ws_url, "#email", candidate_info.get("email") or default_contact.get("email") or APPLICANT_EMAIL)
    click_and_type(ws_url, "#phone", candidate_info.get("phone") or default_phone)

    # 2. Country (+1 US)
    select_react_country(ws_url, "us", "United States +1")

    # 3. Location / City if present
    addr = default_contact.get("address", {})
    default_city_state = f"{addr.get('city', '')}, {addr.get('state_code', '')}".strip(", ") or "United States"
    loc = candidate_info.get("city") or default_city_state
    click_and_type(ws_url, "#candidate-location", loc)

    # 4. Upload Tailored 2-Page Resume PDF
    upload_res = upload_pdf_via_cdp(ws_url, pdf_path, "#resume")
    time.sleep(1.0)

    # 5. Education
    select_react_select(ws_url, "school--0", edu["school"])
    select_react_select(ws_url, "degree--0", edu["degree"])
    click_and_type(ws_url, "#start-year--0", str(edu.get("start_year", "2011")))
    click_and_type(ws_url, "#end-year--0", str(edu.get("end_year", "2014")))

    # 6. LinkedIn & Website
    li_url = candidate_info.get("linkedin_url") or default_contact.get("linkedin_url", "")
    cdp_evaluate(
        ws_url,
        f"""(() => {{
        const liInputs = Array.from(document.querySelectorAll('input')).filter(i => {{
            const lbl = (i.labels && i.labels[0] ? i.labels[0].innerText : '') || (i.closest('div') ? i.closest('div').innerText : '');
            return lbl.toLowerCase().includes('linkedin');
        }});
        if (liInputs.length > 0) {{
            liInputs[0].value = {json.dumps(li_url)};
            liInputs[0].dispatchEvent(new Event('input', {{bubbles: true}}));
            liInputs[0].dispatchEvent(new Event('change', {{bubbles: true}}));
        }}
    }})()""",
    )

    # 7. Standard Disclosures & Dropdowns (Work auth, sponsorship, privacy policy, EEOC)
    cdp_evaluate(
        ws_url,
        """(() => {
        // Answer work auth & sponsorship & privacy policy
        const questions = Array.from(document.querySelectorAll('.field-wrapper, fieldset, div[class*="question"]'));
        for (const q of questions) {
            const text = q.innerText.toLowerCase();
            // Legally authorized -> Yes
            if (text.includes('legally authorized') || text.includes('authorized to work')) {
                const yesOpt = Array.from(q.querySelectorAll('input[type="radio"], input[type="checkbox"], option')).find(el => el.value === 'yes' || el.innerText && el.innerText.toLowerCase().includes('yes'));
                if (yesOpt) {
                    if (yesOpt.tagName === 'OPTION') yesOpt.selected = true;
                    else yesOpt.click();
                }
            }
            // Require sponsorship -> No
            if (text.includes('require sponsorship') || text.includes('sponsorship for employment')) {
                const noOpt = Array.from(q.querySelectorAll('input[type="radio"], input[type="checkbox"], option')).find(el => el.value === 'no' || el.innerText && el.innerText.toLowerCase().includes('no'));
                if (noOpt) {
                    if (noOpt.tagName === 'OPTION') noOpt.selected = true;
                    else noOpt.click();
                }
            }
            // Prior employee -> No
            if (text.includes('previously worked') || text.includes('existing employee')) {
                const noOpt = Array.from(q.querySelectorAll('input[type="radio"], input[type="checkbox"], option')).find(el => el.value === 'no' || el.innerText && el.innerText.toLowerCase().includes('no'));
                if (noOpt) {
                    if (noOpt.tagName === 'OPTION') noOpt.selected = true;
                    else noOpt.click();
                }
            }
            // Privacy policy -> Yes / Checkbox
            if (text.includes('privacy policy') || text.includes('agree to')) {
                const cb = q.querySelector('input[type="checkbox"]');
                if (cb && !cb.checked) cb.click();
                const yesOpt = Array.from(q.querySelectorAll('option, input[type="radio"]')).find(el => el.innerText && el.innerText.toLowerCase().includes('yes'));
                if (yesOpt) {
                    if (yesOpt.tagName === 'OPTION') yesOpt.selected = true;
                    else yesOpt.click();
                }
            }
        }
    })()""",
    )

    time.sleep(1.0)

    # 8. Check for any validation errors
    errors = (
        cdp_evaluate(
            ws_url,
            """(() => {
        return Array.from(document.querySelectorAll('[class*="error"]'))
            .map(e => e.innerText.trim())
            .filter(Boolean);
    })()""",
        )
        or []
    )

    if pause_before_submit:
        return {
            "success": True,
            "submitted": False,
            "status": "Paused at Final Review",
            "errors": errors,
            "upload_res": upload_res,
        }

    # 9. Click Final Submit button (PAUSE_BEFORE_FINAL_SUBMIT=false)
    submit_res = cdp_evaluate(
        ws_url,
        """(() => {
        const btn = document.querySelector('button[type="submit"], #submit_app');
        if (btn) {
            btn.click();
            return 'clicked_submit';
        }
        return 'no_submit_btn';
    })()""",
    )

    # Wait for submission and confirmation redirect
    time.sleep(4.0)

    # Verify confirmation
    body_text = (
        cdp_evaluate(ws_url, "document.body ? document.body.innerText.slice(0, 3000) : ''")
        or ""
    ).lower()
    cur_url = (cdp_evaluate(ws_url, "location.href") or "").lower()

    confirmed = any(
        kw in body_text or kw in cur_url
        for kw in (
            "thank you for applying",
            "thanks for applying",
            "application received",
            "application submitted",
            "confirmation",
            "successfully applied",
        )
    )

    result = {
        "success": True,
        "submitted": True,
        "confirmed": confirmed,
        "url_after_submit": cur_url,
        "upload_res": upload_res,
    }

    if confirmed and tab_id:
        try:
            close_cdp_tab(tab_id)
            result["tab_closed"] = True
        except Exception:
            result["tab_closed"] = False

    return result
