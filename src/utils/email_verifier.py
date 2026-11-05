from __future__ import annotations

import asyncio
import email
import imaplib
import os
import re
from typing import Optional, Dict
from playwright.async_api import BrowserContext
from src.config import APPLICANT_EMAIL, WORKDAY_DEFAULT_PASSWORD
from src.browser.session_manager import BrowserSessionManager, send_macos_notification

GMAIL_INBOX_URL = "https://mail.google.com/mail/u/0/#inbox"
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")


async def interactive_gmail_login() -> None:
    """
    Opens a visible browser window using the persistent `.browser_profile` so the user
    can log into their `APPLICANT_EMAIL` Gmail account once. Cookies & session state are saved automatically
    so future headless/headed runs can read verification emails and OTP codes.
    """
    session_mgr = BrowserSessionManager()
    context = await session_mgr.launch(headless=False)
    page = context.pages[0] if context.pages else await context.new_page()

    await page.goto(GMAIL_INBOX_URL, wait_until="domcontentloaded", timeout=45000)
    await page.wait_for_timeout(2000)

    # Pre-fill email if on Google sign-in page
    email_input = page.locator('input[type="email"]').first
    if await email_input.is_visible(timeout=3000):
        await email_input.fill(APPLICANT_EMAIL)

    send_macos_notification(
        "Log into Job Application Gmail",
        f"Please sign into {APPLICANT_EMAIL} in the open browser window.",
    )
    await asyncio.to_thread(
        input,
        f"\n[Gmail Setup] Please finish logging into {APPLICANT_EMAIL} in the open browser window.\n"
        "Once your Gmail Inbox is visible, press Enter here to save the session...",
    )
    await session_mgr.save_and_close()


def _extract_links_and_otp(text_or_html: str) -> Dict[str, Optional[str]]:
    """Extracts Workday/ATS verification URLs and 6-digit OTP codes from email content."""
    # Look for Workday or ATS verification links
    url_patterns = [
        r'https?://[^\s"\'<>]+(?:myworkdayjobs\.com|myworkday\.com|wd\d\.myworkday)[^\s"\'<>]*',
        r'https?://[^\s"\'<>]+(?:verify|confirm|activate|token|registration)[^\s"\'<>]*',
    ]
    found_url: Optional[str] = None
    for pat in url_patterns:
        matches = re.findall(pat, text_or_html, flags=re.IGNORECASE)
        for m in matches:
            cleaned = m.rstrip(".,;)>'\"")
            if "unsubscribe" not in cleaned.lower() and "privacy" not in cleaned.lower():
                found_url = cleaned
                break
        if found_url:
            break

    # Look for 6-digit (or 4-8 digit) verification code
    otp_match = re.search(
        r"(?:code|passcode|pin|verification)\s*(?:is|:)?\s*([0-9]{4,8})\b",
        text_or_html,
        flags=re.IGNORECASE,
    )
    if not otp_match:
        otp_match = re.search(r"\b([0-9]{6})\b", text_or_html)
    found_otp = otp_match.group(1) if otp_match else None

    return {"verification_url": found_url, "otp_code": found_otp}


async def fetch_verification_from_gmail_browser(
    context: BrowserContext,
    search_Hint: str = "Workday",
    timeout_sec: int = 75,
) -> Dict[str, Optional[str]]:
    """
    Opens a second tab in the active Playwright BrowserContext at `mail.google.com`,
    waits for the latest verification email (from Workday or the target company),
    extracts the verification link or OTP code, and clicks the verification link if present.
    """
    mail_page = await context.new_page()
    try:
        await mail_page.goto(GMAIL_INBOX_URL, wait_until="domcontentloaded", timeout=45000)
        await mail_page.wait_for_timeout(3000)

        # Check if redirected to Google Sign-In
        if "accounts.google.com" in mail_page.url:
            # Try auto-filling credentials if possible
            email_input = mail_page.locator('input[type="email"]').first
            if await email_input.is_visible(timeout=2000):
                await email_input.fill(APPLICANT_EMAIL)
                await mail_page.keyboard.press("Enter")
                await mail_page.wait_for_timeout(2500)

        if "accounts.google.com" in mail_page.url:
            raise RuntimeError(
                f"Gmail ({APPLICANT_EMAIL}) is not signed in inside `.browser_profile`. "
                "Run `python -m src.main --login-email` or sign in inside the headed window."
            )

        loops = max(1, timeout_sec // 5)
        for _ in range(loops):
            # Look for unread or top email rows matching Workday / Verify / Code / Company
            rows = mail_page.locator("tr.zA")
            row_count = await rows.count()
            for idx in range(min(row_count, 8)):
                row = rows.nth(idx)
                row_text = (await row.inner_text()).lower()
                if any(
                    kw in row_text
                    for kw in [
                        "workday",
                        "verify",
                        "verification",
                        "confirm",
                        "code",
                        "account",
                        search_Hint.lower(),
                    ]
                ):
                    await row.click()
                    await mail_page.wait_for_timeout(2000)
                    body_html = await mail_page.content()
                    body_text = await mail_page.inner_text("body")
                    extracted = _extract_links_and_otp(body_html + "\n" + body_text)
                    if extracted["verification_url"] or extracted["otp_code"]:
                        # If there's a verification URL, visit it right inside the mail_page to activate the account!
                        if extracted["verification_url"]:
                            await mail_page.goto(
                                extracted["verification_url"],
                                wait_until="domcontentloaded",
                                timeout=30000,
                            )
                            await mail_page.wait_for_timeout(3000)
                        return extracted

            await mail_page.wait_for_timeout(5000)
            await mail_page.reload(wait_until="domcontentloaded")
            await mail_page.wait_for_timeout(2000)

        return {"verification_url": None, "otp_code": None}
    finally:
        try:
            await mail_page.close()
        except Exception:
            pass
