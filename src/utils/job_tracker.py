from __future__ import annotations

import fcntl
import os
import re
import shutil
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from src.config import DATA_DIR, OUTPUT_DIR

_ext_env = os.getenv("EXTERNAL_TRACKER_PATH", "").strip()
EXTERNAL_TRACKER_PATH = Path(_ext_env) if _ext_env else (DATA_DIR / "Job_Search_Tracker.xlsx")
LOCAL_TRACKER_PATH = DATA_DIR / "Job_Search_Tracker.xlsx"
TRACKER_LOCK_PATH = DATA_DIR / ".tracker.lock"
JOB_APPLICATIONS_DIR = OUTPUT_DIR / "Job Applications"
JOB_APPLICATIONS_DIR.mkdir(parents=True, exist_ok=True)

TRACKER_COLUMNS = [
    "#",
    "Company",
    "Job Title",
    "Location / Work Type",
    "Salary (listed)",
    "Posted / Reposted",
    "Source",
    "Job Link",
    "Hiring Contact",
    "Contact Link",
    "Resume Rework Needed?",
    "Resume Status",
    "Resume Folder",
    "Outreach Msg Status",
    "Application Status",
    "Detailed Reason",
    "Notes",
]


def split_application_status(raw_status: str, detailed_reason: str = "") -> tuple[str, str]:
    """
    Strictly normalizes `Application Status` into one of four canonical values:
      - 'Applied'
      - 'Not Applied'
      - 'Excluded'
      - 'Expired'
    and extracts any parenthetical or descriptive detail into `Detailed Reason`.
    """
    s = (raw_status or "").strip()
    d = (detailed_reason or "").strip()
    s_low = s.lower()

    if s_low in ("applied", "excluded", "expired", "not applied"):
        canon = {
            "applied": "Applied",
            "excluded": "Excluded",
            "expired": "Expired",
            "not applied": "Not Applied",
        }[s_low]
        if not d:
            d = "Applied" if canon == "Applied" else ""
        return canon, d

    # 1. Expired / Closed
    if any(
        k in s_low
        for k in (
            "expired",
            "closed",
            "unposted",
            "no active posting",
            "no longer accepting",
            "not currently accepting",
        )
    ):
        m = re.match(r"^(?:Excluded|Skipped|Closed)\s*\((.*)\)$", s, flags=re.I)
        reason = m.group(1).strip() if m else s
        return "Expired", (d or reason)

    # 2. Applied
    if s_low.startswith("applied") or ("duplicate of row" in s_low and "applied" in s_low):
        m = re.match(r"^Applied\s*\((.*)\)$", s, flags=re.I)
        if m:
            inner = m.group(1).strip()
            if re.match(r"^\d{4}-\d{2}-\d{2}$", inner):
                reason = f"Applied on {inner}"
            else:
                reason = inner
        else:
            reason = s
        return "Applied", (d or reason)

    # 3. Excluded / Skipped
    if s_low.startswith("excluded") or s_low.startswith("skipped"):
        m = re.match(r"^(?:Excluded|Skipped)\s*\((.*)\)$", s, flags=re.I)
        reason = (
            m.group(1).strip()
            if m
            else re.sub(r"^(?:Excluded|Skipped)\s*[:\-]?\s*", "", s, flags=re.I).strip()
        )
        return "Excluded", (d or reason or "Excluded per search criteria")

    # 4. Not Applied
    reason = d or (s if s_low not in ("not applied", "") else "Pending application")
    return "Not Applied", reason


