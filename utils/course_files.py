"""Work out which module a course-material file belongs to, from its name.

Shared by `scripts/load_week_json.py` (module definitions) and
`scripts/setup_vector_stores.py` (lecture material), so both agree on what
"module 4" means. Nothing here reads a title: the module number is taken from a
marker at the *start* of a file or folder name, which is the one convention the
source material has to follow.

Recognised markers (case-insensitive, leading zeros and `_`/`-`/space separators
allowed, so `L04`, `Lecture_4`, `week-04` and `W4` are all module 4):

    L, Lec, Lecture          "L01a Quality Reliability v10.pdf"
    Module, Mod, M           "Module 2 - Inspections.docx"
    Week, Wk, W              "week_3_assessor_questions.json"
    Topic, Unit, Chapter, Ch "Topic 5 notes.md"

Anchored at the start so a trailing version tag ("v10") or subject code
("MCEN90059") can never be read as a module number.

A file whose own name carries no marker inherits one from the nearest folder
that does, so material can also be organised as `week_04/slides.pdf`.

Pure functions, no Streamlit or database, so they can be tested directly.
"""
import re
from pathlib import Path
from typing import Optional

_PREFIXES = r"(?:lecture|lec|l|module|mod|m|week|wk|w|topic|unit|chapter|ch)"
_INDEX_PATTERN = re.compile(rf"^{_PREFIXES}[\s_-]*0*(\d+)", re.IGNORECASE)

# Names that suggest a file holds worked answers. These must never reach a vector
# store: the tutor retrieves from it and would hand students the model answers.
# The week_*.json module files are kept out by suffix; this catches the same
# content arriving in another format, e.g. "Tutorial 3 Solutions.pdf".
_ANSWER_PATTERN = re.compile(r"solution|answer|marking|rubric", re.IGNORECASE)


def infer_module_index(name: str) -> Optional[int]:
    """Module index from a single file or folder name, or None if it has no marker."""
    match = _INDEX_PATTERN.match(name)
    return int(match.group(1)) if match else None


def module_index_for_path(path: Path, root: Path) -> Optional[int]:
    """Module index for a file under `root`: its own name first, then its folders'.

    Folders are checked nearest-first and never above `root`, so the name of the
    directory holding the whole collection can't assign every file to one module.
    """
    index = infer_module_index(path.name)
    if index is not None:
        return index

    try:
        folders = path.parent.relative_to(root).parts
    except ValueError:
        return None
    for folder in reversed(folders):
        index = infer_module_index(folder)
        if index is not None:
            return index
    return None


def looks_like_answers(path: Path) -> bool:
    """True if a file's name suggests it contains answers or marking material."""
    return bool(_ANSWER_PATTERN.search(path.name))
