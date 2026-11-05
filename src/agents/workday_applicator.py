from __future__ import annotations

import asyncio
import json
from typing import Dict, Any, List
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError
from src.config import (
    GEMINI_PRO_MODEL,
    PAUSE_BEFORE_FINAL_SUBMIT,
)
from src.state import HarnessState, PageActionPlan, BrowserAction
from src.browser.session_manager import BrowserSessionManager, send_macos_notification
from src.utils.antigravity_client import generate_structured
from src.utils.credential_store import WorkdayCredentialStore
from src.utils.email_verifier import fetch_verification_from_gmail_browser
from src.utils.job_tracker import is_job_already_applied


class ApplicationBlockedError(Exception):
    """Raised when the headless browser hits a CAPTCHA, 2FA, email verification, or unresolvable form error."""


DOM_SNAPSHOT_SCRIPT = """
() => {
  const elements = [];
  const selectors = 'input, select, textarea, button, [role="button"], [role="combobox"], [role="checkbox"], [role="radio"], [data-automation-id]';
  const nodes = document.querySelectorAll(selectors);
  for (const el of nodes) {
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) continue;
    const style = window.getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none') continue;

    const autoId = el.getAttribute('data-automation-id');
    const id = el.id;
    const name = el.getAttribute('name');
    const role = el.getAttribute('role') || el.tagName.toLowerCase();
    const type = el.getAttribute('type') || '';
    const ariaLabel = el.getAttribute('aria-label') || '';
    const placeholder = el.getAttribute('placeholder') || '';
    let labelText = '';
    if (id) {
      const lbl = document.querySelector(`label[for="${CSS.escape(id)}"]`);
      if (lbl) labelText = lbl.innerText.trim();
    }
    if (!labelText && el.closest('label')) {
      labelText = el.closest('label').innerText.trim();
    }
    const text = (el.innerText || el.value || '').toString().trim().slice(0, 120);

    let selector = '';
    if (autoId) {
      selector = `[data-automation-id="${autoId}"]`;
    } else if (id) {
      selector = `#${CSS.escape(id)}`;
    } else if (name) {
      selector = `${el.tagName.toLowerCase()}[name="${name}"]`;
    } else if (ariaLabel) {
      selector = `${el.tagName.toLowerCase()}[aria-label="${ariaLabel.replace(/"/g, '\\"')}"]`;
    } else if (text && (el.tagName === 'BUTTON' || role === 'button')) {
      selector = `button:has-text("${text.slice(0, 40).replace(/"/g, '\\"')}")`;
    } else {
      continue;
    }

    elements.push({
      selector,
      tag: el.tagName.toLowerCase(),
      type,
      role,
      label: labelText || ariaLabel || placeholder,
      text,
      checked: !!el.checked,
      disabled: !!el.disabled
    });
  }
  return {
    url: window.location.href,
    title: document.title,
    pageTextExcerpt: document.body ? document.body.innerText.slice(0, 4000) : '',
    interactiveElements: elements.slice(0, 120)
  };
}
"""


