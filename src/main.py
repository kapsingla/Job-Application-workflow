from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from src.config import DATA_DIR, GEMINI_API_KEY, USE_ANTIGRAVITY, APPLICANT_EMAIL
from src.graph import build_harness_graph
from src.agents.job_board_scout import (
    interactive_multi_portal_login,
    search_linkedin_jobs,
    DEFAULT_SEARCH_QUERIES,
)
from src.utils.common_questions_sync import enrich_master_profile_with_common_questions
from src.utils.email_verifier import interactive_gmail_login

console = Console()


async def run_harness(job_url: str, jd_file: str | None, resume_only: bool) -> None:
    if not USE_ANTIGRAVITY and (
        not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here"
    ):
        console.print(
            "[bold red]ERROR:[/bold red] Either set `USE_ANTIGRAVITY=true` or provide `GEMINI_API_KEY` in `.env`."
        )
        return

    profile_path = DATA_DIR / "master_profile.json"
    master_profile = json.loads(profile_path.read_text(encoding="utf-8"))
    master_profile = enrich_master_profile_with_common_questions(master_profile)

    raw_jd_text = ""
    if jd_file:
        raw_jd_text = Path(jd_file).read_text(encoding="utf-8")

    initial_state = {
        "job_url": job_url,
        "raw_jd_text": raw_jd_text,
        "master_profile": master_profile,
        "resume_only": resume_only,
        "revision_count": 0,
        "application_status": "pending",
    }

    graph = build_harness_graph()

    synced_qa_count = len(master_profile.get("common_questions_sheet", []))
    console.print(
        Panel.fit(
            f"[bold cyan]Launching Antigravity Resume Builder & Apply Harness[/bold cyan]\n"
            f"Runtime: {'Google Antigravity (Signed-In Session)' if USE_ANTIGRAVITY else 'Gemini API Key'}\n"
            f"Common Questions Sheet: {synced_qa_count} Q&A rows loaded\n"
            f"Portal Account Email: {APPLICANT_EMAIL}\n"
            f"Target URL: {job_url or 'Local JD File'}\n"
            f"Mode: {'Resume Tailoring + 10s Recruiter Loop Only' if resume_only else 'Full End-to-End (Headless -> Headed Fallback)'}",
            border_style="cyan",
        )
    )

    async for event in graph.astream(initial_state, stream_mode="updates"):
        for node_name, update in event.items():
            if node_name == "jd_scout":
                jd = update["parsed_jd"]
                console.print(
                    f"\n[bold green]✓ Agent 1 (JD Scout):[/bold green] Parsed [bold]{jd.job_title}[/bold] at [bold]{jd.company_name}[/bold] (ATS: {jd.ats_type.upper()})"
                )
                console.print(f"  Must-Have Skills: {', '.join(jd.must_have_skills[:8])}")

            elif node_name == "resume_tailor":
                rev = update["revision_count"]
                tailored = update["tailored_resume"]
                console.print(
                    f"\n[bold blue]✓ Agent 2 (Resume Tailor - Pass #{rev}):[/bold blue] Crafted headline: [italic]'{tailored.target_headline}'[/italic]"
                )

            elif node_name == "recruiter_critic":
                verdict = update["recruiter_verdict"]
                color = "green" if verdict.verdict == "GO" else "yellow"
                table = Table(title="Agent 3: 10-Second Senior Recruiter Verdict", show_lines=True)
                table.add_column("Metric", style="bold")
                table.add_column("Evaluation")
                table.add_row("Decision", f"[bold {color}]{verdict.verdict}[/bold {color}] ({verdict.score_out_of_100}/100)")
                table.add_row("10s Gut Reaction", verdict.ten_second_gut_reaction)
                if verdict.missing_hard_keywords:
                    table.add_row("Missing Keywords", ", ".join(verdict.missing_hard_keywords))
                if verdict.weak_bullets_to_fix:
                    weak_summary = "\n".join(
                        f"• {b.original_bullet[:60]}... -> {b.recommended_rewrite_angle}"
                        for b in verdict.weak_bullets_to_fix
                    )
                    table.add_row("Bullets to Fix", weak_summary)
                console.print(table)

            elif node_name == "compile_pdf":
                console.print(
                    f"\n[bold green]✓ LaTeX -> PDF Compiler:[/bold green] Generated ATS-ready LaTeX & PDF:\n"
                    f"  LaTeX (.tex): [underline]{update['compiled_tex_path']}[/underline]\n"
                    f"  PDF   (.pdf): [underline]{update['compiled_pdf_path']}[/underline]\n"
                    f"  JSON  (.json): [underline]{update['compiled_json_path']}[/underline]"
                )

            elif node_name == "workday_headless":
                status = update.get("application_status")
                if status == "failed_headless_needs_headed":
                    console.print(
                        f"\n[bold yellow]! Headless Handoff Triggered:[/bold yellow] {update.get('last_error_reason')}\n"
                        f"  -> Switching to [bold cyan]HEADED MODE[/bold cyan] at {update.get('current_portal_url')}..."
                    )
                else:
                    console.print(
                        f"\n[bold green]✓ Headless Application Complete:[/bold green] Status = {status}"
                    )

            elif node_name == "workday_headed_fallback":
                status = update.get("application_status")
                console.print(
                    f"\n[bold green]✓ Headed Fallback Complete:[/bold green] Status = {status}"
                )


