from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except ImportError:
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
BROWSER_PROFILE_DIR = BASE_DIR / ".browser_profile"
STORAGE_STATE_PATH = BROWSER_PROFILE_DIR / "storage_state.json"
CREDENTIALS_VAULT_PATH = DATA_DIR / "workday_accounts_vault.json"
APPLICATIONS_LOG_PATH = OUTPUT_DIR / "applications_log.json"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

# Antigravity Runtime Mode (True by default — no GEMINI_API_KEY needed)
USE_ANTIGRAVITY = os.getenv("USE_ANTIGRAVITY", "true").lower() == "true"

# Google Sheets Common Questions Link / ID
COMMON_QUESTIONS_SHEET_ID = os.getenv(
    "COMMON_QUESTIONS_SHEET_ID",
    "",
)

# Optional fallback Gemini API Key (only used if Antigravity SDK is bypassed)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_PRO_MODEL = os.getenv("GEMINI_PRO_MODEL", "gemini-2.5-pro")
GEMINI_FLASH_MODEL = os.getenv("GEMINI_FLASH_MODEL", "gemini-2.5-flash")
# Dedicated highest-reasoning model tier for the 10-Second Senior Recruiter Critic
RECRUITER_CRITIC_MODEL = os.getenv("RECRUITER_CRITIC_MODEL", "gemini-2.5-pro")
RECRUITER_THINKING_BUDGET = int(os.getenv("RECRUITER_THINKING_BUDGET", "16384"))

# Workday / Career Portal Credentials (configured via .env)
APPLICANT_EMAIL = os.getenv("APPLICANT_EMAIL", "")
WORKDAY_DEFAULT_PASSWORD = os.getenv("WORKDAY_DEFAULT_PASSWORD", "")

# Minimum compensation floor for High-Impact / High-Paying filter ($190K+ base floor)
MIN_COMPENSATION_FLOOR_USD = int(os.getenv("MIN_COMPENSATION_FLOOR_USD", "190000"))

MAX_RECRUITER_REVISIONS = int(os.getenv("MAX_RECRUITER_REVISIONS", "3"))
INITIAL_HEADLESS = os.getenv("INITIAL_HEADLESS", "true").lower() == "true"
PAUSE_BEFORE_FINAL_SUBMIT = os.getenv("PAUSE_BEFORE_FINAL_SUBMIT", "false").lower() == "true"
