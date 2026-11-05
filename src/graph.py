from __future__ import annotations

from typing import Literal
from langgraph.graph import StateGraph, START, END
from src.config import MAX_RECRUITER_REVISIONS, INITIAL_HEADLESS
from src.state import HarnessState
from src.agents.jd_scout import jd_scout_node
from src.agents.resume_tailor import resume_tailor_node
from src.agents.recruiter_critic import recruiter_critic_node
from src.agents.workday_applicator import (
    workday_headless_node,
    workday_headed_fallback_node,
)
from src.utils.pdf_compiler import compile_tailored_resume_to_pdf


async def compile_pdf_node(state: HarnessState) -> dict:
    """Compiles the recruiter-approved tailored resume JSON into LaTeX (.tex) and renders it to PDF (.pdf)."""
    pdf_path, tex_path, html_path, json_path = await compile_tailored_resume_to_pdf(
        master_profile=state["master_profile"],
        tailored_resume=state["tailored_resume"],
        company_name=state["parsed_jd"].company_name,
        job_title=state["parsed_jd"].job_title,
        job_url=state.get("job_url", ""),
        location=state["parsed_jd"].location,
        raw_jd_text=state.get("raw_jd_text", ""),
        recruiter_verdict=state.get("recruiter_verdict"),
    )
    return {
        "compiled_pdf_path": pdf_path,
        "compiled_tex_path": tex_path,
        "compiled_html_path": html_path,
        "compiled_json_path": json_path,
    }


def route_after_recruiter(
    state: HarnessState,
) -> Literal["resume_tailor", "compile_pdf"]:
    """
    Loops back to the Resume Tailor Agent if the 10-Second Senior Recruiter Critic
    gives a NO_GO verdict (up to MAX_RECRUITER_REVISIONS), otherwise proceeds to PDF compilation.
    """
    verdict = state.get("recruiter_verdict")
    revisions = state.get("revision_count", 0)

    if verdict and verdict.verdict == "GO":
        return "compile_pdf"
    if revisions >= MAX_RECRUITER_REVISIONS:
        return "compile_pdf"
    return "resume_tailor"


def route_after_pdf_compile(
    state: HarnessState,
) -> Literal["workday_headless", "workday_headed_fallback", "__end__"]:
    """Routes to headless browser attempt first (unless resume_only is set)."""
    if state.get("resume_only"):
        return "__end__"
    if INITIAL_HEADLESS:
        return "workday_headless"
    return "workday_headed_fallback"


def route_after_headless_attempt(
    state: HarnessState,
) -> Literal["workday_headed_fallback", "__end__"]:
    """
    If any issue happened during the headless application attempt, automatically
    routes to the headed browser fallback node.
    """
    if state.get("application_status") == "failed_headless_needs_headed":
        return "workday_headed_fallback"
    return "__end__"


def build_harness_graph():
    workflow = StateGraph(HarnessState)

    workflow.add_node("jd_scout", jd_scout_node)
    workflow.add_node("resume_tailor", resume_tailor_node)
    workflow.add_node("recruiter_critic", recruiter_critic_node)
    workflow.add_node("compile_pdf", compile_pdf_node)
    workflow.add_node("workday_headless", workday_headless_node)
    workflow.add_node("workday_headed_fallback", workday_headed_fallback_node)

    workflow.add_edge(START, "jd_scout")
    workflow.add_edge("jd_scout", "resume_tailor")
    workflow.add_edge("resume_tailor", "recruiter_critic")

    workflow.add_conditional_edges(
        "recruiter_critic",
        route_after_recruiter,
        {
            "resume_tailor": "resume_tailor",
            "compile_pdf": "compile_pdf",
        },
    )

    workflow.add_conditional_edges(
        "compile_pdf",
        route_after_pdf_compile,
        {
            "workday_headless": "workday_headless",
            "workday_headed_fallback": "workday_headed_fallback",
            "__end__": END,
        },
    )

    workflow.add_conditional_edges(
        "workday_headless",
        route_after_headless_attempt,
        {
            "workday_headed_fallback": "workday_headed_fallback",
            "__end__": END,
        },
    )

    workflow.add_edge("workday_headed_fallback", END)

    return workflow.compile()