async def run_auto_search_and_apply(
    query: str | None, location: str, max_jobs: int, resume_only: bool
) -> None:
    queries = [query] if query else DEFAULT_SEARCH_QUERIES
    for q in queries:
        console.print(
            f"\n[bold magenta]Searching LinkedIn Jobs:[/bold magenta] '{q}' in '{location}' (Last 24h -> Past Week fallback)..."
        )
        jobs = await search_linkedin_jobs(
            query=q, location=location, past_24h=True, max_results=max_jobs
        )
        console.print(f"  Found {len(jobs)} matching jobs.")
        for job in jobs:
            console.print(
                f"\n[bold cyan]-> Running Harness for:[/bold cyan] {job.title} @ {job.company} ({job.job_url})"
            )
            try:
                await run_harness(
                    job_url=job.job_url, jd_file=None, resume_only=resume_only
                )
            except Exception as exc:
                console.print(f"[bold red]Skipped {job.company}:[/bold red] {exc}")


def main():
    parser = argparse.ArgumentParser(
        description="Antigravity Multi-Agent Resume Tailor, 10s Recruiter Critic & Workday Apply Harness"
    )
    parser.add_argument("--url", type=str, default="", help="Target Workday/Job Portal URL")
    parser.add_argument("--jd-file", type=str, default=None, help="Optional path to raw JD text file")
    parser.add_argument(
        "--resume-only",
        action="store_true",
        help="Run only JD Scout + Resume Tailor + 10s Recruiter Critic + PDF Compilation",
    )
    parser.add_argument(
        "--login-email",
        action="store_true",
        help="Open the persistent browser profile to sign into your job application Gmail (APPLICANT_EMAIL) once",
    )
    parser.add_argument(
        "--login-portals",
        action="store_true",
        help="Open the persistent browser profile with tabs for LinkedIn, Gmail, Indeed, and Dice so you can sign in once",
    )
    parser.add_argument(
        "--auto-search",
        action="store_true",
        help="Automatically search LinkedIn using your spreadsheet criteria and run the harness on discovered jobs",
    )
    parser.add_argument(
        "--query",
        type=str,
        default=None,
        help="Optional specific search query for --auto-search (defaults to all target roles from your sheet)",
    )
    parser.add_argument(
        "--location",
        type=str,
        default="United States",
        help="Location filter for --auto-search (default: 'United States')",
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=3,
        help="Max jobs per query during --auto-search",
    )
    args = parser.parse_args()

    if args.login_email:
        asyncio.run(interactive_gmail_login())
        return

    if args.login_portals:
        asyncio.run(interactive_multi_portal_login())
        return

    if args.auto_search:
        asyncio.run(
            run_auto_search_and_apply(
                query=args.query,
                location=args.location,
                max_jobs=args.max_jobs,
                resume_only=args.resume_only,
            )
        )
        return

    if not args.url and not args.jd_file:
        parser.error(
            "Please provide --url <job_url>, --jd-file <path_to_jd.txt>, --auto-search, --login-portals, or --login-email"
        )

    asyncio.run(run_harness(args.url, args.jd_file, args.resume_only))


if __name__ == "__main__":
    main()
