"""Validation checks for the engagement report.

These compare the report against other records the app keeps. Like utils/engagement.py they are
pure functions over plain records, with no Streamlit and no pymongo. scripts/engagement_report.py
reads the databases, runs the checks and passes the results to the workbook's About sheet.

docs/engagement-report-plan.md lists the checks. The ones that need a person (marking
messages as questions, tracing students by hand, opening the workbook in a spreadsheet program)
are not here. The script takes their results as notes.
"""
from dataclasses import dataclass
from datetime import datetime
from statistics import median
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from utils.engagement import (
    StudentMetrics,
    StudentRecords,
    _get,
    read_submissions,
    read_tutor_log,
    to_utc,
)

# Progress records are written moments after the submission log, so the two times agree within
# a few seconds when the server runs on UTC.
CLOCK_TOLERANCE_SECONDS = 60
CLOCK_MATCH_SHARE = 0.9

# The details of a check can be long. The workbook shows this many lines and says how many more
# there were.
MAX_DETAIL_LINES = 100

# module key -> question id -> question text. Question ids are 1-based positions, as in the
# progress records.
ModuleQuestions = Mapping[str, Mapping[str, str]]


@dataclass(frozen=True)
class CheckResult:
    name: str
    # None means the check could not run.
    passed: Optional[bool]
    summary: str
    details: Tuple[str, ...] = ()

    @property
    def status(self) -> str:
        if self.passed is None:
            return "Not run"
        return "Passed" if self.passed else "Failed"


def question_texts(modules: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, str]]:
    """Map each module's question ids to question text, from modules_live documents.

    The tutorial_questions field is a list, or a dict keyed "q1", "q2" and so on. The progress
    records and the assessor page both turn either shape into 1-based ids, so this does too.
    """
    result: Dict[str, Dict[str, str]] = {}
    for module in modules:
        index = module.get("index")
        if index is None:
            continue
        questions = module.get("tutorial_questions") or []
        if isinstance(questions, Mapping):
            items = []
            for key, question in questions.items():
                digits = str(key)[1:] if str(key).startswith("q") else str(key)
                if digits.isdigit():
                    items.append((digits, question))
        else:
            items = [(str(position + 1), question) for position, question in enumerate(questions)]
        result[str(index)] = {
            question_id: question["question"]
            for question_id, question in items
            if isinstance(question, Mapping) and isinstance(question.get("question"), str)
        }
    return result


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" + ("" if number == 1 else "s")


def _cap(lines: List[str]) -> Tuple[str, ...]:
    if len(lines) <= MAX_DETAIL_LINES:
        return tuple(lines)
    return tuple(lines[:MAX_DETAIL_LINES]) + (f"... and {len(lines) - MAX_DETAIL_LINES} more",)


def check_totals(
    students: Sequence[StudentRecords],
    metrics: Sequence[StudentMetrics],
    admin_tutor: Mapping[str, int],
    admin_assessor: Mapping[str, int],
) -> CheckResult:
    """Compare each student's totals with the admin Data Analysis tab.

    The tab counts error turns as tutor messages and counts every logged submission, so the
    report's figures have those added back before the comparison.
    """
    name = "Totals match the admin Data Analysis tab"
    row_of = {row.user_id: row for row in metrics}
    user_ids = sorted({s.user_id for s in students} | set(admin_tutor) | set(admin_assessor))

    mismatches: List[str] = []
    skipped_total = 0
    for user_id in user_ids:
        records = next((s for s in students if s.user_id == user_id), None)
        row = row_of.get(user_id)

        if row is not None:
            tutor = row.tutor_messages + row.tutor_error_turns
            assessor = row.assessor_submissions
        elif records is not None:
            log = read_tutor_log(records.conversations)
            tutor = len(log.messages) + log.error_turns
            assessor = len(read_submissions(user_id, records.submissions, []))
        else:
            tutor = assessor = 0

        # A submission with no usable time or grade is left out of the report but the tab counts it.
        skipped = 0
        if records is not None:
            skipped = len(records.submissions) - len(read_submissions(user_id, records.submissions, []))
        skipped_total += skipped

        if tutor != admin_tutor.get(user_id, 0):
            mismatches.append(f"{user_id}: tutor messages, report {tutor}, admin tab {admin_tutor.get(user_id, 0)}")
        if assessor + skipped != admin_assessor.get(user_id, 0):
            mismatches.append(
                f"{user_id}: assessor submissions, report {assessor} plus {skipped} skipped, "
                f"admin tab {admin_assessor.get(user_id, 0)}"
            )

    compared = len(user_ids)
    note = f" {_count(skipped_total, 'unusable submission')} added back." if skipped_total else ""
    if mismatches:
        return CheckResult(name, False, f"{_count(len(mismatches), 'difference')} across {_count(compared, 'student')}.{note}", _cap(mismatches))
    return CheckResult(name, True, f"All {_count(compared, 'student')} match on tutor messages and assessor submissions.{note}")


