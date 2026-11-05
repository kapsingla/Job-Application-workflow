from __future__ import annotations

import json
from src.config import GEMINI_PRO_MODEL
from src.state import HarnessState, TailoredResume
from src.utils.antigravity_client import generate_structured


async def resume_tailor_node(state: HarnessState) -> dict:
    """
    Agent 2: Tailors the candidate's Master Profile (`data/master_profile.json`)
    to the target Job Description via Antigravity.
    """
    master_profile = state["master_profile"]
    parsed_jd = state["parsed_jd"]
    previous_verdict = state.get("recruiter_verdict")
    revision_count = state.get("revision_count", 0)

    critique_context = ""
    if previous_verdict and previous_verdict.verdict == "NO_GO":
        critique_context = f"""
CRITICAL FEEDBACK FROM SENIOR RECRUITER AGENT (Iteration {revision_count}):
- Recruiter 10-Second Reaction: {previous_verdict.ten_second_gut_reaction}
- Match Score: {previous_verdict.score_out_of_100}/100
- Missing Hard Keywords to Surface Prominently: {previous_verdict.missing_hard_keywords}
- Specific Weak Bullets to Rewrite Immediately:
{json.dumps([b.model_dump() for b in previous_verdict.weak_bullets_to_fix], indent=2)}

You MUST resolve every single critique above so the resume passes the 10-second scan on this revision.
"""

    candidate_name = master_profile.get("contact", {}).get("full_name", "the candidate")
    prompt = f"""
You are an elite Executive Technical Resume Writer tailoring {candidate_name}'s base resume (`data/master_profile.json`).

STRICT STRUCTURE & CONTENT RULES (MANDATORY):
1. NEVER fabricate companies, dates, degrees, or technologies not grounded in the Master Profile (`data/master_profile.json`).
2. Keep all chronological roles from `master_profile.experience` in `tailored_experience` in exact chronological order, and PORTRAY THE MOST RECENT TWO ROLES (Role 1 and Role 2) WITH TITLES COMPATIBLE WITH THE SENIOR LEADERSHIP ROLE BEING APPLIED FOR (never use "Senior Manager" + "Manager (IC)" when applying for Director / Head / Senior Director / VP roles):
   - Role 1 (Current / Most Recent Role in `master_profile.experience[0]`):
     * Title rule: Align title seniority and domain to match the target leadership role (e.g., for Director / Head of AI or Software Engineering roles: `Director, AI Engineering & Enterprise Platforms` or `Director, Software Engineering & Cloud Platforms`; for Senior Director / VP roles: `Senior Director, Engineering & Enterprise AI Platforms` or `Director, Platform & AI Engineering`).
     * Content rule: Preserve and tailor all key flagship initiatives from `master_profile.experience[0]`.
   - Role 2 (Second Most Recent Role in `master_profile.experience[1]`):
     * Title rule: Portray as a compatible progression immediately preceding Role 1 (e.g., `Senior Manager, Software & Cloud Platform Engineering` or `Associate Director, Application Development & Cloud Platforms` — NEVER use `Manager (IC)`).
     * Content rule: Preserve and tailor all key modernization, AI/automation, and velocity initiatives from `master_profile.experience[1]`.
   - Remaining Roles (`master_profile.experience[2:]`):
     * Preserve exact company names, dates, and titles from `master_profile.experience`.
3. Every role MUST have:
   - `leadership_summary`: A cohesive leadership paragraph first (summarizing team leadership, architecture governance, and cross-functional impact, tailored to mirror the target JD's language).
   - `bullets`: Under "Key Initiatives & Delivery:", each bullet starts with a bold lead-in title wrapped in `<strong>...</strong>` (e.g., `<strong>Enterprise MCP platform:</strong> Led the engineering team...`).
4. Populate `core_competencies` with 12 high-impact competencies ordered for the target role, and `prioritized_skills` with the 5 Technical Proficiencies categories.

{critique_context}

TARGET JOB DESCRIPTION:
{parsed_jd.model_dump_json(indent=2)}

CANDIDATE MASTER PROFILE:
{json.dumps(master_profile, indent=2)}
"""

    tailored_resume = await generate_structured(
        prompt=prompt,
        schema=TailoredResume,
        model_name=GEMINI_PRO_MODEL,
        temperature=0.25,
    )
    return {
        "tailored_resume": tailored_resume,
        "revision_count": revision_count + 1,
    }
