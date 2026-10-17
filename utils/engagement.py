"""Engagement metrics and prize scores for the PRQ tutor.

These are pure functions over plain records. Nothing here imports Streamlit or pymongo, so the
module runs and is tested without a database. scripts/engagement_report.py reads the two
databases, calls build_report and writes the workbook.

docs/engagement-report-plan.md sets out every rule implemented here. The records are the
documents the app already writes.

- conversations are the entries of a user_conversations document. Each holds a `conversation`
  list of [student_message, tutor_message] pairs. Pairs logged since timestamps were added carry
  a third logged_at element, and older pairs are undated.
- submissions are the entries of a user_submissions document.
- progress_modules is the `modules` mapping of a user_module_progress document.

The module is deterministic. The same records and settings always give the same report, and
nothing reads the clock. The caller passes the report date.
"""
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple
from zoneinfo import ZoneInfo

# A turn the tutor failed to answer is logged with this prefix on the tutor side. The student's
# retry is the message that counts, so the failed turn is left out.
ERROR_PREFIX = "[error]"

# The Attempts sheet shows this much of each question.
QUESTION_PREFIX_CHARS = 80

# A tutor message is a follow-up question if it contains "?" or starts with one of these words.
QUESTION_WORDS = (
    "why", "how", "what", "when", "where", "which", "who",
    "can", "could", "would", "should", "is", "are", "does", "do",
)
_QUESTION_START = re.compile(r"^\W*(?:" + "|".join(QUESTION_WORDS) + r")\b", re.IGNORECASE)

TopicKey = Tuple[str, str]


@dataclass(frozen=True)
class Settings:
    """The values a lecturer may want to change between runs."""

    session_gap: timedelta = timedelta(minutes=30)
    shrink_k: float = 5
    min_weeks: int = 3
    min_interactions: int = 10
    # Students with at least this many undated tutor messages are flagged.
    incomplete_timing_messages: int = 10
    timezone: str = "Australia/Melbourne"
    # Progress records are stamped with datetime.now() on the server and stored without a zone.
    # This is the zone to read them in, and UTC is right only if the server runs on UTC.
    progress_timezone: str = "UTC"


@dataclass(frozen=True)
class StudentRecords:
    """Everything the logs and progress database hold for one student."""

    user_id: str
    conversations: Sequence[Mapping[str, Any]] = ()
    submissions: Sequence[Mapping[str, Any]] = ()
    progress_modules: Optional[Mapping[str, Any]] = None


@dataclass(frozen=True)
class TutorMessage:
    module: str
    topic: str
    text: str
    # UTC, or None for a pair logged before timestamps were added.
    at: Optional[datetime]


@dataclass(frozen=True)
class TutorLog:
    messages: List[TutorMessage]
    # Turns whose reply was an [error] entry. They are kept apart so totals can be reconciled
    # with the admin Data Analysis tab, which counts them.
    error_turns: int
    # When each topic conversation started, in UTC.
    started: Dict[TopicKey, datetime]


@dataclass(frozen=True)
class Submission:
    module: str
    question: str
    level: int
    at: datetime


@dataclass(frozen=True)
class AttemptRow:
    """One student's attempts at one assessor question. This is a row of the Attempts sheet."""

    user_id: str
    module: str
    question: str
    levels: Tuple[int, ...]
    days: Tuple[date, ...]

    @property
    def attempts(self) -> int:
        return len(self.levels)

    @property
    def first_level(self) -> int:
        return self.levels[0]

    @property
    def best_level(self) -> int:
        return max(self.levels)

    @property
    def level_sequence(self) -> str:
        return " → ".join(str(level) for level in self.levels)

    @property
    def question_start(self) -> str:
        return self.question[:QUESTION_PREFIX_CHARS]