def _col_letter(col_idx_zero_based: int) -> str:
    """Converts 0-based column index to Excel column letters (A, B, ..., P)."""
    result = ""
    n = col_idx_zero_based + 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def get_next_job_folder(company_name: str, job_title: str) -> Path:
    """
    Creates or reuses the numbered job folder matching `Job Applications/NN_Company_Title`
    starting from 01 as defined in `Job_Search_Tracker.xlsx`.
    """
    safe_comp = "".join(c if c.isalnum() else "_" for c in company_name).strip("_")[:30]
    safe_title = "".join(c if c.isalnum() else "_" for c in job_title).strip("_")[:50]

    existing = sorted(
        [d for d in JOB_APPLICATIONS_DIR.iterdir() if d.is_dir()],
        key=lambda p: p.name,
    )

    for d in existing:
        name_without_num = re.sub(r"^\d+_", "", d.name).lower()
        if safe_comp.lower() in name_without_num and (len(safe_title) < 5 or safe_title[:10].lower() in name_without_num):
            return d

    existing_nums = []
    for d in existing:
        prefix = d.name.split("_")[0]
        if prefix.isdigit():
            existing_nums.append(int(prefix))
    next_num = (max(existing_nums) + 1) if existing_nums else (1 + len(existing))
    folder_name = f"{next_num:02d}_{safe_comp}_{safe_title}"
    folder = JOB_APPLICATIONS_DIR / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def clear_tracker_rows() -> str:
    """
    Clears all existing job rows from `Job Tracker` (Sheet 1) while preserving Row 1 headers,
    column widths/formatting, and Sheet 2 (`Legend & Workflow`).
    """
    if not LOCAL_TRACKER_PATH.exists():
        return ""

    ns_uri = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    ET.register_namespace("", ns_uri)
    ns = {"main": ns_uri}

    with zipfile.ZipFile(LOCAL_TRACKER_PATH, "r") as zin:
        files_map: Dict[str, bytes] = {name: zin.read(name) for name in zin.namelist()}

    sheet_path = "xl/worksheets/sheet1.xml"
    tree = ET.fromstring(files_map[sheet_path])
    sheet_data = tree.find("main:sheetData", ns)
    if sheet_data is not None:
        for row in list(sheet_data.findall("main:row", ns)):
            if row.attrib.get("r") != "1":
                sheet_data.remove(row)

    files_map[sheet_path] = ET.tostring(tree, encoding="utf-8", xml_declaration=True)
    with zipfile.ZipFile(LOCAL_TRACKER_PATH, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in files_map.items():
            zout.writestr(name, data)

    try:
        if EXTERNAL_TRACKER_PATH.parent.exists():
            shutil.copy2(LOCAL_TRACKER_PATH, EXTERNAL_TRACKER_PATH)
            return str(EXTERNAL_TRACKER_PATH)
    except Exception:
        pass
    return str(LOCAL_TRACKER_PATH)


def _normalize_token(s: str) -> str:
    """Normalizes company names and job titles by stripping punctuation and noise tags."""
    import re
    cleaned = re.sub(r"[\(\[\{].*?[\)\]\}]", " ", (s or "").lower())
    cleaned = re.sub(r"\b(verified job|easy apply|remote|hybrid)\b", " ", cleaned, flags=re.IGNORECASE)
    return re.sub(r"[^a-z0-9]+", " ", cleaned).strip()


def _extract_cell_value(c_el: ET.Element, ns: dict, shared_strings: List[str]) -> str:
    cell_type = c_el.attrib.get("t", "")
    if cell_type == "s":
        v_node = c_el.find("main:v", ns)
        if v_node is not None and v_node.text:
            idx = int(v_node.text)
            if 0 <= idx < len(shared_strings):
                return shared_strings[idx].strip()
    elif cell_type == "inlineStr":
        t_node = c_el.find(".//main:t", ns)
        if t_node is not None and t_node.text:
            return t_node.text.strip()
    else:
        v_node = c_el.find("main:v", ns)
        if v_node is not None and v_node.text:
            return v_node.text.strip()
        t_node = c_el.find(".//main:t", ns)
        if t_node is not None and t_node.text:
            return t_node.text.strip()
    return ""


def append_or_update_tracker_row(
    company: str,
    job_title: str,
    location: str,
    job_url: str,
    resume_status: str,
    resume_folder: str,
    application_status: str,
    notes: str,
    salary: str = "Not listed",
    posted: str = "Active",
    source: str = "LinkedIn / Direct",
    hiring_contact: str = "Not listed on posting",
    contact_link: str = "",
    rework_needed: str = "Yes",
    outreach_status: str = "Not started",
    detailed_reason: str = "",
) -> str:
    """
    Appends or updates a row in the `Job Tracker` worksheet inside `Job_Search_Tracker.xlsx`
    using the 17-column schema (where `Application Status` is strictly `Applied` / `Not Applied` / `Excluded` / `Expired`
    and `Detailed Reason` holds the specific date or exclusion/expiration reason).
    Updates `data/Job_Search_Tracker.xlsx` and mirrors to `EXTERNAL_TRACKER_PATH` if configured and writable.
    """
    canon_status, det_reason = split_application_status(application_status, detailed_reason)

    TRACKER_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TRACKER_LOCK_PATH, "a+", encoding="utf-8") as lock_fh:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
        try:
            if not LOCAL_TRACKER_PATH.exists() and EXTERNAL_TRACKER_PATH.exists():
                try:
                    shutil.copy2(EXTERNAL_TRACKER_PATH, LOCAL_TRACKER_PATH)
                except Exception:
                    pass

            if not LOCAL_TRACKER_PATH.exists():
                return ""

            ns_uri = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
            ET.register_namespace("", ns_uri)
            ns = {"main": ns_uri}

            with zipfile.ZipFile(LOCAL_TRACKER_PATH, "r") as zin:
                namelist = zin.namelist()
                files_map: Dict[str, bytes] = {name: zin.read(name) for name in namelist}

            sheet_path = "xl/worksheets/sheet1.xml"
            if sheet_path not in files_map:
                return str(LOCAL_TRACKER_PATH)

            tree = ET.fromstring(files_map[sheet_path])
            sheet_data = tree.find("main:sheetData", ns)
            if sheet_data is None:
                return str(LOCAL_TRACKER_PATH)

            shared_strings: List[str] = []
            if "xl/sharedStrings.xml" in files_map:
                try:
                    sst = ET.fromstring(files_map["xl/sharedStrings.xml"])
                    for si in sst.findall("main:si", ns):
                        t_nodes = si.findall(".//main:t", ns)
                        shared_strings.append("".join(t.text or "" for t in t_nodes))
                except Exception:
                    pass

            rows = sheet_data.findall("main:row", ns)

            # Check if an existing row matches company + job_title (case-insensitive) and update in-place
            matched_row_el = None
            matched_row_num = None
            for r in rows:
                r_num_str = r.attrib.get("r", "1")
                if r_num_str == "1":
                    continue
                cells = {}
                for c in r.findall("main:c", ns):
                    ref = c.attrib.get("r", "")
                    col_letters = "".join(ch for ch in ref if ch.isalpha())
                    cells[col_letters] = _extract_cell_value(c, ns, shared_strings)
                if (
                    _normalize_token(cells.get("B", "")) == _normalize_token(company)
                    and _normalize_token(cells.get("C", "")) == _normalize_token(job_title)
                ):
                    matched_row_el = r
                    matched_row_num = int(r_num_str)
                    # Preserve existing salary/posted/source if caller passed defaults
                    if salary == "Not listed" and cells.get("E"):
                        salary = cells["E"]
                    if posted == "Active" and cells.get("F"):
                        posted = cells["F"]
                    if source == "LinkedIn / Direct" and cells.get("G"):
                        source = cells["G"]
                    if not job_url and cells.get("H"):
                        job_url = cells["H"]
                    break

            if matched_row_el is not None and matched_row_num is not None:
                target_row_num = matched_row_num
                row_id_label = str(target_row_num - 1)
                for c in list(matched_row_el.findall("main:c", ns)):
                    matched_row_el.remove(c)
                target_row_el = matched_row_el
            else:
                max_row_num = 1
                for r in rows:
                    try:
                        r_num = int(r.attrib.get("r", "1"))
                        if r_num > max_row_num:
                            max_row_num = r_num
                    except ValueError:
                        pass
                target_row_num = max_row_num + 1
                row_id_label = str(target_row_num - 1)
                target_row_el = ET.SubElement(sheet_data, f"{{{ns_uri}}}row", {"r": str(target_row_num)})

            row_values: List[str] = [
                row_id_label,
                company,
                job_title,
                location,
                salary,
                posted,
                source,
                job_url,
                hiring_contact,
                contact_link,
                rework_needed,
                resume_status,
                resume_folder,
                outreach_status,
                canon_status,
                det_reason,
                notes,
            ]

            for col_idx, val in enumerate(row_values):
                cell_ref = f"{_col_letter(col_idx)}{target_row_num}"
                c_el = ET.SubElement(
                    target_row_el, f"{{{ns_uri}}}c", {"r": cell_ref, "t": "inlineStr"}
                )
                is_el = ET.SubElement(c_el, f"{{{ns_uri}}}is")
                t_el = ET.SubElement(is_el, f"{{{ns_uri}}}t")
                t_el.text = str(val or "")

            # Update <dimension ref="A1:Q{final_max_row}"/> so Excel/openpyxl always sees all rows & columns
            dim_el = tree.find("main:dimension", ns)
            if dim_el is not None:
                all_r_nums = [int(r.attrib.get("r", "1")) for r in sheet_data.findall("main:row", ns) if r.attrib.get("r", "1").isdigit()]
                final_max = max(all_r_nums) if all_r_nums else target_row_num
                dim_el.set("ref", f"A1:{_col_letter(len(TRACKER_COLUMNS) - 1)}{final_max}")

            files_map[sheet_path] = ET.tostring(tree, encoding="utf-8", xml_declaration=True)

            with zipfile.ZipFile(LOCAL_TRACKER_PATH, "w", zipfile.ZIP_DEFLATED) as zout:
                for name, data in files_map.items():
                    zout.writestr(name, data)

            # Mirror back to EXTERNAL_TRACKER_PATH if configured and accessible
            try:
                if EXTERNAL_TRACKER_PATH != LOCAL_TRACKER_PATH and EXTERNAL_TRACKER_PATH.parent.exists():
                    shutil.copy2(LOCAL_TRACKER_PATH, EXTERNAL_TRACKER_PATH)
                    return str(EXTERNAL_TRACKER_PATH)
            except Exception:
                pass

            return str(LOCAL_TRACKER_PATH)
        finally:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)