def _log_attempts(
    records: StudentRecords, module_key: str, text: str
) -> Tuple[int, Optional[datetime]]:
    """The number of logged submissions for one question and the time of the latest."""
    times: List[datetime] = []
    count = 0
    for entry in records.submissions or ():
        if str(_get(entry, "module")) == module_key and _get(entry, "question") == text:
            count += 1
            moment = to_utc(_get(entry, "timestamp"))
            if moment is not None:
                times.append(moment)
    return count, max(times, default=None)


def check_attempts(students: Sequence[StudentRecords], module_questions: ModuleQuestions) -> CheckResult:
    """Compare logged submissions with the `attempts` field of each progress question.

    Each progress question is matched to its logged submissions by module and question text.
    A question whose text changed since students attempted it has no match, and a lost
    competency write shows as fewer attempts in progress than in the log.
    """
    name = "Attempts per question match the progress records"
    if not module_questions:
        return CheckResult(name, None, "No question text was available to match submissions to progress records.")

    compared = 0
    mismatches: List[str] = []
    not_compared: List[str] = []
    for records in students:
        if records.progress_modules is None:
            # Nothing to compare with, which is a gap in the data and not a difference.
            if records.submissions:
                not_compared.append(
                    f"{records.user_id}: no progress record, so {_count(len(records.submissions), 'logged submission')} not compared"
                )
            continue

        known_texts: Dict[str, set] = {}
        for module_key, module in records.progress_modules.items():
            questions = module_questions.get(module_key, {})
            known_texts[module_key] = set(questions.values())
            for question_id, record in sorted((_get(module, "questions") or {}).items(), key=lambda item: (len(item[0]), item[0])):
                text = questions.get(question_id)
                recorded = _get(record, "attempts") or 0
                logged = _log_attempts(records, module_key, text)[0] if text is not None else 0
                if recorded == 0 and logged == 0:
                    continue
                compared += 1
                if recorded != logged:
                    mismatches.append(
                        f"{records.user_id}: module {module_key} question {question_id}, "
                        f"log {logged}, progress {recorded}"
                    )

        # Submissions whose text matches no current question have no progress record to compare.
        orphaned = sum(
            1
            for entry in records.submissions or ()
            if _get(entry, "question") not in known_texts.get(str(_get(entry, "module")), set())
        )
        if orphaned:
            compared += 1
            mismatches.append(f"{records.user_id}: {_count(orphaned, 'logged submission')} matching no current question text")

    skipped = f" {_count(len(not_compared), 'student')} with no progress record not compared." if not_compared else ""
    if mismatches:
        return CheckResult(
            name, False, f"{_count(len(mismatches), 'difference')} out of {_count(compared, 'comparison')}.{skipped}", _cap(mismatches + not_compared)
        )
    return CheckResult(name, True, f"All {_count(compared, 'student-question pair')} match.{skipped}", _cap(not_compared))


def check_progress_clock(students: Sequence[StudentRecords], module_questions: ModuleQuestions) -> CheckResult:
    """Check that progress records and the submission log agree on the time.

    Progress times come from datetime.now() on the server and log times are UTC. Where a
    question's attempts agree between the two, the last attempt in the progress record should be
    within seconds of the latest logged submission. A constant gap of whole hours means the
    server is not on UTC.
    """
    name = "Progress clock is UTC"
    gaps: List[float] = []
    for records in students:
        for module_key, module in (records.progress_modules or {}).items():
            questions = module_questions.get(module_key, {})
            for question_id, record in (_get(module, "questions") or {}).items():
                text = questions.get(question_id)
                last_attempt = _get(record, "last_attempt")
                if text is None or not isinstance(last_attempt, datetime):
                    continue
                logged, latest = _log_attempts(records, module_key, text)
                if logged == 0 or latest is None or logged != (_get(record, "attempts") or 0):
                    continue
                gaps.append((last_attempt.replace(tzinfo=None) - latest.replace(tzinfo=None)).total_seconds())

    if not gaps:
        return CheckResult(name, None, "No question had matching attempts in both records, so the clocks could not be compared.")

    close = sum(1 for gap in gaps if abs(gap) <= CLOCK_TOLERANCE_SECONDS)
    typical = median(gaps)
    summary = (
        f"{close} of {_count(len(gaps), 'question')} agree within {CLOCK_TOLERANCE_SECONDS} seconds. "
        f"The median gap is {typical / 3600:.2f} hours."
    )
    if close / len(gaps) >= CLOCK_MATCH_SHARE:
        return CheckResult(name, True, summary)
    return CheckResult(
        name,
        False,
        summary + " Run again with --progress-timezone set to the server's zone.",
    )
