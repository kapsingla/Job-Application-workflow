from __future__ import annotations

import csv
import io
import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any, Dict, List
from src.config import COMMON_QUESTIONS_SHEET_ID, DATA_DIR

COMMON_QUESTIONS_CACHE_PATH = DATA_DIR / "common_questions.json"
AGY_BIN_DIR = Path.home() / ".gemini" / "antigravity" / "bin"


def extract_spreadsheet_id(sheet_id_or_url: str) -> str:
    """Extracts the Google Drive/Sheets ID from either a full URL or raw ID."""
    match = re.search(r"/d/([a-zA-Z0-9_-]+)", sheet_id_or_url)
    if match:
        return match.group(1)
    return sheet_id_or_url.strip()


def _find_cli(name: str) -> str | None:
    candidate = AGY_BIN_DIR / name
    if candidate.exists():
        return str(candidate)
    return shutil.which(name)


def _parse_xlsx_sheets(xlsx_path: Path) -> Dict[str, List[List[str]]]:
    """Parses all worksheets from an .xlsx file using Python's built-in zipfile + ElementTree."""
    with zipfile.ZipFile(xlsx_path) as z:
        ns = {
            "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        }
        shared: List[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            sst = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in sst.findall("main:si", ns):
                texts = [t.text or "" for t in si.findall(".//main:t", ns)]
                shared.append("".join(texts))

        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        rel_map = {r.attrib["Id"]: r.attrib["Target"] for r in rels}
        result: Dict[str, List[List[str]]] = {}

        for s in wb.findall(".//main:sheet", ns):
            name = s.attrib["name"]
            rid = s.attrib[
                "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
            ]
            target = "xl/" + rel_map[rid].lstrip("/")
            if target not in z.namelist():
                continue
            tree = ET.fromstring(z.read(target))
            rows: List[List[str]] = []
            for row in tree.findall(".//main:row", ns):
                r_vals: List[str] = []
                for c in row.findall("main:c", ns):
                    t = c.attrib.get("t")
                    v = c.find("main:v", ns)
                    val = v.text if v is not None else ""
                    if t == "s" and val.isdigit():
                        val = shared[int(val)]
                    r_vals.append(str(val).strip())
                if any(r_vals):
                    rows.append(r_vals)
            result[name] = rows
        return result


def sync_common_questions_from_google(
    sheet_id_or_url: str = COMMON_QUESTIONS_SHEET_ID,
) -> List[Dict[str, str]]:
    """
    Uses Antigravity's `gdrive` or `gsheets` CLI (authenticated with your Google account)
    to fetch your Common Questions spreadsheet (`COMMON_QUESTIONS_SHEET_ID`)
    and cache it locally at `data/common_questions.json`.
    Supports both uploaded `.xlsx` files and native Google Sheets.
    """
    file_id = extract_spreadsheet_id(sheet_id_or_url)
    if not file_id:
        return load_cached_common_questions()

    gdrive_bin = _find_cli("gdrive")
    gsheets_bin = _find_cli("gsheets")
    qa_pairs: List[Dict[str, str]] = []

    # Path 1: Download .xlsx directly via `gdrive readonly download <ID>`
    if gdrive_bin:
        tmp_xlsx = Path("/tmp/agy_common_questions.xlsx")
        res = subprocess.run(
            [gdrive_bin, "readonly", "download", file_id, "--out", str(tmp_xlsx)],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0 and tmp_xlsx.exists() and zipfile.is_zipfile(tmp_xlsx):
            sheets = _parse_xlsx_sheets(tmp_xlsx)
            cq_rows = sheets.get("Common Question", [])
            if len(cq_rows) >= 2 and len(cq_rows[0]) > 3:
                # Horizontal Q&A layout (Row 0 = Questions, Row 1 = Answers)
                questions = cq_rows[0]
                answers = cq_rows[1]
                for q, a in zip(questions, answers):
                    if q.strip():
                        qa_pairs.append({"question": q.strip(), "answer": a.strip()})
            elif cq_rows:
                # Vertical Q&A layout
                for row in cq_rows:
                    if len(row) >= 2 and row[0] and row[1]:
                        qa_pairs.append({"question": row[0], "answer": row[1]})

    # Path 2: Native Google Sheets read via `gsheets readonly read-all <ID> --json`
    if not qa_pairs and gsheets_bin:
        res = subprocess.run(
            [gsheets_bin, "readonly", "read-all", file_id, "--json"],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            try:
                parsed = json.loads(res.stdout)
                rows = parsed if isinstance(parsed, list) else []
                for row in rows:
                    if isinstance(row, list) and len(row) >= 2:
                        qa_pairs.append(
                            {"question": str(row[0]).strip(), "answer": str(row[1]).strip()}
                        )
            except Exception:
                pass

    if not qa_pairs:
        return load_cached_common_questions()

    COMMON_QUESTIONS_CACHE_PATH.write_text(
        json.dumps(qa_pairs, indent=2), encoding="utf-8"
    )
    return qa_pairs


def load_cached_common_questions() -> List[Dict[str, str]]:
    if COMMON_QUESTIONS_CACHE_PATH.exists():
        try:
            return json.loads(COMMON_QUESTIONS_CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def enrich_master_profile_with_common_questions(
    master_profile: Dict[str, Any],
) -> Dict[str, Any]:
    """Merges synced Google Sheet common questions into the candidate's master_profile."""
    qa_list = sync_common_questions_from_google()
    if qa_list:
        master_profile = dict(master_profile)
        master_profile["common_questions_sheet"] = qa_list
    return master_profile
