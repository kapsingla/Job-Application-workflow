from __future__ import annotations

from typing import List, Optional, Literal, TypedDict, Dict, Any
from pydantic import BaseModel, Field


class ParsedJobDescription(BaseModel):
    company_name: str = Field(description="Company name extracted from the job posting")
    job_title: str = Field(description="Exact title of the role")
    job_id: Optional[str] = Field(default=None, description="Requisition ID (e.g., R12345)")
    location: str = Field(description="Job location or remote status")
    listed_salary_range: Optional[str] = Field(
        default=None,
        description="Listed base salary or total compensation range if present on the posting (e.g., '$220,000 - $280,000')"
    )
    estimated_max_comp_usd: Optional[int] = Field(
        default=None,
        description="Upper bound of listed base/total compensation in USD as an integer if stated (e.g., 280000), or None if unlisted"
    )
    is_high_impact_leadership_role: bool = Field(
        default=True,
        description="True if this is a high-impact senior leadership role (Sr. Manager, Director, Sr. Director, VP, Head of Engineering/AI/Data/Platform); False if junior/mid-level IC or pre-sales/commission role"
    )
    ats_type: Literal["workday", "greenhouse", "lever", "generic"] = Field(
        description="Detected Applicant Tracking System portal type"
    )
    must_have_skills: List[str] = Field(
        description="Top 5-10 hard technical skills and non-negotiable requirements"
    )
    nice_to_have_skills: List[str] = Field(
        description="Bonus or preferred qualifications"
    )
    key_responsibilities: List[str] = Field(
        description="Core responsibilities and deliverables of the role"
    )
    screening_questions: List[str] = Field(
        default_factory=list,
        description="Any custom application questions visible on the posting"
    )


class SkillCategory(BaseModel):
    category: str = Field(description="Skill group label, e.g., 'Languages & Core'")
    skills: List[str] = Field(description="Ordered list of skills with most relevant first")


class TailoredRole(BaseModel):
    company: str
    title: str
    location: str
    start_date: str
    end_date: str
    leadership_summary: str = Field(
        description="Short 2-4 sentence executive leadership paragraph summarizing scope, team size, architecture ownership, and stakeholder alignment for this role"
    )
    bullets: List[str] = Field(
        default_factory=list,
        description="Key Initiatives & Delivery bullets, each starting with a bold lead-in phrase wrapped in <strong>...</strong> followed by quantified outcomes"
    )


class TailoredProject(BaseModel):
    name: str
    tech_stack: List[str]
    bullets: List[str]


class TailoredResume(BaseModel):
    target_headline: str = Field(
        description="Sharp role-aligned headline positioned directly under the candidate's name"
    )
    tailored_summary: str = Field(
        description="4-5 sentence high-signal Professional Summary tailored to the target role"
    )
    core_competencies: List[str] = Field(
        description="10-12 core executive and technical competencies ordered for the target JD (rendered in a 2-column grid)"
    )
    prioritized_skills: List[SkillCategory] = Field(
        description="Technical Proficiencies categories (Cloud & Infra, Data & AI/ML, DevOps & Tools, Development, Methodologies) reordered so the JD's must-have keywords appear first"
    )
    tailored_experience: List[TailoredRole] = Field(
        description="All 5 roles from Master Profile (starting with Senior Manager, Application Development 2024-Present) with leadership_summary and Key Initiatives & Delivery bullets tailored without fabricating facts"
    )
    selected_projects: List[TailoredProject] = Field(
        default_factory=list,
        description="Optional additional projects if needed"
    )


class BulletRewriteSuggestion(BaseModel):
    original_bullet: str
    why_it_fails_10_sec_scan: str
    recommended_rewrite_angle: str


class RecruiterVerdict(BaseModel):
    verdict: Literal["GO", "NO_GO"] = Field(
        description="Strict GO or NO_GO decision after a ruthless 10-second top-of-page scan"
    )
    score_out_of_100: int = Field(
        description="Match score from 0 to 100 based on hard requirements and quantified impact"
    )
    ten_second_gut_reaction: str = Field(
        description="Blunt 1-2 sentence first impression from a Senior Recruiter who reads 1,000 resumes/day"
    )
    missing_hard_keywords: List[str] = Field(
        default_factory=list,
        description="Exact keywords from the JD missing or buried too deep in the resume"
    )
    weak_bullets_to_fix: List[BulletRewriteSuggestion] = Field(
        default_factory=list,
        description="Specific bullets that read as passive task descriptions instead of quantified outcomes"
    )


class BrowserAction(BaseModel):
    action_type: Literal["fill", "click", "select", "check", "upload", "wait"] = Field(
        description="Playwright action to perform on the target element"
    )
    selector: str = Field(
        description="Exact CSS or data-automation-id selector from the DOM snapshot"
    )
    value: Optional[str] = Field(
        default=None,
        description="Text value to fill, option text to select, or file path to upload"
    )
    reason: str = Field(description="Brief explanation of why this action is taken")


class PageActionPlan(BaseModel):
    page_status: Literal[
        "in_progress",
        "ready_for_final_review",
        "submitted",
        "blocked",
    ] = Field(
        description="Current status of the job application page"
    )
    blocker_reason: Optional[str] = Field(
        default=None,
        description="If page_status is 'blocked' (CAPTCHA, 2FA, email verification, unresolvable error), explain why"
    )
    actions: List[BrowserAction] = Field(
        default_factory=list,
        description="Ordered list of Playwright actions to execute on the current page before the next snapshot"
    )


class HarnessState(TypedDict, total=False):
    job_url: str
    raw_jd_text: str
    master_profile: Dict[str, Any]
    parsed_jd: ParsedJobDescription
    tailored_resume: TailoredResume
    recruiter_verdict: RecruiterVerdict
    revision_count: int
    compiled_pdf_path: str
    compiled_tex_path: str
    compiled_html_path: str
    compiled_json_path: str
    resume_only: bool
    browser_mode: Literal["headless", "headed"]
    application_status: Literal[
        "pending",
        "submitted_headless",
        "ready_for_review_headless",
        "failed_headless_needs_headed",
        "completed_headed",
        "error",
    ]
    last_error_reason: Optional[str]
    current_portal_url: Optional[str]
