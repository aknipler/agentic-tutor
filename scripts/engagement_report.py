"""Write the student engagement report as an Excel workbook.

Reads the tutor and assessor logs and the progress records, works out each student's engagement
with utils/engagement.py and writes the workbook with utils/engagement_workbook.py. See
docs/engagement-report-plan.md for the definitions and the validation checks.

The script only reads from the databases, so it has no --commit flag. The workbook lists login
codes, so the default output folder, data/reports/, is gitignored.

The report is deterministic. The same data and settings give the same figures.

Usage:
    .venv/Scripts/python.exe scripts/engagement_report.py
    .venv/Scripts/python.exe scripts/engagement_report.py --out data/reports/mid_semester.xlsx
    .venv/Scripts/python.exe scripts/engagement_report.py --validation-notes data/reports/notes.txt
"""

import argparse
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st

from mongodb.connectors.analytics import get_assessor_submission_counts, get_tutor_message_counts
from mongodb.connectors.base import get_mongo_client
from utils.engagement import Settings, StudentRecords, build_report
from utils.engagement_checks import (
    CheckResult,
    check_attempts,
    check_progress_clock,
    check_totals,
    question_texts,
)
from utils.engagement_workbook import RunInfo, build_workbook

CONVERSATIONS_COLLECTION = "user_conversations"
SUBMISSIONS_COLLECTION = "user_submissions"
PROGRESS_COLLECTION = "user_module_progress"
MODULES_COLLECTION = "modules_live"

# How many lines of each check's details to print.
PRINTED_DETAILS = 20


def _entries(expression: Any) -> Dict[str, Any]:
    """The key and value pairs of a document field, or none if the field isn't a document."""
    return {"$cond": [{"$eq": [{"$type": expression}, "object"]}, {"$objectToArray": expression}, []]}


# Progress records hold students' answer images under each question, which are large and not
# needed here. This keeps only the fields the report reads, on the server. Fields that aren't
# documents (some old records) are treated as empty.
PROGRESS_PIPELINE: List[Dict[str, Any]] = [
    {
        "$project": {
            "user_id": 1,
            "modules": {
                "$arrayToObject": {
                    "$map": {
                        "input": _entries("$modules"),
                        "as": "module",
                        "in": {
                            "k": "$$module.k",
                            "v": {
                                "topics": "$$module.v.topics",
                                "questions": {
                                    "$arrayToObject": {
                                        "$map": {
                                            "input": _entries("$$module.v.questions"),
                                            "as": "question",
                                            "in": {
                                                "k": "$$question.k",
                                                "v": {
                                                    "attempts": "$$question.v.attempts",
                                                    "competency_level": "$$question.v.competency_level",
                                                    "last_attempt": "$$question.v.last_attempt",
                                                },
                                            },
                                        }
                                    }
                                },
                            },
                        },
                    }
                }
            },
        }
    }
]


def load_records(progress_db: Any, logs_db: Any) -> List[StudentRecords]:
    """Read every student's logs and progress. Nothing is written."""
    conversations: Dict[str, list] = {}
    for doc in logs_db[CONVERSATIONS_COLLECTION].find({}, {"user_id": 1, "conversations": 1}):
        if doc.get("user_id"):
            conversations.setdefault(doc["user_id"], []).extend(doc.get("conversations") or [])

    submissions: Dict[str, list] = {}
    submission_fields = {
        "user_id": 1,
        "submissions.module": 1,
        "submissions.question": 1,
        "submissions.grade": 1,
        "submissions.timestamp": 1,
    }
    for doc in logs_db[SUBMISSIONS_COLLECTION].find({}, submission_fields):
        if doc.get("user_id"):
            submissions.setdefault(doc["user_id"], []).extend(doc.get("submissions") or [])

    progress: Dict[str, Dict[str, Any]] = {}
    for doc in progress_db[PROGRESS_COLLECTION].aggregate(PROGRESS_PIPELINE):
        if doc.get("user_id"):
            progress.setdefault(doc["user_id"], {}).update(doc.get("modules") or {})

    user_ids = sorted(set(conversations) | set(submissions) | set(progress))
    return [
        StudentRecords(user_id, conversations.get(user_id, []), submissions.get(user_id, []), progress.get(user_id))
        for user_id in user_ids
    ]