async def deterministic_workday_auth_and_upload(
    page: Page,
    job_url: str,
    creds: Dict[str, str],
    pdf_path: str,
    cred_store: WorkdayCredentialStore,
    original_job_url: str,
    company_name: str = "Workday",
) -> str:
    """
    Executes fast, deterministic Playwright actions for standard Workday `data-automation-id`
    elements (Apply button, Create Account / Sign In, automatic Gmail verification link/OTP check,
    and Resume Autofill Upload) before handing off dynamic screening questions to Antigravity.
    """
    await page.goto(job_url, wait_until="domcontentloaded", timeout=45000)
    await page.wait_for_timeout(2500)

    # Check for CAPTCHA / Cloudflare block immediately
    page_content = (await page.content()).lower()
    if "verify you are human" in page_content or "cf-challenge" in page_content:
        raise ApplicationBlockedError("CAPTCHA / bot verification detected on initial load.")

    # Step 1: Click Apply Button if on JD landing page
    apply_btn = page.locator('[data-automation-id="adventureButton"], a:has-text("Apply")').first
    if await apply_btn.is_visible(timeout=5000):
        await apply_btn.click()
        await page.wait_for_timeout(1500)

    # Step 2: Select "Autofill with Resume" if modal appears
    autofill_btn = page.locator(
        '[data-automation-id="autofillWithResume"], button:has-text("Autofill with Resume")'
    ).first
    if await autofill_btn.is_visible(timeout=5000):
        await autofill_btn.click()
        await page.wait_for_timeout(2000)

    # Step 3: Handle Workday Sign In FIRST (`APPLICANT_EMAIL` / `WORKDAY_DEFAULT_PASSWORD`),
    # then fallback to Create Account ONLY if account does not exist yet
    email_input = page.locator('[data-automation-id="email"]').first
    if await email_input.is_visible(timeout=5000):
        signed_in = False

        # 3A: Always try Sign In first using `creds["email"]` and `creds["password"]`
        sign_in_btn = page.locator('[data-automation-id="signInSubmitButton"]').first
        if await sign_in_btn.is_visible(timeout=3000):
            await email_input.fill(creds["email"])
            await page.locator('[data-automation-id="password"]').fill(creds["password"])
            await sign_in_btn.click()
            await page.wait_for_timeout(3000)

            error_banner = page.locator('[data-automation-id="errorMessage"]').first
            if not await error_banner.is_visible(timeout=1500) and not await email_input.is_visible(timeout=1000):
                signed_in = True

        # 3B: ONLY if Sign In failed (account does not exist yet on this portal), create the account
        if not signed_in:
            create_acct_link = page.locator(
                '[data-automation-id="createAccountLink"], button:has-text("Create Account"), a:has-text("Create Account")'
            ).first
            if await create_acct_link.is_visible(timeout=3000):
                await create_acct_link.click()
                await page.wait_for_timeout(1200)

            await page.locator('[data-automation-id="email"]').fill(creds["email"])
            await page.locator('[data-automation-id="password"]').fill(creds["password"])
            verify_pw = page.locator('[data-automation-id="verifyPassword"]')
            if await verify_pw.is_visible(timeout=2000):
                await verify_pw.fill(creds["password"])

            checkbox = page.locator('[data-automation-id="createAccountCheckbox"]')
            if await checkbox.is_visible(timeout=2000):
                await checkbox.check()

            submit_acct = page.locator(
                '[data-automation-id="createAccountSubmitButton"]'
            ).first
            if await submit_acct.is_visible(timeout=3000):
                await submit_acct.click()
                await page.wait_for_timeout(3000)

            error_banner = page.locator('[data-automation-id="errorMessage"]').first
            if await error_banner.is_visible(timeout=1500):
                err_text = await error_banner.inner_text()
                raise ApplicationBlockedError(f"Workday authentication/signup error: {err_text}")

            # Check if Workday requires email verification link or OTP code for the newly created account
            body_lower = (await page.inner_text("body")).lower()
            if (
                "verify your email" in body_lower
                or "verification link" in body_lower
                or "verification code" in body_lower
            ):
                verification = await fetch_verification_from_gmail_browser(
                    context=page.context,
                    search_Hint=company_name,
                )
                if verification.get("verification_url"):
                    await page.reload(wait_until="domcontentloaded")
                    await page.wait_for_timeout(2000)
                    if await email_input.is_visible(timeout=3000):
                        await email_input.fill(creds["email"])
                        await page.locator('[data-automation-id="password"]').fill(
                            creds["password"]
                        )
                        if await sign_in_btn.is_visible(timeout=2000):
                            await sign_in_btn.click()
                            await page.wait_for_timeout(3000)
                elif not verification.get("otp_code"):
                    raise ApplicationBlockedError(
                        "Workday requested email verification, and no verification email arrived within timeout."
                    )

        # Record verified working account in vault
        cred_store.mark_account_created(
            original_job_url, creds["email"], creds["password"]
        )

        # Step 4: Upload tailored PDF on "Autofill with Resume" dropzone if present
    file_input = page.locator('input[type="file"]').first
    if await file_input.count() > 0:
        await file_input.set_input_files(pdf_path)
        await page.wait_for_timeout(4000)
        continue_btn = page.locator(
            '[data-automation-id="bottom-navigation-next-button"]'
        ).first
        if await continue_btn.is_visible(timeout=3000):
            await continue_btn.click()
            await page.wait_for_timeout(3000)

    # Step 5: Self-heal Workday VPS| resume parser 500 error if triggered after Autofill
    body_text = await page.inner_text("body")
    if "Error Code: VPS|" in body_text or (
        "Something went wrong" in body_text and "Please refresh the page" in body_text
    ):
        await page.reload(wait_until="domcontentloaded")
        await page.wait_for_timeout(4000)

    return page.url


async def execute_browser_actions(page: Page, actions: List[BrowserAction]) -> None:
    """Executes the structured Playwright actions planned by Antigravity."""
    for act in actions:
        if act.action_type == "wait":
            await page.wait_for_timeout(2000)
            continue

        loc = page.locator(act.selector).first
        if act.action_type == "fill" and act.value is not None:
            await loc.fill(act.value, timeout=5000)
        elif act.action_type == "click":
            await loc.click(timeout=5000)
        elif act.action_type == "select" and act.value is not None:
            try:
                await loc.select_option(label=act.value, timeout=4000)
            except Exception:
                await loc.click(timeout=4000)
                await page.wait_for_timeout(600)
                opt = page.locator(f'text="{act.value}"').first
                if await opt.is_visible(timeout=3000):
                    await opt.click()
        elif act.action_type == "check":
            await loc.check(timeout=4000)
        elif act.action_type == "upload" and act.value is not None:
            await loc.set_input_files(act.value, timeout=5000)

        await page.wait_for_timeout(600)


