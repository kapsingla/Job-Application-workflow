from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import quote_plus
from src.config import GEMINI_PRO_MODEL, MIN_COMPENSATION_FLOOR_USD

try:
    from pydantic import BaseModel, Field
except Exception:
    BaseModel = object  # type: ignore
    def Field(default=None, **kwargs):  # type: ignore
        return default

PORTAL_URLS = {
    "gmail": "https://mail.google.com/mail/u/0/#inbox",
    "linkedin": "https://www.linkedin.com/login",
    "indeed": "https://secure.indeed.com/auth",
    "dice": "https://www.dice.com/dashboard/login",
    "builtin": "https://builtin.com/jobs/remote/dev-engineering/lead-management",
}

# High-Impact & High-Paying Executive / Senior Leadership Search Queries ($200K–$350K+ target band)
DEFAULT_SEARCH_QUERIES = [
    '"Senior Director of Software Engineering" OR "Sr Director Software Engineering" OR "VP of Engineering"',
    '"Director of Software Engineering" OR "Director of Engineering" OR "Director, Engineering"',
    '"Director of AI" OR "Director, AI/ML Engineering" OR "Director of Platform Engineering"',
    '"Senior Director of Data Science" OR "Director of Data Engineering" OR "Director of Data Science"',
    '"Senior Manager, Software Engineering" OR "Sr Manager Software Engineering" OR "Senior Engineering Manager"',
]

EXCLUDED_COMPANIES: List[str] = []

EXCLUDED_AGENCY_AND_PORTAL_KEYWORDS = [
    # Third-party job portals & aggregators
    "hackajob",
    "jobgether",
    "lensa",
    "clearancejobs",
    "careerbuilder",
    "simplyhired",
    "talent.com",
    "adzuna",
    # Staffing, recruiting, headhunting & IT consulting agencies
    "axial search",
    "deca talent",
    "horizontal talent",
    "ttc group",
    "tech talent consulting",
    "twentyai",
    "veriipro",
    "vita global",
    "kelly services",
    "kelly company",
    "robert half",
    "randstad",
    "teksystems",
    "insight global",
    "kforce",
    "akkodis",
    "modis",
    "adecco",
    "manpower",
    "hays",
    "michael page",
    "pagegroup",
    "cybercoders",
    "motion recruitment",
    "jefferson frank",
    "nigel frank",
    "mason frank",
    "anderson frank",
    "frg technology",
    "harvey nash",
    "collabera",
    "apex systems",
    "judge group",
    "vaco",
    "eliassen",
    "beacon hill",
    "lucas group",
    "onward search",
    "mondo",
    "aerotek",
    "aston carter",
    "actalent",
    "dexian",
    "disys",
    "experis",
    "pyramid consulting",
    "kavaliro",
    "korn ferry",
    "russell reynolds",
    "spencer stuart",
    "heidrick",
    "harnham",
    "responses managed off linkedin",
    "staffing",
    "recruiting",
    "recruitment",
    "talent search",
    "executive search",
    "search partners",
    "talent partners",
]

EXCLUDED_PORTAL_DOMAINS = (
    "hackajob.com",
    "jobgether.com",
    "lensa.com",
    "cybercoders.com",
    "horizontaltalent.com",
    "vitaglobalsciences.com",
    "veriipro.com",
    "dice.com",
    "ziprecruiter.com",
    "monster.com",
    "careerbuilder.com",
    "simplyhired.com",
    "talent.com",
)

EXCLUDED_ROLE_TITLE_KEYWORDS = (
    # Security & DevSecOps (strictly excluded per user preference)
    "security",
    "cybersecurity",
    "cyber security",
    "devsecops",
    "secops",
    "infosec",
    "information security",
    "appsec",
    "application security",
    "cloud security",
    "network security",
    "product security",
    "ai security",
    "soc ",
    "soc,",
    "soc-",
    "/soc",
    "ciso",
    "iam ",
    "identity and access",
    "identity & access",
    "threat",
    "vulnerability",
    "penetration",
    "crisis simulation",
    # Non-engineering / Pre-sales / Marketing / Non-software engineering
    "sales",
    "pre-sales",
    "presales",
    "solutions engineering",
    "solution engineering",
    "channel director",
    "account executive",
    "marketing",
    "chemical engineering",
    "civil engineering",
    "mechanical engineering",
    "electrical engineering",
)