def git_commit() -> str:
    """The short commit hash the report was run from, noting uncommitted changes to tracked files."""
    try:
        run = lambda *args: subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        commit = run("rev-parse", "--short", "HEAD")
        changed = run("status", "--porcelain", "--untracked-files=no")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{commit} (with uncommitted changes)" if changed else commit


def read_notes(path: Path) -> List[str]:
    """Read the results of the hand checks, one per line. Blank lines and # lines are skipped."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


def zone_name(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise argparse.ArgumentTypeError(f"unknown time zone {value!r}")
    return value


def parse_args() -> argparse.Namespace:
    defaults = Settings()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, help="Where to write the workbook. Defaults to data/reports/engagement_<date>.xlsx.")
    parser.add_argument("--session-gap", type=float, default=defaults.session_gap.total_seconds() / 60,
                        help="Minutes of silence that end a session. Default %(default)s.")
    parser.add_argument("--shrink-k", type=float, default=defaults.shrink_k,
                        help="Weight of the cohort rate when shrinking a rate. Default %(default)s.")
    parser.add_argument("--min-weeks", type=int, default=defaults.min_weeks,
                        help="Starting value of the Prize 2 minimum active weeks. Default %(default)s.")
    parser.add_argument("--min-interactions", type=int, default=defaults.min_interactions,
                        help="Starting value of the Prize 2 minimum interactions. Default %(default)s.")
    parser.add_argument("--progress-timezone", type=zone_name, default=defaults.progress_timezone,
                        help="Time zone the server wrote progress times in. Set this if the clock check fails. Default %(default)s.")
    parser.add_argument("--report-date", type=date.fromisoformat,
                        help="Melbourne date to report as of, as YYYY-MM-DD. Defaults to today.")
    parser.add_argument("--validation-notes", type=Path,
                        help="A text file with the results of the hand checks, one per line, for the About sheet.")
    return parser.parse_args()


def print_check(check: CheckResult) -> None:
    print(f"  [{check.status.upper()}] {check.name}. {check.summary}")
    for line in check.details[:PRINTED_DETAILS]:
        print(f"      {line}")
    if len(check.details) > PRINTED_DETAILS:
        print(f"      ... and {len(check.details) - PRINTED_DETAILS} more in the workbook")


def main() -> None:
    args = parse_args()
    settings = Settings(
        session_gap=timedelta(minutes=args.session_gap),
        shrink_k=args.shrink_k,
        min_weeks=args.min_weeks,
        min_interactions=args.min_interactions,
        progress_timezone=args.progress_timezone,
    )

    now = datetime.now(ZoneInfo(settings.timezone))
    report_date = args.report_date or now.date()
    out = args.out or ROOT / "data" / "reports" / f"engagement_{report_date.isoformat()}.xlsx"
    notes = read_notes(args.validation_notes) if args.validation_notes else []

    client = get_mongo_client()
    progress_db = client[st.secrets["MONGODB_DATABASE_NAME"]]
    logs_db = client[st.secrets["MONGODB_LOGS_DATABASE_NAME"]]

    print("Reading the logs and progress records (read only)...")
    students = load_records(progress_db, logs_db)
    module_questions = question_texts(list(progress_db[MODULES_COLLECTION].find({}, {"index": 1, "tutorial_questions.question": 1})))
    print(f"  {len(students)} users have a record, {len(module_questions)} modules have questions.")

    report = build_report(students, report_date, settings)

    print("Running the validation checks...")
    checks = [
        check_totals(students, report.students, get_tutor_message_counts(), get_assessor_submission_counts()),
        check_attempts(students, module_questions),
        check_progress_clock(students, module_questions),
    ]
    for check in checks:
        print_check(check)

    run = RunInfo(now.strftime("%d %b %Y %H:%M %Z"), git_commit(), checks, notes)
    workbook = build_workbook(report, run)
    out.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(out)

    print(f"\n{len(report.students)} students with at least one interaction.")
    if report.data_range:
        print(f"Activity from {report.data_range[0]} to {report.data_range[1]}, reported as of {report_date}.")
    if report.warnings:
        print(f"Warnings (also on the About sheet), {len(report.warnings)} in all.")
        for line in report.warnings[:PRINTED_DETAILS]:
            print(f"  {line}")
    print(f"Wrote {out}")
    print("Scores and ranks are formulas, so they appear once the file is opened in a spreadsheet program.")


if __name__ == "__main__":
    main()