@dataclass(frozen=True)
class StudentMetrics:
    """Every figure for one student that has at least one interaction."""

    user_id: str

    # Overall usage
    tutor_messages: int
    tutor_undated_messages: int
    tutor_error_turns: int
    tutor_sessions: int
    tutor_active_days: int
    assessor_submissions: int
    assessor_sessions: int
    assessor_active_days: int
    sessions: int
    active_days: int
    active_weeks: int
    active_days_per_week: Optional[float]
    first_active: Optional[date]
    last_active: Optional[date]
    tutor_timing_incomplete: bool

    # Depth
    tutor_interactions_per_session: Optional[float]
    assessor_interactions_per_session: Optional[float]
    interactions_per_session: Optional[float]
    topics_worked: int
    messages_per_topic: Optional[float]
    follow_ups: int
    questions_attempted: int
    questions_retried: int
    attempts_per_question: Optional[float]

    # Meaningful learning engagement
    questions_first_below_2: int
    questions_responded: int
    questions_improved: int
    questions_revisited: int
    topics_revisited: int
    # None when the student has no progress record.
    topics_at_level_2: Optional[int]
    questions_at_level_2: Optional[int]

    # Interactions in each week, keyed by the Monday that starts the week. Undated tutor
    # messages are not in tutor_by_week.
    tutor_by_week: Dict[date, int] = field(default_factory=dict)
    assessor_by_week: Dict[date, int] = field(default_factory=dict)

    @property
    def interactions(self) -> int:
        return self.tutor_messages + self.assessor_submissions

    @property
    def follow_up_share(self) -> Optional[float]:
        return _ratio(self.follow_ups, self.tutor_messages)

    @property
    def responded_share(self) -> Optional[float]:
        return _ratio(self.questions_responded, self.questions_first_below_2)

    @property
    def improved_share(self) -> Optional[float]:
        return _ratio(self.questions_improved, self.questions_first_below_2)

    @property
    def items_worked(self) -> int:
        return self.questions_attempted + self.topics_worked

    @property
    def items_revisited(self) -> int:
        return self.questions_revisited + self.topics_revisited

    @property
    def revisited_share(self) -> Optional[float]:
        return _ratio(self.items_revisited, self.items_worked)

    @property
    def items_at_level_2(self) -> Optional[int]:
        if self.topics_at_level_2 is None or self.questions_at_level_2 is None:
            return None
        return self.topics_at_level_2 + self.questions_at_level_2


@dataclass(frozen=True)
class Measure:
    """One scored measure on a prize sheet.

    For a plain measure, read returns the value, or None when the student has no data. For a
    rate, read returns (successes, opportunities) and the score uses the rate shrunk toward the
    cohort rate.
    """

    key: str
    label: str
    weight: float
    read: Callable[[StudentMetrics], Any]
    is_rate: bool = False
    # Rates only. These name the two counts a rate divides, for the workbook's column headings.
    successes_label: str = ""
    opportunities_label: str = ""


# A student who never used a mode has no data for that mode's measures, which is different from
# a count of zero. The measures below use "or None" so a zero count leaves a blank percentile
# and the student isn't marked down for it.
PRIZE_1_MEASURES: Tuple[Measure, ...] = (
    Measure("active_days", "Active days, combined", 1, lambda s: s.active_days or None),
    Measure("active_weeks", "Active weeks, combined", 1, lambda s: s.active_weeks or None),
    Measure("active_days_per_week", "Active days per week", 0, lambda s: s.active_days_per_week),
    Measure("sessions", "Sessions, combined", 0, lambda s: s.sessions or None),
    Measure("tutor_messages", "Tutor messages", 0, lambda s: s.tutor_messages or None),
    Measure("assessor_submissions", "Assessor submissions", 0, lambda s: s.assessor_submissions or None),
)