def is_excluded_role_title(title: str) -> bool:
    """
    Returns True if the job title relates to Security, Cybersecurity, DevSecOps, SOC,
    InfoSec, AppSec, IAM, or non-software/sales/marketing roles.
    Also merges `excluded_role_keywords` from `data/master_profile.json`.
    """
    import re
    from src.config import DATA_DIR

    t_low = f" {(title or '').strip().lower()} "
    keywords = set(EXCLUDED_ROLE_TITLE_KEYWORDS)
    profile_path = DATA_DIR / "master_profile.json"
    if profile_path.exists():
        try:
            prefs = json.loads(profile_path.read_text(encoding="utf-8")).get("job_preferences", {})
            for kw in prefs.get("excluded_role_keywords", []):
                if kw and kw.strip():
                    keywords.add(kw.strip().lower())
        except Exception:
            pass

    if any(kw in t_low for kw in keywords):
        return True
    if re.search(r"\b(soc|iam|ciso|appsec|infosec|secops|devsecops)\b", t_low, re.IGNORECASE):
        return True
    return False



def is_excluded_company_or_portal(company: str, job_url: str = "") -> bool:
    """
    Returns True if the company or URL belongs to an excluded employer (from `master_profile.json`),
    a staffing/recruiting/consulting agency, or a third-party job aggregator portal (e.g. hackajob).
    Dynamically merges `excluded_companies` and `excluded_portals` from `data/master_profile.json`.
    """
    from src.config import DATA_DIR

    comp_l = (company or "").strip().lower()
    url_l = (job_url or "").strip().lower()

    dynamic_companies = set(EXCLUDED_AGENCY_AND_PORTAL_KEYWORDS)
    dynamic_portals = set(EXCLUDED_PORTAL_DOMAINS)
    profile_path = DATA_DIR / "master_profile.json"
    if profile_path.exists():
        try:
            prefs = json.loads(profile_path.read_text(encoding="utf-8")).get("job_preferences", {})
            for c in prefs.get("excluded_companies", []):
                if c and c.strip():
                    dynamic_companies.add(c.strip().lower())
            for p in prefs.get("excluded_portals", []):
                if p and p.strip():
                    dynamic_portals.add(p.strip().lower())
        except Exception:
            pass

    if any(kw in comp_l for kw in dynamic_companies if len(kw) > 2):
        return True
    if any(re.search(rf"\b{re.escape(kw)}\b", comp_l) for kw in dynamic_companies if len(kw) <= 2):
        return True
    if any(dom in url_l for dom in dynamic_portals):
        return True
    return False


def add_to_avoid_companies_list(company: str | List[str] = "", portal_domain: str = "") -> None:
    """
    Persists a newly discovered staffing/consulting company (or list of companies) or third-party portal domain
    into `data/master_profile.json` (`job_preferences.excluded_companies` / `excluded_portals`)
    so future runs automatically skip it.
    """
    from src.config import DATA_DIR

    profile_path = DATA_DIR / "master_profile.json"
    if not profile_path.exists():
        return
    try:
        data = json.loads(profile_path.read_text(encoding="utf-8"))
        prefs = data.setdefault("job_preferences", {})
        exc_comps: List[str] = prefs.setdefault("excluded_companies", [])
        exc_ports: List[str] = prefs.setdefault("excluded_portals", [])
        comp_list = [company] if isinstance(company, str) else list(company or [])
        for comp_item in comp_list:
            if comp_item and comp_item.strip():
                c_clean = comp_item.strip()
                if not any(x.lower() == c_clean.lower() for x in exc_comps):
                    exc_comps.append(c_clean)
        if portal_domain and portal_domain.strip():
            p_clean = portal_domain.strip().lower()
            if not any(x.lower() == p_clean for x in exc_ports):
                exc_ports.append(p_clean)
        profile_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception:
        pass


class DiscoveredJobPosting(BaseModel):
    title: str = Field(description="Job title")
    company: str = Field(description="Hiring company name")
    location: str = Field(description="Location or Remote")
    listed_salary: Optional[str] = Field(
        default=None, description="Listed salary range on card if visible (e.g., '$220K - $300K/yr')"
    )
    estimated_max_comp_usd: Optional[int] = Field(
        default=None, description="Max listed salary in USD if visible on card, else None"
    )
    is_high_impact_leadership: bool = Field(
        default=True,
        description="True ONLY if this is a high-impact, high-paying Senior Manager, Director, Sr. Director, or VP role in Software/AI/Data/Platform Engineering (exclude pre-sales, commission, or low-level IC roles)",
    )
    job_url: str = Field(description="Direct URL to the job posting or external apply link")
    is_easy_apply: bool = Field(
        default=False, description="True if marked as LinkedIn/Indeed Easy Apply"
    )


