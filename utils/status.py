"""Shared rendering of the 0/1/2 competency scale.

Competency is 0/1/2 everywhere - tutor, assessor, prompts and database - and this
is the one place that decides what each level looks like on screen. It used to be
defined once in `assessor/utils.py` and again in `pages/1_Your_Progress.py`, which
meant the progress page and the module pages could disagree about a student's
status while reading the same number.
"""

# Status strings as stored in user_module_progress, indexed by competency level.
STATUS_BY_PROGRESS = ("not_started", "in_progress", "completed")

_EMOJI_BY_STATUS = {
    "not_started": "🔴",
    "in_progress": "🟠",
    "completed": "✅",
}


def get_status_emoji(status: str) -> str:
    """Emoji for a stored status string. Unknown statuses read as not started."""
    return _EMOJI_BY_STATUS.get(status, "🔴")


def get_status_from_progress(progress: int) -> str:
    """Status string for a 0/1/2 competency level."""
    if isinstance(progress, int) and 0 <= progress < len(STATUS_BY_PROGRESS):
        return STATUS_BY_PROGRESS[progress]
    return "not_started"