PRIZE_2_MEASURES: Tuple[Measure, ...] = (
    Measure(
        "improvement", "Improvement after feedback", 1,
        lambda s: (s.questions_improved, s.questions_first_below_2), is_rate=True,
        successes_label="questions improved", opportunities_label="questions first scored below 2",
    ),
    Measure(
        "revisiting", "Revisiting", 1,
        lambda s: (s.items_revisited, s.items_worked), is_rate=True,
        successes_label="questions and topics revisited", opportunities_label="questions and topics worked on",
    ),
    Measure(
        "follow_ups", "Follow-up questions", 1,
        lambda s: (s.follow_ups, s.tutor_messages), is_rate=True,
        successes_label="follow-up questions", opportunities_label="tutor messages",
    ),
    Measure(
        "responded", "Responded to feedback", 0,
        lambda s: (s.questions_responded, s.questions_first_below_2), is_rate=True,
        successes_label="questions retried", opportunities_label="questions first scored below 2",
    ),
    Measure("messages_per_topic", "Messages per topic conversation", 0, lambda s: s.messages_per_topic),
    Measure("interactions_per_session", "Interactions per session", 0, lambda s: s.interactions_per_session),
    Measure("attempts_per_question", "Attempts per question", 0, lambda s: s.attempts_per_question),
    Measure("level_2", "Topics and questions at level 2", 0, lambda s: s.items_at_level_2),
)


@dataclass(frozen=True)
class MeasureCell:
    """One student's result on one measure."""

    # The value as reported. For a rate this is successes divided by opportunities.
    raw: Optional[float]
    # Rates only. The raw rate shrunk toward the cohort rate.
    adjusted: Optional[float]
    # Position in the cohort from 0 to 100, or None when the student has no data.
    percentile: Optional[float]
    successes: Optional[int] = None
    opportunities: Optional[int] = None


@dataclass(frozen=True)
class PrizeRow:
    user_id: str
    cells: Dict[str, MeasureCell]
    score: Optional[float]
    eligible: bool
    # None for an ineligible student or one with no score.
    rank: Optional[int]


@dataclass(frozen=True)
class PrizeTable:
    measures: Tuple[Measure, ...]
    weights: Dict[str, float]
    # Total successes over total opportunities across students with data, for each rate.
    cohort_rates: Dict[str, Optional[float]]
    rows: List[PrizeRow]


@dataclass(frozen=True)
class EngagementReport:
    settings: Settings
    report_date: date
    students: List[StudentMetrics]
    attempts: List[AttemptRow]
    # The Monday of every week from the cohort's first activity to the report date.
    weeks: List[date]
    prize_1: PrizeTable
    prize_2: PrizeTable
    # First and last active dates across the cohort, or None when nobody has any.
    data_range: Optional[Tuple[date, date]]
    # Records that were skipped or could not be read.
    warnings: List[str]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _ratio(numerator: float, denominator: float) -> Optional[float]:
    return numerator / denominator if denominator else None


def _get(value: Any, *path: str) -> Any:
    """Follow a path of keys through nested mappings, giving None where it breaks."""
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _values(value: Any) -> List[Any]:
    return list(value.values()) if isinstance(value, Mapping) else []


def to_utc(moment: Any, naive_zone: tzinfo = timezone.utc) -> Optional[datetime]:
    """Return a datetime in UTC, or None if the value isn't a datetime.

    MongoDB returns datetimes without a zone. Those are read in naive_zone.
    """
    if not isinstance(moment, datetime):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=naive_zone)
    return moment.astimezone(timezone.utc)


def week_start(day: date) -> date:
    """The Monday of the week that contains day. Weeks are labelled by this date."""
    return day - timedelta(days=day.weekday())


def grade_to_level(grade: Any) -> Optional[int]:
    """Convert a logged grade (level divided by 2) back to the 0/1/2 competency level."""
    if isinstance(grade, bool) or not isinstance(grade, (int, float)):
        return None
    if not 0 <= grade <= 1:
        return None
    return int(round(grade * 2))


def is_follow_up(text: str) -> bool:
    """Whether a tutor message looks like a question.

    This is a heuristic. It is checked against hand-marked messages before the report goes out.
    """
    return "?" in text or bool(_QUESTION_START.match(text))