_TRACKER_CACHE_MTIME: float = 0.0
_TRACKER_CACHE_ROWS: List[Dict[str, str]] = []


def read_tracker_rows() -> List[Dict[str, str]]:
    """Reads all job rows from `Job_Search_Tracker.xlsx` into a list of dicts keyed by `TRACKER_COLUMNS`."""
    global _TRACKER_CACHE_MTIME, _TRACKER_CACHE_ROWS
    try:
        if EXTERNAL_TRACKER_PATH.exists() and not LOCAL_TRACKER_PATH.exists():
            shutil.copy2(EXTERNAL_TRACKER_PATH, LOCAL_TRACKER_PATH)
    except Exception:
        pass

    if not LOCAL_TRACKER_PATH.exists():
        return []

    try:
        current_mtime = LOCAL_TRACKER_PATH.stat().st_mtime
        if _TRACKER_CACHE_ROWS and current_mtime == _TRACKER_CACHE_MTIME:
            return list(_TRACKER_CACHE_ROWS)
    except Exception:
        current_mtime = 0.0

    ns_uri = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    ns = {"main": ns_uri}
    shared_strings: List[str] = []
    with zipfile.ZipFile(LOCAL_TRACKER_PATH, "r") as zin:
        namelist = zin.namelist()
        if "xl/sharedStrings.xml" in namelist:
            try:
                sst = ET.fromstring(zin.read("xl/sharedStrings.xml"))
                for si in sst.findall("main:si", ns):
                    t_nodes = si.findall(".//main:t", ns)
                    shared_strings.append("".join(t.text or "" for t in t_nodes))
            except Exception:
                pass
        tree = ET.fromstring(zin.read("xl/worksheets/sheet1.xml"))
    sd = tree.find("main:sheetData", ns)
    if sd is None:
        return []

    out: List[Dict[str, str]] = []
    for r in sd.findall("main:row", ns):
        if r.attrib.get("r") == "1":
            continue
        cells: Dict[str, str] = {}
        for c in r.findall("main:c", ns):
            ref = c.attrib.get("r", "")
            col_letters = "".join(ch for ch in ref if ch.isalpha())
            cells[col_letters] = _extract_cell_value(c, ns, shared_strings)
        row_dict: Dict[str, str] = {}
        for idx, col_name in enumerate(TRACKER_COLUMNS):
            row_dict[col_name] = cells.get(_col_letter(idx), "")
        out.append(row_dict)
    _TRACKER_CACHE_MTIME = current_mtime
    _TRACKER_CACHE_ROWS = list(out)
    return out


