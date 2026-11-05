from __future__ import annotations

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from src.config import GEMINI_FLASH_MODEL, MIN_COMPENSATION_FLOOR_USD
from src.state import HarnessState, ParsedJobDescription
from src.utils.antigravity_client import generate_structured


async def fetch_job_page_text(url: str) -> str:
    """Uses headless Playwright to render dynamic Workday/SPA job postings and extract text."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            try:
                await page.wait_for_selector(
                    '[data-automation-id="jobPostingDescription"], main, article, #content',
                    timeout=8000,
                )
            except PlaywrightTimeoutError:
                await page.wait_for_timeout(3000)
            html = await page.content()
        finally:
            await browser.close()

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


async def jd_scout_node(state: HarnessState) -> dict:
    """
    Agent 1: Scrapes the job posting (or reads provided raw JD text) and uses Antigravity
    structured output to extract must-have skills, salary range, ATS type, and screening questions.
    Enforces:
      1. Excluded Companies Guard (from `master_profile.job_preferences.excluded_companies`)
      2. High-Impact & High-Paying Role Guard (minimum $190K+ ceiling, senior leadership scope)
    """
    raw_text = state.get("raw_jd_text", "")
    job_url = state.get("job_url", "")

    if not raw_text and job_url:
        raw_text = await fetch_job_page_text(job_url)

    prompt = f"""
You are an expert Executive Technical Recruiting Scout Agent.
Analyze the following job posting URL and page text, and extract the structured requirements, compensation range, and whether this is a high-impact senior leadership role (Sr. Manager, Director, Sr. Director, VP of Engineering / AI / Data / Platform).

Job URL: {job_url}

Job Posting Text:
{raw_text[:25000]}
"""
    parsed_jd = await generate_structured(
        prompt=prompt,
        schema=ParsedJobDescription,
        model_name=GEMINI_FLASH_MODEL,
        temperature=0.1,
    )

    excluded = (
        state.get("master_profile", {})
        .get("job_preferences", {})
        .get("excluded_companies", [])
    )
    company_lower = parsed_jd.company_name.lower()
    for exc in excluded:
        if exc.lower() in company_lower:
            raise ValueError(
                f"Company '{parsed_jd.company_name}' is on your Excluded Companies list ({exc}). Skipping."
            )

    if (
        parsed_jd.estimated_max_comp_usd is not None
        and parsed_jd.estimated_max_comp_usd < MIN_COMPENSATION_FLOOR_USD
    ):
        raise ValueError(
            f"Role '{parsed_jd.job_title}' at '{parsed_jd.company_name}' lists max compensation "
            f"${parsed_jd.estimated_max_comp_usd:,} ({parsed_jd.listed_salary_range}), which is below your "
            f"${MIN_COMPENSATION_FLOOR_USD:,} high-paying floor. Skipping."
        )

    if not parsed_jd.is_high_impact_leadership_role:
        raise ValueError(
            f"Role '{parsed_jd.job_title}' at '{parsed_jd.company_name}' does not match high-impact engineering/AI/data leadership criteria. Skipping."
        )

    return {
        "raw_jd_text": raw_text,
        "parsed_jd": parsed_jd,
        "revision_count": 0,
    }