async def run_antigravity_form_loop(
    page: Page,
    master_profile: Dict[str, Any],
    creds: Dict[str, str],
    pdf_path: str,
    company_name: str = "Workday",
    tailored_resume: Dict[str, Any] | None = None,
    max_steps: int = 20,
) -> str:
    """
    Uses Antigravity (`generate_structured` -> `PageActionPlan`) to inspect the live Playwright
    DOM snapshot and fill out multi-step Workday / ATS application forms. Automatically reads
    Gmail (`APPLICANT_EMAIL`) if an email verification or OTP code prompt appears mid-application.
    """
    final_gate_rule = (
        "When you reach the final 'Review' page (or see the final 'Submit' button after all fields are filled), "
        "set `page_status` to 'ready_for_final_review' and DO NOT click Submit."
        if PAUSE_BEFORE_FINAL_SUBMIT
        else "When you reach the final 'Review' page, click the final 'Submit' button and set `page_status` to 'submitted'."
    )

    latest_otp_context = ""

    for _ in range(max_steps):
        # Self-heal Workday VPS| parser errors mid-flow
        body_text = await page.inner_text("body")
        if "Error Code: VPS|" in body_text or (
            "Something went wrong" in body_text and "Please refresh the page" in body_text
        ):
            await page.reload(wait_until="domcontentloaded")
            await page.wait_for_timeout(4000)

        snapshot = await page.evaluate(DOM_SNAPSHOT_SCRIPT)
        prompt = f"""
You are the Antigravity Browser Automation Agent controlling a live Playwright session on a job application portal.

CURRENT PAGE SNAPSHOT:
{json.dumps(snapshot, indent=2)}

CANDIDATE MASTER PROFILE & COMMON QUESTIONS (from Google Sheets):
{json.dumps(master_profile, indent=2)}

TAILORED RESUME EXPERIENCE TITLES (MUST SYNCHRONIZE ROLE 1 & ROLE 2 IN WORKDAY 'MY EXPERIENCE'):
{json.dumps((tailored_resume or {}).get('tailored_experience', [])[:2], indent=2)}

PORTAL CREDENTIALS & RESUME FILE:
- Email: {creds['email']}
- Password: {creds['password']}
- Tailored Resume PDF Path: {pdf_path}
{latest_otp_context}

INSTRUCTIONS:
1. Analyze the current page's text excerpt and interactive elements.
2. Always normalize Legal Name to Title Case matching `master_profile.contact` (never all-caps from OCR) and ensure Workday 'My Experience' Role 1 (2024–Present) and Role 2 (03/2020–2024) titles match the Tailored Resume Experience Titles above.
3. If there is an email verification or OTP security code prompt and no OTP code is provided above yet, set `page_status="blocked"` and set `blocker_reason="EMAIL_VERIFICATION_REQUIRED"`.
4. If there is a CAPTCHA or unresolvable validation error blocking progress, set `page_status="blocked"` and provide `blocker_reason`.
5. {final_gate_rule}
6. Otherwise, set `page_status="in_progress"` and output the exact ordered `actions` (`fill`, `click`, `select`, `check`, `upload`) needed to complete the current step and click 'Save and Continue' / 'Next' (`[data-automation-id="bottom-navigation-next-button"]`).
"""
        plan = await generate_structured(
            prompt=prompt,
            schema=PageActionPlan,
            model_name=GEMINI_PRO_MODEL,
            temperature=0.0,
        )

        if plan.page_status == "blocked":
            reason = plan.blocker_reason or "Blocked on application page."
            if "EMAIL_VERIFICATION" in reason.upper() and not latest_otp_context:
                verification = await fetch_verification_from_gmail_browser(
                    context=page.context,
                    search_Hint=company_name,
                )
                if verification.get("otp_code"):
                    latest_otp_context = f"- Latest Email Verification OTP Code from Gmail: {verification['otp_code']}"
                    continue
                if verification.get("verification_url"):
                    await page.reload(wait_until="domcontentloaded")
                    await page.wait_for_timeout(2000)
                    continue
            raise ApplicationBlockedError(reason)

        if plan.page_status in ("ready_for_final_review", "submitted"):
            if plan.actions and not PAUSE_BEFORE_FINAL_SUBMIT:
                await execute_browser_actions(page, plan.actions)
            return plan.page_status

        if not plan.actions:
            await page.wait_for_timeout(1500)
            continue

        await execute_browser_actions(page, plan.actions)
        await page.wait_for_timeout(2000)

    raise ApplicationBlockedError("Reached max form steps without completing application.")