def _extract_req_or_job_ids(text: str) -> set[str]:
    """Extracts canonical LinkedIn job IDs, Oracle Cloud job IDs, and Workday/ATS requisition IDs from a URL or notes string."""
    import re
    if not text:
        return set()
    ids = set()
    # LinkedIn job IDs
    for m in re.findall(r"(?:currentJobId=|/jobs/view/|_[RJrj]{0,2})(\d{5,12})", text):
        ids.add(m.lower())
    # Oracle Cloud and generic ATS /job/<id>
    for m in re.findall(r"(?:/job/|/jobs/|/sites/[^/]+/job/|jobId=)(\d{4,12})", text):
        ids.add(m.lower())
    # Workday requisition patterns (e.g. R014580-1, JR123456)
    for m in re.findall(r"\b(J?R\d{5,10}(?:-\d+)?)\b", text, flags=re.IGNORECASE):
        ids.add(m.lower())
    # Workday trailing slug requisition IDs (e.g. _495, _R014580-1)
    for m in re.findall(r"_(?:[rR]?\d{3,10}(?:-\d+)?)\b", text):
        ids.add(m.strip("_").lower())
    return ids


def is_job_already_tracked(company: str, job_title: str, job_url: str = "") -> bool:
    """
    Returns True if `(company, job_title)`, `job_url`, or any extracted LinkedIn/ATS Requisition ID
    is already present in `Job_Search_Tracker.xlsx` (checking both external and local tracker files).
    """
    c_norm = _normalize_token(company)
    t_norm = _normalize_token(job_title)
    u_norm = job_url.split("?")[0].strip().lower() if job_url else ""
    target_ids = _extract_req_or_job_ids(job_url)

    for r in read_tracker_rows():
        rc = _normalize_token(r.get("Company", ""))
        rt = _normalize_token(r.get("Job Title", ""))
        ru_raw = r.get("Job Link", "")
        ru = ru_raw.split("?")[0].strip().lower()
        row_ids = (
            _extract_req_or_job_ids(ru_raw)
            | _extract_req_or_job_ids(r.get("Detailed Reason", ""))
            | _extract_req_or_job_ids(r.get("Notes", ""))
        )

        if c_norm and t_norm and rc == c_norm and rt == t_norm:
            return True
        if u_norm and ru and u_norm == ru:
            return True
        if target_ids and row_ids and (target_ids & row_ids):
            return True
    return False