class DiscoveredJobsList(BaseModel):
    jobs: List[DiscoveredJobPosting] = Field(
        default_factory=list,
        description="List of high-impact, high-paying leadership jobs discovered on the search results page",
    )


async def interactive_multi_portal_login(
    portals: Optional[List[str]] = None,
) -> None:
    """
    Opens a visible browser window using the persistent `.browser_profile` with tabs for
    Gmail (`APPLICANT_EMAIL`), LinkedIn, Indeed, and BuiltIn so the user
    can sign in once. All cookies and sessions are persisted in `.browser_profile`.
    """
    selected = portals or ["gmail", "linkedin", "indeed", "builtin"]
    session_mgr = BrowserSessionManager()
    context = await session_mgr.launch(headless=False)

    for idx, portal_key in enumerate(selected):
        url = PORTAL_URLS.get(portal_key.lower(), portal_key)
        page = (
            context.pages[0]
            if (idx == 0 and context.pages)
            else await context.new_page()
        )
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)

    send_macos_notification(
        "Sign Into Your Job Portals",
        "Log into LinkedIn, Gmail, Indeed, or BuiltIn in the open tabs. Sessions will be saved automatically.",
    )
    await asyncio.to_thread(
        input,
        "\n[Portal Login Setup] Sign into your accounts (LinkedIn, Gmail, Indeed, BuiltIn) across the open browser tabs.\n"
        "Once you are logged in, press Enter here to save all sessions to `.browser_profile`...",
    )
    await session_mgr.save_and_close()


async def search_linkedin_jobs(
    query: str,
    location: str = "United States",
    past_24h: bool = True,
    max_results: int = 5,
) -> List[DiscoveredJobPosting]:
    """
    Uses your signed-in LinkedIn session in `.browser_profile` to search strictly for
    HIGH-IMPACT & HIGH-PAYING ($190K–$350K+) executive and senior engineering leadership roles
    (Last 24 hours -> Past Week fallback, excluding companies in `master_profile.json`).
    """
    # f_TPR=r86400 is Past 24 Hours; f_TPR=r604800 is Past Week
    # f_SB2=7 filters LinkedIn for $160,000+ / $200,000+ high-salary bracket where supported
    tpr = "r86400" if past_24h else "r604800"
    search_url = (
        f"https://www.linkedin.com/jobs/search/?keywords={quote_plus(query)}"
        f"&location={quote_plus(location)}&f_TPR={tpr}"
    )

    session_mgr = BrowserSessionManager()
    context = await session_mgr.launch(headless=True)
    try:
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(3500)

        raw_cards = await page.evaluate(
            """
            () => {
              const cards = [];
              const links = document.querySelectorAll('a[href*="/jobs/view/"]');
              for (const a of links) {
                const card = a.closest('li, div.job-card-container') || a.parentElement;
                const text = card ? card.innerText.trim() : a.innerText.trim();
                cards.push({
                  href: a.href.split('?')[0],
                  text: text.slice(0, 450)
                });
              }
              return cards.slice(0, 25);
            }
            """
        )

        if not raw_cards and past_24h:
            await session_mgr.save_and_close()
            return await search_linkedin_jobs(
                query=query,
                location=location,
                past_24h=False,
                max_results=max_results,
            )

        prompt = f"""
You are filtering job postings for a Senior Engineering & AI/Data Executive (target compensation $200K–$350K+, minimum floor ${MIN_COMPENSATION_FLOOR_USD:,}).
Select up to {max_results} HIGH-IMPACT, HIGH-PAYING leadership roles from the raw cards below.

STRICT FILTERING RULES:
1. EXCLUDE any role at companies in the candidate's excluded companies list.
2. EXCLUDE any role whose listed salary ceiling is below ${MIN_COMPENSATION_FLOOR_USD:,}.
3. EXCLUDE pre-sales, solutions consulting, commission-based, or mid-level IC roles.
4. EXCLUDE any role related to Security, Cybersecurity, InfoSec, AppSec, Cloud Security, SOC, SecOps, DevSecOps, or IAM.
5. PRIORITIZE VP of Engineering, Senior Director / Director of Software Engineering, Director of AI/ML or Platform Engineering, Senior Director of Data Science, and high-paying Tier-1 Senior Engineering Manager roles in Healthcare SaaS, FinTech, Cloud/AI, or Enterprise Tech.

SEARCH QUERY: {query}
LOCATION: {location}
RAW CARDS:
{json.dumps(raw_cards, indent=2)}
"""
        parsed = await generate_structured(
            prompt=prompt,
            schema=DiscoveredJobsList,
            model_name=GEMINI_PRO_MODEL,
            temperature=0.1,
        )
        filtered = [
            j
            for j in parsed.jobs
            if j.is_high_impact_leadership
            and not is_excluded_company_or_portal(j.company, j.job_url)
            and not is_excluded_role_title(j.title)
            and (
                j.estimated_max_comp_usd is None
                or j.estimated_max_comp_usd >= MIN_COMPENSATION_FLOOR_USD
            )
        ]
        return filtered[:max_results]
    finally:
        await session_mgr.save_and_close()


