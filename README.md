# Resume Builder & Workday Apply Agent Harness (Powered by Google Antigravity)

An end-to-end multi-agent harness powered by **Google Antigravity (`google-antigravity`)**, **LangGraph**, **Playwright**, **Chrome DevTools MCP**, and **Google Sheets / Drive** that:
1. **Syncs Your Common Questions Sheet** (`src/utils/common_questions_sync.py`) directly from your Google account (`COMMON_QUESTIONS_SHEET_ID`) via Antigravity's `gsheets` and `gdrive` plugins.
2. **Scouts & Parses** job descriptions and screening questions from target job portals (Workday, Greenhouse, Lever, etc.) via [`src/agents/jd_scout.py`](src/agents/jd_scout.py).
3. **Tailors Your Resume** using your structured [`data/master_profile.json`](data/master_profile.json) without hallucinating experience via [`src/agents/resume_tailor.py`](src/agents/resume_tailor.py).
4. **Evaluates via the "10-Second Senior Recruiter" Critic Agent** ([`src/agents/recruiter_critic.py`](src/agents/recruiter_critic.py)) — a ruthless recruiter persona that reviews 1,000+ resumes a day and issues a strict `GO` / `NO_GO` verdict with specific bullet rewrites before any application is submitted.
5. **Compiles an ATS-Clean PDF Resume + Audit Log** automatically via Playwright's Chromium PDF renderer ([`src/utils/pdf_compiler.py`](src/utils/pdf_compiler.py)) and logs every tailored resume to `output/applications_log.json`.
6. **Applies via Antigravity Browser Control with Seamless Headless -> Headed Fallback** ([`src/browser/session_manager.py`](src/browser/session_manager.py) & [`src/agents/workday_applicator.py`](src/agents/workday_applicator.py)):
   - **Attempt 1 (`headless=True`)**: Runs silently in the background using a persistent Chromium profile (`.browser_profile/`) and saved `storage_state.json`, automatically signing up or logging into the company's Workday portal, uploading the tailored PDF, and using Antigravity (`PageActionPlan`) to fill multi-step forms.
   - **Automatic Fallback (`headless=False`)**: If ANY issue occurs (CAPTCHA, 2FA, email verification link, validation error, or reaching the final Review gate when `PAUSE_BEFORE_FINAL_SUBMIT=true`), the headless browser saves its session state and immediately relaunches in **headed mode** (visible window on your Mac) at the exact step where it left off, firing a macOS desktop notification and waiting for you to review and click Submit.

---

## Project Structure

```text
resume builder and apply harness/
├── .agents/skills/
│   └── job-apply-harness/SKILL.md # Native Antigravity workspace skill for in-chat execution
├── .env.example                   # Configuration template (USE_ANTIGRAVITY=true by default)
├── requirements.txt               # Python dependencies (google-antigravity, langgraph, playwright)
├── data/
│   ├── master_profile.json        # Your complete career history, skills, EEO & Workday defaults
│   ├── common_questions.json      # Auto-synced Q&A cache from your Google Sheet
│   └── resume_template.html       # Clean, ATS-optimized HTML/CSS template compiled to PDF
├── output/                        # Generated tailored resumes (.json, .html, .pdf) & applications_log.json
└── src/
    ├── config.py                  # Central configuration and environment settings
    ├── state.py                   # LangGraph state & Pydantic schemas (RecruiterVerdict, TailoredResume, PageActionPlan)
    ├── graph.py                   # Main LangGraph workflow orchestrating all 4 agents & fallback routing
    ├── main.py                    # CLI entrypoint to run the harness on any job URL
    ├── agents/
    │   ├── jd_scout.py            # Agent 1: Extracts structured JD requirements & ATS portal type
    │   ├── resume_tailor.py       # Agent 2: Tailors resume bullets & ordering based on JD + Recruiter feedback
    │   ├── recruiter_critic.py    # Agent 3: "10-Second Senior Recruiter" GO/NO_GO critic loop
    │   └── workday_applicator.py  # Agent 4: Antigravity-controlled Playwright form loop & headless->headed fallback
    ├── browser/
    │   └── session_manager.py     # Persistent Chromium profile & Headless -> Headed session handoff
    └── utils/
        ├── antigravity_client.py  # Structured output client powered by Google Antigravity SDK
        ├── common_questions_sync.py # Syncs Common Questions Google Sheet via gsheets/gdrive CLI
        ├── pdf_compiler.py        # Renders tailored resume JSON + HTML template into an ATS-friendly PDF
        └── credential_store.py    # Local per-tenant Workday account vault
```

---

## Two Ways to Run

### Option A: Run Directly in Antigravity Chat (Zero Setup)
Simply paste any Workday, Greenhouse, or Lever job URL in chat and say:
> *"Run the harness on `<job_url>`"*

Antigravity will automatically use the workspace skill ([`.agents/skills/job-apply-harness/SKILL.md`](.agents/skills/job-apply-harness/SKILL.md)), sync your Google Sheet via `gsheets`/`gdrive`, run the 10-Second Senior Recruiter loop, compile your PDF, and drive the browser via Chrome DevTools MCP or Playwright.

### Option B: Run via the Python CLI (`google-antigravity` SDK)
```bash
git clone <your-repo-url>
cd Job-Application-workflow
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
cp data/master_profile.example.json data/master_profile.json

# Full pipeline: Sync Sheet -> Scout JD -> Tailor Resume <-> 10s Recruiter Loop -> Compile PDF -> Headless/Headed Apply
python -m src.main --url "https://company.wd5.myworkdayjobs.com/en-US/Careers/job/Software-Engineer_R12345"

# Or run only the Resume Tailor + 10-Second Senior Recruiter Loop + PDF Compiler:
python -m src.main --url "https://company.wd5.myworkdayjobs.com/..." --resume-only
```