def is_job_already_applied(company: str, job_title: str, job_url: str = "") -> bool:
    """
    Hard guard: Returns True if the job in `Job_Search_Tracker.xlsx` already has an
    `Application Status` indicating it was applied or is already prepared at Final Review
    (e.g. 'Applied', 'Submitted', 'Paused at Final Review', 'Ready to Submit').
    """
    c_norm = _normalize_token(company)
    t_norm = _normalize_token(job_title)
    u_norm = job_url.split("?")[0].strip().lower() if job_url else ""
    target_ids = _extract_req_or_job_ids(job_url)

    applied_keywords = (
        "applied",
        "submitted",
        "paused at final review",
        "ready to submit",
        "completed",
    )

    for r in read_tracker_rows():
        status = (r.get("Application Status", "") or "").strip().lower()
        if not any(k in status for k in applied_keywords):
            continue
        rc = _normalize_token(r.get("Company", ""))
        rt = _normalize_token(r.get("Job Title", ""))
        ru_raw = r.get("Job Link", "")
        ru = ru_raw.split("?")[0].strip().lower()
        row_ids = (
            _extract_req_or_job_ids(ru_raw)
            | _extract_req_or_job_ids(r.get("Detailed Reason", ""))
            | _extract_req_or_job_ids(r.get("Notes", ""))
        )

        if c_norm and t_norm and rc == c_norm and rt == t_norm:
            return True
        if u_norm and ru and u_norm == ru:
            return True
        if target_ids and row_ids and (target_ids & row_ids):
            return True
    return False


update_job_tracker = append_or_update_tracker_row