def split_sessions(times: Iterable[datetime], gap: timedelta) -> List[List[datetime]]:
    """Group timestamps into sessions. A gap longer than gap starts a new session."""
    sessions: List[List[datetime]] = []
    for moment in sorted(times):
        if sessions and moment - sessions[-1][-1] <= gap:
            sessions[-1].append(moment)
        else:
            sessions.append([moment])
    return sessions


def adjusted_rate(successes: float, opportunities: float, cohort_rate: float, k: float) -> float:
    """Shrink a rate toward the cohort rate, so a rate needs enough attempts to stand out."""
    return (successes + k * cohort_rate) / (opportunities + k)


def percentiles(values: Mapping[str, Optional[float]]) -> Dict[str, Optional[float]]:
    """Each key's position in the cohort from 0 to 100.

    Tied values share the average of the ranks they cover. A key whose value is None has no
    data and gets None, and it isn't counted in the cohort. When only one key has data, or every
    value is tied, the position is 50.
    """
    present = {key: value for key, value in values.items() if value is not None}
    result: Dict[str, Optional[float]] = {key: None for key in values}
    ordered = sorted(present, key=lambda key: present[key])
    count = len(ordered)

    start = 0
    while start < count:
        end = start
        # Rounding stops floating point noise from splitting values that are really equal.
        while end + 1 < count and round(present[ordered[end + 1]], 9) == round(present[ordered[start]], 9):
            end += 1
        average_rank = (start + end) / 2 + 1
        for key in ordered[start:end + 1]:
            result[key] = 50.0 if count == 1 else (average_rank - 1) / (count - 1) * 100
        start = end + 1
    return result


def weighted_score(percentile_by_measure: Mapping[str, Optional[float]], weights: Mapping[str, float]) -> Optional[float]:
    """The weighted mean of a student's percentiles, leaving out measures with no data.

    This is the same calculation as the score formula in the workbook. It is None when no
    measure with a weight has data.
    """
    weighted_total = 0.0
    weight_total = 0.0
    for key, percentile in percentile_by_measure.items():
        if percentile is None:
            continue
        weight = weights.get(key, 0)
        weighted_total += weight * percentile
        weight_total += weight
    return weighted_total / weight_total if weight_total else None


# ---------------------------------------------------------------------------
# Reading the raw records
# ---------------------------------------------------------------------------

def read_tutor_log(conversations: Iterable[Mapping[str, Any]]) -> TutorLog:
    """Pull the student's own messages out of their logged conversations.

    Opening questions are logged with an empty student message and don't count. A turn whose
    reply is an [error] entry doesn't count either, because the student's retry does. A pair
    with two elements is undated.
    """
    messages: List[TutorMessage] = []
    error_turns = 0
    started: Dict[TopicKey, datetime] = {}

    for entry in conversations or ():
        if not isinstance(entry, Mapping):
            continue
        key = (str(entry.get("module")), str(entry.get("topic")))
        began = to_utc(entry.get("timestamp"))
        if began is not None and (key not in started or began < started[key]):
            started[key] = began

        for pair in entry.get("conversation") or ():
            if not isinstance(pair, (list, tuple)) or not pair:
                continue
            student_message = pair[0]
            if not isinstance(student_message, str) or student_message == "":
                continue
            reply = pair[1] if len(pair) > 1 and isinstance(pair[1], str) else ""
            if reply.startswith(ERROR_PREFIX):
                error_turns += 1
                continue
            at = to_utc(pair[2]) if len(pair) > 2 else None
            messages.append(TutorMessage(key[0], key[1], student_message, at))

    return TutorLog(messages, error_turns, started)


