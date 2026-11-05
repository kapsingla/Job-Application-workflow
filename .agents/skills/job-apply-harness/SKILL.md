---
name: job-apply-harness
description: End-to-end Antigravity Resume Tailor, 10-Second Senior Recruiter Critic, LaTeX-to-PDF Compiler, Job Tracker Updater, and Browser Apply workflow. Use when the user shares a job URL or job description, wants to search for high-impact/high-paying engineering leadership roles, tailor their resume in LaTeX, run the 10-second recruiter GO/NO_GO loop, compile the PDF, update Job_Search_Tracker.xlsx, or apply on Workday/Greenhouse/Lever.
---

# Antigravity Job Apply & Resume Harness Skill

This skill executes the multi-agent resume tailoring and job application harness directly using Antigravity:
1. **High-Impact & High-Paying Role Filter & Strict Tracker Deduplication (`src/agents/jd_scout.py`, `src/agents/job_board_scout.py`, & `src/utils/job_tracker.py`)**:
   - Targets **VP of Engineering, Senior Director / Director of Software Engineering, Director of AI/ML or Platform Engineering, Senior Director of Data Science, and high-comp Senior Manager of Software Engineering** roles (`$200K–$350K+` target band, `$190K+` hard floor).
   - Automatically skips excluded companies configured in `data/master_profile.json` (`job_preferences.excluded_companies`), **consulting/staffing/recruiting agencies** (e.g., Axial Search, Deca Talent, Horizontal Talent, TTC Group, twentyAI, VeriiPro, Kelly/Vita Global, Robert Half, Randstad, TEKsystems, Insight Global, Kforce), **third-party job portals/aggregators** (e.g., `hackajob.com`, `jobgether.com`, `lensa.com`, `dice.com`, `ziprecruiter.com`, `monster.com` via `is_excluded_company_or_portal()`), **all Security / Cybersecurity / InfoSec / AppSec / Cloud Security / SOC / SecOps / DevSecOps / IAM roles** (`is_excluded_role_title()`), roles below `$190K`, and pre-sales/IC-only roles.
   - **Mandatory Duplicate Application Guard**: Always check `Job_Search_Tracker.xlsx` (`EXTERNAL_TRACKER_PATH` and `data/Job_Search_Tracker.xlsx`) via `is_job_already_tracked()` and `is_job_already_applied()` BEFORE tailoring or applying. Any job that was already applied to in a previous run must NEVER be applied to again.
2. **Agent 2 (Resume Tailor) <-> Agent 3 (10-Second Senior Recruiter Critic on Best Reasoning Model)**:
   - Always run `recruiter_critic` (`src/agents/recruiter_critic.py`) on the **highest-reasoning Pro model tier** (`Model="pro"`, `RECRUITER_THINKING_BUDGET=16384`).
   - Preserves all chronological roles from `data/master_profile.json`, with a `leadership_summary` paragraph + ***Key Initiatives & Delivery:*** bullets per role.
   - **Role Title Compatibility Rule (Mandatory)**: Always portray the last two roles (`Role 1` and `Role 2` in `data/master_profile.json`) with titles compatible with the seniority and domain of the target leadership role (e.g., for Director / Head of AI or Software Engineering roles: `Director, AI Engineering & Enterprise Platforms` and `Senior Manager, Software & Cloud Platform Engineering` — never use `Senior Manager` + `Manager (IC)` on Director+ applications).
3. **LaTeX `.tex` -> `.pdf` Compiler & Tracker Updater (`src/utils/pdf_compiler.py` & `src/utils/job_tracker.py`)**:
   - Renders `data/resume_template.tex` into `output/Job Applications/NN_<Company>_<Title>/<Candidate_Name>_<Company>_<Title>.tex` and compiles it to `.pdf`.
   - Updates `Job_Search_Tracker.xlsx` (`data/Job_Search_Tracker.xlsx` and `EXTERNAL_TRACKER_PATH`) using the exact 16-column `Job Tracker` schema.
4. **Agent 4 (Browser Applicator — Login First + Automatic Gmail Verification + Auto-Submit + Auto-Close Tab)**:
   - Uses the credentials from `.env` (`APPLICANT_EMAIL` / `WORKDAY_DEFAULT_PASSWORD`) and the exact contact info from `data/master_profile.json` (`contact.phone`, `contact.address`).
   - **Always tries Sign In first**; only clicks **Create Account** if the account does not exist yet on that company's portal, and automatically reads `APPLICANT_EMAIL` via `src/utils/email_verifier.py` if an email verification link or OTP code is requested.
   - **Do NOT pause before submit (`PAUSE_BEFORE_FINAL_SUBMIT=false`)**: Once the tailored 2-page PDF is uploaded and all required fields and disclosures are populated and verified, **immediately click the final Submit / Apply button**, verify the submission confirmation, update `Application Status = Applied (YYYY-MM-DD)` in `Job_Search_Tracker.xlsx`, and **immediately close the Chrome application tab via `close_cdp_tab(tab_id)`** (`http://127.0.0.1:9222/json/close/<tab_id>`).