async def run_workday_application_attempt(
    state: HarnessState, headless: bool
) -> Dict[str, Any]:
    """
    Runs the Workday application workflow via Antigravity + Playwright in either
    `headless=True` (Attempt 1) or `headless=False` (Fallback Attempt 2).
    """
    job_url = state.get("current_portal_url") or state["job_url"]
    pdf_path = state["compiled_pdf_path"]
    master_profile = state["master_profile"]
    company_name = (
        state["parsed_jd"].company_name if state.get("parsed_jd") else "Workday"
    )
    role_title = (
        state["parsed_jd"].role_title if state.get("parsed_jd") else ""
    )

    # Hard Guard: Never re-apply to a job already marked Applied / Ready to Submit in Job_Search_Tracker.xlsx
    if is_job_already_applied(company_name, role_title, job_url):
        return {
            "application_status": "skipped_already_applied",
            "browser_mode": "headless" if headless else "headed",
            "last_error_reason": f"Skipped: {company_name} — {role_title} is already marked Applied in Job_Search_Tracker.xlsx.",
        }

    cred_store = WorkdayCredentialStore()
    creds = cred_store.get_credentials(state["job_url"])

    session_mgr = BrowserSessionManager()
    try:
        context = await session_mgr.launch(headless=headless)
        page = context.pages[0] if context.pages else await context.new_page()

        await deterministic_workday_auth_and_upload(
            page=page,
            job_url=job_url,
            creds=creds,
            pdf_path=pdf_path,
            cred_store=cred_store,
            original_job_url=state["job_url"],
            company_name=company_name,
        )

        final_page_status = await run_antigravity_form_loop(
            page=page,
            master_profile=master_profile,
            creds=creds,
            pdf_path=pdf_path,
            company_name=company_name,
        )

        # If headless reached final review and PAUSE_BEFORE_FINAL_SUBMIT is True,
        # hand off to Headed Mode so the user can visually review and click Submit!
        if headless and PAUSE_BEFORE_FINAL_SUBMIT and final_page_status == "ready_for_final_review":
            current_url = page.url
            await session_mgr.save_and_close()
            return {
                "application_status": "failed_headless_needs_headed",
                "browser_mode": "headed",
                "last_error_reason": "Reached final Review gate — opening Headed window for manual review & Submit.",
                "current_portal_url": current_url,
            }

        if not headless and PAUSE_BEFORE_FINAL_SUBMIT:
            send_macos_notification(
                "Application Ready for Final Submit",
                "Please review the open Workday window and click Submit.",
            )
            await asyncio.to_thread(
                input,
                "\n[Headed Browser Open] Review the application and click Submit in the browser, then press Enter here to close...",
            )

        await session_mgr.save_and_close()
        return {
            "application_status": (
                "submitted_headless" if headless else "completed_headed"
            ),
            "browser_mode": "headless" if headless else "headed",
            "last_error_reason": None,
        }

    except (ApplicationBlockedError, PlaywrightTimeoutError, Exception) as exc:
        current_url = state.get("job_url")
        if session_mgr.context and session_mgr.context.pages:
            try:
                current_url = session_mgr.context.pages[0].url
            except Exception:
                pass

        if not headless:
            send_macos_notification(
                "Manual Action Required in Browser",
                f"Please complete the remaining step in the open window: {str(exc)[:80]}",
            )
            try:
                await asyncio.to_thread(
                    input,
                    f"\n[Headed Fallback Intervention] Blocker: {exc}\nComplete the step in the open browser window, then press Enter here to save & close...",
                )
                await session_mgr.save_and_close()
                return {
                    "application_status": "completed_headed",
                    "browser_mode": "headed",
                    "last_error_reason": None,
                }
            except Exception:
                pass

        await session_mgr.save_and_close()

        if headless:
            return {
                "application_status": "failed_headless_needs_headed",
                "browser_mode": "headed",
                "last_error_reason": str(exc),
                "current_portal_url": current_url,
            }
        return {
            "application_status": "error",
            "browser_mode": "headed",
            "last_error_reason": str(exc),
        }


async def workday_headless_node(state: HarnessState) -> dict:
    """Attempt 1: Run the Workday application flow in Headless mode via Antigravity."""
    return await run_workday_application_attempt(state, headless=True)


async def workday_headed_fallback_node(state: HarnessState) -> dict:
    """
    Attempt 2 (Fallback): Automatically triggered if Attempt 1 (`headless=True`) encounters
    any issue, CAPTCHA, timeout, blocker, or final review gate. Opens a visible browser window (`headless=False`)
    with the saved session cookies/progress so the workflow continues smoothly.
    """
    send_macos_notification(
        "Switching to Headed Browser Mode",
        f"{state.get('last_error_reason', 'Opening visible window')[:80]}",
    )
    return await run_workday_application_attempt(state, headless=False)