def read_submissions(user_id: str, entries: Iterable[Mapping[str, Any]], warnings: List[str]) -> List[Submission]:
    """Read a student's assessor submissions, oldest first.

    A submission without a usable time or grade can't be placed, so it is left out and a
    warning says so.
    """
    submissions: List[Submission] = []
    for entry in entries or ():
        at = to_utc(_get(entry, "timestamp"))
        level = grade_to_level(_get(entry, "grade"))
        if at is None or level is None:
            warnings.append(f"{user_id}: skipped a submission with no usable time or grade ({entry!r:.120})")
            continue
        submissions.append(Submission(str(entry.get("module")), str(entry.get("question")), level, at))
    submissions.sort(key=lambda submission: submission.at)
    return submissions


def _module_sort_key(module: str) -> Tuple[int, str]:
    return (int(module), module) if module.isdigit() else (10**9, module)


def build_attempt_rows(user_id: str, submissions: Sequence[Submission], day_of: Callable[[datetime], date]) -> List[AttemptRow]:
    """Group submissions into one row per question, identified by module and question text."""
    grouped: Dict[Tuple[str, str], List[Submission]] = {}
    for submission in submissions:
        grouped.setdefault((submission.module, submission.question), []).append(submission)

    rows = [
        AttemptRow(
            user_id=user_id,
            module=module,
            question=question,
            levels=tuple(s.level for s in attempts),
            days=tuple(sorted({day_of(s.at) for s in attempts})),
        )
        for (module, question), attempts in grouped.items()
    ]
    # The sort is stable, so questions in a module stay in the order they were first attempted.
    rows.sort(key=lambda row: _module_sort_key(row.module))
    return rows


# ---------------------------------------------------------------------------
# One student
# ---------------------------------------------------------------------------