def scan_linkedin_hourly_past24h_cdp(
    location: str = "",
    max_new_jobs: int = 6,
) -> List[dict]:
    """
    Hourly Past-24h (`f_TPR=r86400`) LinkedIn scanner using the active Chrome CDP session (`port 9222`).
    1. Syncs any recently submitted tabs/Gmail confirmations to `Job_Search_Tracker.xlsx`.
    2. Scans LinkedIn Jobs (`f_TPR=r86400`) for high-impact, high-paying ($190K+) leadership roles.
    3. Deduplicates against `Job_Search_Tracker.xlsx` (`is_job_already_tracked`) and excludes
       companies and portals configured in `data/master_profile.json`.
    4. Extracts the direct external ATS URL (`safety/go/?url=...`) for each new role and appends
       new discoveries to `Job_Search_Tracker.xlsx`.
    """
    import re
    import time
    from src.config import DATA_DIR
    from src.browser.cdp_helper import cdp_evaluate, list_cdp_pages, start_on_demand_chrome_cdp
    from src.browser.ats_adapters import (
        extract_linkedin_external_apply_url,
        sync_submitted_applications_from_tabs_and_gmail,
    )
    from src.utils.job_tracker import append_or_update_tracker_row, is_job_already_tracked

    if not location:
        profile_path = DATA_DIR / "master_profile.json"
        if profile_path.exists():
            try:
                prefs = json.loads(profile_path.read_text(encoding="utf-8")).get("job_preferences", {})
                locs = prefs.get("preferred_locations", [])
                if locs:
                    location = locs[0]
            except Exception:
                pass
        if not location:
            location = "United States"

    # Step 0: Ensure on-demand Chrome CDP is running in the background
    start_on_demand_chrome_cdp()
    time.sleep(2.0)

    # Step 1: Sync any newly submitted applications from Gmail / tabs
    sync_submitted_applications_from_tabs_and_gmail()

    pages = list_cdp_pages()
    li_tab = next((p for p in pages if "linkedin.com/jobs" in p.get("url", "")), None)
    if not li_tab:
        li_tab = next((p for p in pages if "linkedin.com" in p.get("url", "")), None)
    if not li_tab:
        try:
            import urllib.request
            req = urllib.request.Request("http://127.0.0.1:9222/json/new?https://www.linkedin.com/jobs", method="PUT")
            with urllib.request.urlopen(req, timeout=5) as resp:
                li_tab = json.loads(resp.read().decode())
                time.sleep(3.0)
        except Exception:
            return []

    tab_id = li_tab["id"]

    def get_li_ws() -> str:
        nonlocal tab_id
        for p in list_cdp_pages():
            if p.get("id") == tab_id:
                return p["webSocketDebuggerUrl"]
        for p in list_cdp_pages():
            if "linkedin.com" in p.get("url", ""):
                tab_id = p["id"]
                return p["webSocketDebuggerUrl"]
        return li_tab["webSocketDebuggerUrl"]

    search_queries = [
        ('(Director of Engineering OR VP of Engineering OR Director of AI) NOT "Security" NOT "DevSecOps" NOT "Cybersecurity"', "United States", "&geoId=103644278&f_WT=2&f_TPR=r86400&sortBy=DD"),
        ('(Senior Manager Software Engineering OR Director Data Science) NOT "Security" NOT "DevSecOps" NOT "Cybersecurity"', "United States", "&geoId=103644278&f_WT=2&f_TPR=r86400&sortBy=DD"),
        ('(Director Software Engineering OR Senior Manager Engineering OR Director AI) NOT "Security" NOT "DevSecOps" NOT "Cybersecurity"', location, "&geoId=103112676&f_TPR=r86400&sortBy=DD"),
        ('(Senior Director Software Engineering OR Director AI Engineering OR Head of AI) NOT "Security" NOT "DevSecOps" NOT "Cybersecurity"', "United States", "&geoId=103644278&f_WT=2&f_TPR=r86400&sortBy=DD"),
    ]

    # First try high-precision DOM card extraction across the Past-24h search queries
    # Supports both legacy `a[href*="/jobs/view/"]` and modern `/jobs/search-results/` `div[role="button"]` cards
    dom_js = r"""(() => {
        const results = [];
        const seenKeys = new Set();
        const links = Array.from(document.querySelectorAll('a')).filter(a => a.href && a.href.includes('/jobs/view/'));
        for (const a of links) {
            const cleanUrl = a.href.split('?')[0];
            if (seenKeys.has(cleanUrl)) continue;
            seenKeys.add(cleanUrl);
            
            let container = a;
            for (let i = 0; i < 5; i++) {
                if (container.parentElement) container = container.parentElement;
            }
            const textLines = (container ? (container.innerText || container.textContent || '') : (a.innerText || a.textContent || '')).split('\n').map(s => s.trim()).filter(Boolean);
            
            let title = (a.innerText || a.textContent || '').trim().split('\n')[0];
            if (title.endsWith(' with verification')) title = title.replace(' with verification', '').trim();
            
            let company = '';
            let loc = 'United States (Remote)';
            let salary = 'Not listed';
            
            for (let i = 0; i < textLines.length; i++) {
                const line = textLines[i];
                if (line.includes('$') && (line.includes('/yr') || line.includes('/hr'))) {
                    salary = line;
                }
                if (!company && i > 0 && !line.includes(title) && !line.includes('with verification') && line.length < 50) {
                    const lower = line.toLowerCase();
                    if (!lower.includes('ago') && !lower.includes('applicant') && !lower.includes('promoted') && 
                        !lower.includes('benefit') && !lower.includes('connection') && !lower.includes('alumni') &&
                        !lower.includes('review time') && !lower.includes('typically') && !lower.includes('actively')) {
                        company = line;
                        if (i + 1 < textLines.length) {
                            const nextLine = textLines[i+1];
                            const nextLower = nextLine.toLowerCase();
                            if (!nextLine.includes('$') && !nextLower.includes('ago') && !nextLower.includes('promoted') && 
                                !nextLower.includes('applicant') && !nextLower.includes('alumni') && !nextLower.includes('review time')) {
                                loc = nextLine;
                            }
                        }
                    }
                }
            }
            if (title && company) {
                results.push({
                    title: title,
                    company: company,
                    location: loc,
                    salary: salary,
                    job_url: cleanUrl
                });
            }
        }
        const roleBtns = Array.from(document.querySelectorAll('div[role="button"]'));
        for (const btn of roleBtns) {
            const rawText = (btn.textContent || '').replace(/\s+/g, ' ').trim();
            if (!rawText || rawText.length < 25 || rawText.length > 500 || !rawText.includes(' • ')) continue;
            if (rawText.includes('Applied')) continue;
            const parts = rawText.split(' • ');
            const leftPart = parts[0].trim();
            const rightPart = parts.slice(1).join(' • ').trim();
            const verIdx = leftPart.indexOf(' (Verified job)');
            if (verIdx === -1) continue;
            const title = leftPart.slice(0, verIdx).trim();
            const company = leftPart.slice(verIdx + 15).trim();
            const key = (company + '|' + title).toLowerCase();
            if (seenKeys.has(key)) continue;
            seenKeys.add(key);
            let salary = 'Not listed';
            const salMatch = rightPart.match(/\$[0-9.,]+K?(?:\/yr|\/hr)?(?:\s*-\s*\$[0-9.,]+K?(?:\/yr|\/hr)?)?/i);
            if (salMatch) salary = salMatch[0];
            results.push({
                title: title,
                company: company,
                location: rightPart.slice(0, 80),
                salary: salary,
                job_url: ''
            });
        }
        return results;
    })()"""
    raw_dom_items: List[dict] = []
    seen_job_urls = set()
    scroll_js = r"""(async () => {
        const pane = document.querySelector('.scaffold-layout__list > div') || document.querySelector('.jobs-search-results-list') || document.scrollingElement;
        for (let s = 0; s < 6; s++) {
            if (pane) pane.scrollTop += 600;
            window.scrollBy(0, 400);
            await new Promise(r => setTimeout(r, 200));
        }
    })()"""
    for q_text, q_loc, q_extra in search_queries:
        search_url = f"https://www.linkedin.com/jobs/search/?keywords={quote_plus(q_text)}&location={quote_plus(q_loc)}{q_extra}"
        try:
            cdp_evaluate(get_li_ws(), f"location.href = {json.dumps(search_url)};")
        except Exception:
            pass
        time.sleep(4.0)
        try:
            cdp_evaluate(get_li_ws(), scroll_js)
        except Exception:
            pass
        time.sleep(1.0)
        batch_items = cdp_evaluate(get_li_ws(), dom_js) or []
        for b_itm in batch_items:
            u = b_itm.get("job_url", "") or f"{b_itm.get('company', '')}|{b_itm.get('title', '')}".lower()
            if u and u not in seen_job_urls:
                seen_job_urls.add(u)
                raw_dom_items.append(b_itm)

        # In modern LinkedIn SDUI, also extract from body text per search query
        cur_body = cdp_evaluate(get_li_ws(), "document.body ? (document.body.innerText || document.body.textContent || '') : ''") or ""
        lines_b = [ln.strip() for ln in cur_body.split("\n") if ln.strip()]
        noise_re = re.compile(
            r"^(How promoted|Viewed|Posted |Be an early|Easy Apply|You’d be|You'd be|\d+ connection|\d+ company|\d+ school|Medical|Vision|Dental|401\(k\)|•|·|\$|Actively reviewing|\d+ result|\d+ benefit|Applied|Take the next step|Application status|\d+ notification)",
            re.IGNORECASE,
        )
        leadership_re = re.compile(
            r"\b(Director|Senior Director|Sr\.?\s*Director|Associate Director|Senior Manager|Sr\.?\s*Manager|VP|Vice President|Head of)\b",
            re.IGNORECASE,
        )
        bi = 0
        while bi < len(lines_b) - 2:
            b_line = lines_b[bi]
            if leadership_re.search(b_line) and not noise_re.search(b_line) and len(b_line) < 95 and "how ai search" not in b_line.lower():
                bc_idx = bi + 1
                while bc_idx < len(lines_b) and (leadership_re.search(lines_b[bc_idx]) or lines_b[bc_idx].lower() == b_line.lower()):
                    bc_idx += 1
                if bc_idx < len(lines_b):
                    b_comp = lines_b[bc_idx]
                    if not noise_re.search(b_comp) and len(b_comp) < 65 and "notification" not in b_comp.lower():
                        b_loc = q_loc if q_loc else location
                        b_sal = "Not listed"
                        b_next = bc_idx + 1
                        if b_next < len(lines_b) and any(w in lines_b[b_next] for w in ("United States", "Remote", "Area", "Hybrid")):
                            b_loc = lines_b[b_next]
                            b_next += 1
                        for bj in range(b_next, min(len(lines_b), b_next + 4)):
                            if "$" in lines_b[bj] and any(u in lines_b[bj] for u in ("/yr", "/hr", "K")):
                                b_sal = lines_b[bj]
                                break
                        raw_dom_items.append({
                            "title": b_line,
                            "company": b_comp,
                            "location": b_loc,
                            "salary": b_sal,
                            "job_url": "",
                        })
                        bi = b_next
                        continue
            bi += 1

    # Also scan LinkedIn's Recommended Jobs feed (/jobs/collections/recommended/)
    try:
        cdp_evaluate(get_li_ws(), 'location.href = "https://www.linkedin.com/jobs/collections/recommended/";')
        time.sleep(4.0)
        cdp_evaluate(get_li_ws(), scroll_js)
        time.sleep(1.0)
        rec_items = cdp_evaluate(get_li_ws(), dom_js) or []
        for r_itm in rec_items:
            u = r_itm.get("job_url", "")
            if u and u not in seen_job_urls:
                seen_job_urls.add(u)
                raw_dom_items.append(r_itm)
    except Exception:
        pass

    leadership_re = re.compile(
        r"\b(Director|Senior Director|Sr\.?\s*Director|Associate Director|Senior Manager|Sr\.?\s*Manager|VP|Vice President|Head of)\b",
        re.IGNORECASE,
    )

    raw_items: List[dict] = []
    seen_raw = set()
    for itm in raw_dom_items:
        t = itm.get("title", "").strip()
        c = itm.get("company", "").strip()
        key = (c.lower(), t.lower())
        if c and t and key not in seen_raw and leadership_re.search(t):
            seen_raw.add(key)
            raw_items.append(itm)

    new_discoveries: List[dict] = []
    for item in raw_items:
        comp = item.get("company", "").strip()
        title = item.get("title", "").strip()
        item_job_url = item.get("job_url", "")
        if not comp or not title:
            continue
        if is_excluded_role_title(title):
            continue
        if is_excluded_company_or_portal(comp, item_job_url):
            continue
        if is_job_already_tracked(comp, title, item_job_url):
            continue

        # Try clicking the job card on the active search page first to load right pane
        clicked = False
        if not item_job_url:
            click_js = f"""(() => {{
                const el = Array.from(document.querySelectorAll('p, div, span, h3')).find(e => e.innerText && e.innerText.trim().toLowerCase() === {json.dumps(comp.lower())});
                if (el) {{
                    el.click();
                    return true;
                }}
                return false;
            }})()"""
            try:
                clicked = bool(cdp_evaluate(get_li_ws(), click_js))
            except Exception:
                clicked = False
            if clicked:
                time.sleep(2.5)

        target_nav_url = item_job_url or f"https://www.linkedin.com/jobs/search/?keywords={quote_plus(comp + ' ' + title)}&location={quote_plus(location)}"
        if not clicked:
            try:
                cdp_evaluate(get_li_ws(), f"location.href = {json.dumps(target_nav_url)};")
            except Exception:
                pass
            time.sleep(3.5)

        # Resolve real company name and title from the active job detail page if generic
        page_info = cdp_evaluate(get_li_ws(), """(() => {
            const cEl = document.querySelector('.job-details-jobs-unified-top-card__company-name, .jobs-unified-top-card__company-name, .job-details-jobs-unified-top-card__primary-description-container a');
            const tEl = document.querySelector('.job-details-jobs-unified-top-card__job-title, h1');
            return {
                company: cEl ? cEl.innerText.trim() : '',
                title: tEl ? tEl.innerText.trim() : ''
            };
        })()""")
        if isinstance(page_info, dict):
            c_cand = page_info.get("company", "").strip()
            t_cand = page_info.get("title", "").strip()
            if c_cand and (comp.lower() in ("remote", "responses managed off linkedin", "hybrid", "full-time", "contract") or len(comp) < 2):
                comp = c_cand
            if t_cand and len(t_cand) > 3:
                title = t_cand

        ext_url = extract_linkedin_external_apply_url(get_li_ws()) or target_nav_url
        if is_excluded_company_or_portal(comp, ext_url) or is_excluded_role_title(title):
            continue
        from src.utils.job_tracker import is_job_already_applied
        if is_job_already_applied(comp, title, ext_url) or is_job_already_applied(comp, title, target_nav_url):
            continue
        if is_job_already_tracked(comp, title, ext_url) or is_job_already_tracked(comp, title, target_nav_url):
            continue

        append_or_update_tracker_row(
            company=comp,
            job_title=title,
            location=item.get("location", location),
            salary=item.get("salary", "Not listed"),
            job_url=ext_url,
            resume_status="Queued for Tailor & 10s Critic",
            resume_folder="Pending",
            application_status="DISCOVERED (Hourly Past-24h Scan)",
            notes="Auto-discovered by Hourly Past-24h Scanner",
        )
        new_discoveries.append(
            {
                "company": comp,
                "title": title,
                "location": item.get("location", location),
                "salary": item.get("salary", "Not listed"),
                "linkedin_url": target_nav_url,
                "portal_url": ext_url,
            }
        )
        if len(new_discoveries) >= max_new_jobs:
            break

    return new_discoveries