def summarise_student(
    records: StudentRecords,
    settings: Settings,
    report_date: date,
    warnings: List[str],
) -> Optional[Tuple[StudentMetrics, List[AttemptRow]]]:
    """Work out one student's metrics. Returns None if the student has no interactions."""
    zone = ZoneInfo(settings.timezone)
    progress_zone = ZoneInfo(settings.progress_timezone)

    def day_of(moment: datetime) -> date:
        return moment.astimezone(zone).date()

    log = read_tutor_log(records.conversations)
    submissions = read_submissions(records.user_id, records.submissions, warnings)
    if not log.messages and not submissions:
        return None

    # Tutor activity by topic conversation.
    by_topic: Dict[TopicKey, List[TutorMessage]] = {}
    for message in log.messages:
        by_topic.setdefault((message.module, message.topic), []).append(message)

    topic_days: Dict[TopicKey, Set[date]] = {}
    for (module, topic), messages in by_topic.items():
        days = {day_of(m.at) for m in messages if m.at is not None}
        if any(m.at is None for m in messages):
            # Undated messages leave only two clues to the day. One is when the conversation
            # started and the other is when the topic's competency last changed. Both are
            # lower bounds on the days the student worked on the topic.
            began = log.started.get((module, topic))
            changed = to_utc(_get(records.progress_modules, module, "topics", topic, "last_updated"), progress_zone)
            days |= {day_of(moment) for moment in (began, changed) if moment is not None}
        topic_days[(module, topic)] = days

    tutor_times = sorted(m.at for m in log.messages if m.at is not None)
    assessor_times = [s.at for s in submissions]
    tutor_days = set().union(*topic_days.values())
    assessor_days = {day_of(moment) for moment in assessor_times}
    active_days = tutor_days | assessor_days
    active_weeks = {week_start(day) for day in active_days}

    tutor_sessions = len(split_sessions(tutor_times, settings.session_gap))
    assessor_sessions = len(split_sessions(assessor_times, settings.session_gap))
    sessions = len(split_sessions(tutor_times + assessor_times, settings.session_gap))

    first_active = min(active_days, default=None)
    last_active = max(active_days, default=None)
    days_per_week = None
    if first_active is not None:
        weeks_so_far = max(1, (week_start(report_date) - week_start(first_active)).days // 7 + 1)
        days_per_week = len(active_days) / weeks_so_far

    tutor_by_week: Dict[date, int] = {}
    for moment in tutor_times:
        week = week_start(day_of(moment))
        tutor_by_week[week] = tutor_by_week.get(week, 0) + 1
    assessor_by_week: Dict[date, int] = {}
    for moment in assessor_times:
        week = week_start(day_of(moment))
        assessor_by_week[week] = assessor_by_week.get(week, 0) + 1

    # Assessor questions.
    rows = build_attempt_rows(records.user_id, submissions, day_of)
    first_below_2 = [row for row in rows if row.first_level < 2]
    responded = [row for row in first_below_2 if row.attempts > 1]
    improved = [row for row in responded if max(row.levels[1:]) > row.first_level]

    # Competency levels recorded in the progress database.
    modules = records.progress_modules
    topics_at_2 = questions_at_2 = None
    if modules is not None:
        topics_at_2 = sum(
            1
            for module in _values(modules)
            for topic in _values(_get(module, "topics"))
            if _get(topic, "progress") == 2
        )
        questions_at_2 = sum(
            1
            for module in _values(modules)
            for question in _values(_get(module, "questions"))
            if _get(question, "competency_level") == 2
        )

    dated_interactions = len(tutor_times) + len(assessor_times)
    undated = sum(1 for m in log.messages if m.at is None)

    metrics = StudentMetrics(
        user_id=records.user_id,
        tutor_messages=len(log.messages),
        tutor_undated_messages=undated,
        tutor_error_turns=log.error_turns,
        tutor_sessions=tutor_sessions,
        tutor_active_days=len(tutor_days),
        assessor_submissions=len(submissions),
        assessor_sessions=assessor_sessions,
        assessor_active_days=len(assessor_days),
        sessions=sessions,
        active_days=len(active_days),
        active_weeks=len(active_weeks),
        active_days_per_week=days_per_week,
        first_active=first_active,
        last_active=last_active,
        tutor_timing_incomplete=undated >= settings.incomplete_timing_messages,
        tutor_interactions_per_session=_ratio(len(tutor_times), tutor_sessions),
        assessor_interactions_per_session=_ratio(len(assessor_times), assessor_sessions),
        interactions_per_session=_ratio(dated_interactions, sessions),
        topics_worked=len(by_topic),
        messages_per_topic=_ratio(len(log.messages), len(by_topic)),
        follow_ups=sum(1 for m in log.messages if is_follow_up(m.text)),
        questions_attempted=len(rows),
        questions_retried=sum(1 for row in rows if row.attempts > 1),
        attempts_per_question=_ratio(len(submissions), len(rows)),
        questions_first_below_2=len(first_below_2),
        questions_responded=len(responded),
        questions_improved=len(improved),
        questions_revisited=sum(1 for row in rows if len(row.days) > 1),
        topics_revisited=sum(1 for days in topic_days.values() if len(days) > 1),
        topics_at_level_2=topics_at_2,
        questions_at_level_2=questions_at_2,
        tutor_by_week=tutor_by_week,
        assessor_by_week=assessor_by_week,
    )
    return metrics, rows


# ---------------------------------------------------------------------------
# The cohort
# ---------------------------------------------------------------------------

def score_prize(
    students: Sequence[StudentMetrics],
    measures: Sequence[Measure],
    shrink_k: float,
    weights: Optional[Mapping[str, float]] = None,
    is_eligible: Optional[Callable[[StudentMetrics], bool]] = None,
) -> PrizeTable:
    """Work out raw values, percentiles, scores and ranks for one prize sheet.

    Weights default to each measure's starting weight. Only eligible students are ranked, but
    every student with data on a measure is in that measure's percentiles. Tied students share
    the higher rank, which is the better of the places they cover. Scores of 90, 80, 80 and 70
    rank 1, 2, 2 and 4, as the RANK function in a spreadsheet gives.
    """
    weights = {**{m.key: m.weight for m in measures}, **(weights or {})}
    is_eligible = is_eligible or (lambda student: True)

    cells: Dict[str, Dict[str, MeasureCell]] = {student.user_id: {} for student in students}
    cohort_rates: Dict[str, Optional[float]] = {}

    for measure in measures:
        positions: Dict[str, Optional[float]] = {}
        details: Dict[str, MeasureCell] = {}

        if measure.is_rate:
            counts = {student.user_id: measure.read(student) for student in students}
            counts = {user_id: pair for user_id, pair in counts.items() if pair[1] > 0}
            total_opportunities = sum(opportunities for _, opportunities in counts.values())
            cohort_rate = sum(successes for successes, _ in counts.values()) / total_opportunities if total_opportunities else None
            cohort_rates[measure.key] = cohort_rate
            for user_id, (successes, opportunities) in counts.items():
                adjusted = adjusted_rate(successes, opportunities, cohort_rate, shrink_k)
                positions[user_id] = adjusted
                details[user_id] = MeasureCell(successes / opportunities, adjusted, None, successes, opportunities)
        else:
            for student in students:
                value = measure.read(student)
                if value is not None:
                    positions[student.user_id] = value
                    details[student.user_id] = MeasureCell(value, None, None)

        percentile_of = percentiles(positions)
        for student in students:
            cell = details.get(student.user_id, MeasureCell(None, None, None))
            cells[student.user_id][measure.key] = MeasureCell(
                cell.raw, cell.adjusted, percentile_of.get(student.user_id), cell.successes, cell.opportunities
            )

    scores = {
        student.user_id: weighted_score({m.key: cells[student.user_id][m.key].percentile for m in measures}, weights)
        for student in students
    }
    eligible = {student.user_id: bool(is_eligible(student)) for student in students}
    ranked_scores = [scores[u] for u in scores if eligible[u] and scores[u] is not None]

    rows = [
        PrizeRow(
            user_id=student.user_id,
            cells=cells[student.user_id],
            score=scores[student.user_id],
            eligible=eligible[student.user_id],
            rank=(
                1 + sum(1 for other in ranked_scores if other > scores[student.user_id])
                if eligible[student.user_id] and scores[student.user_id] is not None
                else None
            ),
        )
        for student in students
    ]
    return PrizeTable(tuple(measures), weights, cohort_rates, rows)


def build_report(
    students: Iterable[StudentRecords],
    report_date: date,
    settings: Optional[Settings] = None,
) -> EngagementReport:
    """Build the whole report from every student's records.

    report_date is the Melbourne date of the run. Active days per week counts weeks up to it.
    """
    settings = settings or Settings()
    warnings: List[str] = []
    metrics: List[StudentMetrics] = []
    attempts: List[AttemptRow] = []

    for records in sorted(students, key=lambda r: r.user_id):
        summary = summarise_student(records, settings, report_date, warnings)
        if summary is not None:
            metrics.append(summary[0])
            attempts.extend(summary[1])

    for student in metrics:
        if student.last_active is not None and student.last_active > report_date:
            warnings.append(
                f"{student.user_id}: activity dated {student.last_active}, after the report date "
                f"{report_date}. A progress record written by a machine in another time zone can do this."
            )

    weeks: List[date] = []
    data_range: Optional[Tuple[date, date]] = None
    firsts = [m.first_active for m in metrics if m.first_active is not None]
    lasts = [m.last_active for m in metrics if m.last_active is not None]
    if firsts:
        data_range = (min(firsts), max(lasts))
        week, final_week = week_start(min(firsts)), week_start(max(report_date, max(lasts)))
        while week <= final_week:
            weeks.append(week)
            week += timedelta(days=7)

    prize_1 = score_prize(metrics, PRIZE_1_MEASURES, settings.shrink_k)
    prize_2 = score_prize(
        metrics,
        PRIZE_2_MEASURES,
        settings.shrink_k,
        is_eligible=lambda s: s.active_weeks >= settings.min_weeks and s.interactions >= settings.min_interactions,
    )
    return EngagementReport(settings, report_date, metrics, attempts, weeks, prize_1, prize_2, data_range, warnings)
