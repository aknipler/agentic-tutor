"""Load week_*_assessor_questions.json files into the modules_live collection.

Each source file is one module, supplied as JSON or Mongo Extended JSON. On the
way in:

  1. Extended JSON wrappers ({"$oid": ...}, {"$numberInt": ...}) are parsed with
     bson.json_util, so they become real types rather than literal subdocuments.
     Plain JSON parses the same way.
  2. `index` is set to the module number in the *filename* ("week_10_..." -> 10,
     see utils/course_files.py), the same rule setup_vector_stores.py uses to pick
     each module's lecture files. The app keys everything off it: module pages use
     it to find their module, and user progress is stored under str(index). A
     source `index` field, if present, is only cross-checked - the lecturers'
     files number from 0 - and a file with no number in its name falls back to it.
     Deriving it from the filename means a missing week leaves a gap instead of
     silently shifting every later module (and its students' progress) down one.
  3. The source `_id` is dropped so Mongo assigns its own. Any other field the app
     doesn't read is dropped too, and reported, so a new source format can't lose
     data without anyone noticing.

Every file is validated before anything is written, and the load refuses to run
with errors: a topic name containing "." (topic progress is stored at
`modules.<index>.topics.<name>`, so the dot would split the path), duplicate topic
names or module numbers, and questions with no `question` or `expected_answer`.

The dry run also diffs against what is live, because students' progress is keyed
by topic *name* and by question *position*: it lists topics that would disappear
(with how many students have progress on each) and questions that would move.

A module's `vector_store_id` is taken from the live database whenever one is
there. setup_vector_stores.py writes real ids straight to Mongo and never back to
these files, which carry lecturer placeholders ("vs_week9_reliability") or
nothing - letting the file win would unlink every built module on each reload.
The file's value is only used for a module the database has no id for.

Per-topic `learning_outcomes` are merged in from knowledge/learning_outcomes.json.
That file is keyed by lecture number and topic name, but topic names there don't
always match the wording in the week_*.json topics (e.g. "Process capability" vs.
"Process Potential and Capability") - both files are built by hand from the same
lecture material in the same order, so topics are matched positionally within each
lecture. Lecture number == the module's `index`. Positional matching is only safe
when both lists are the same length, so a lecture whose topic count differs is
skipped with a warning rather than attached one topic out. The field is optional.

Safety: this replaces the whole modules_live collection, so it runs as a DRY RUN
by default. Pass --commit to write. The new documents are written to a staging
collection and renamed over modules_live in one step, so a failed write leaves
the live modules untouched rather than empty.

Usage:
    .venv/Scripts/python.exe scripts/load_week_json.py            # preview
    .venv/Scripts/python.exe scripts/load_week_json.py --commit   # load
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

# Make project packages importable when run as `python scripts/load_week_json.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
from bson import json_util

from mongodb.connectors.base import get_mongo_client
from utils.course_files import infer_module_index

# Fields we keep, in the order the rest of the codebase writes them. `description`
# is optional; module pages pass it to the tutor when present.
_KEEP_FIELDS = ("title", "description", "topics", "tutorial_questions", "vector_store_id", "index")
# Source fields that are expected and deliberately not kept.
_DROPPED_QUIETLY = {"_id"}

DATA_DIR = Path(__file__).resolve().parent.parent / "knowledge" / "MCEN_resources_extracted"
FILE_GLOB = "week_*_assessor_questions.json"
COLLECTION = "modules_live"
STAGING_COLLECTION = f"{COLLECTION}__staging"
PROGRESS_COLLECTION = "user_module_progress"
LEARNING_OUTCOMES_PATH = Path(__file__).resolve().parent.parent / "knowledge" / "learning_outcomes.json"


def load_learning_outcomes(path: Path) -> dict:
    """Load learning_outcomes.json into {lecture_number: [outcomes_list, ...]}.

    The per-lecture outcomes are kept as a plain list, in the same order as the
    file's `topics` dict, so callers can match them positionally against a
    module's `topics` array.
    """
    if not path.exists():
        return {}

    lectures = json.loads(path.read_text(encoding="utf-8"))
    by_lecture = {}
    for lecture in lectures:
        topics = lecture.get("topics", {})
        by_lecture[lecture["lecture"]] = [
            data.get("learning_outcomes", []) for data in topics.values()
        ]
    return by_lecture


def load_source_docs(data_dir: Path, file_glob: str):
    """Read and parse every file matching `file_glob` in data_dir.

    Returns a list of (path, parsed_doc) tuples in module order (week_2 before
    week_10). A file that doesn't parse stops the run: loading the rest would
    silently drop a module.
    """
    files = sorted(
        data_dir.glob(file_glob),
        key=lambda p: (infer_module_index(p.name) is None, infer_module_index(p.name) or 0, p.name),
    )
    if not files:
        raise SystemExit(f"No files matching {file_glob!r} found in {data_dir}")

    parsed = []
    for path in files:
        try:
            # json_util.loads resolves $oid -> ObjectId and $numberInt -> int.
            doc = json_util.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            raise SystemExit(f"Could not parse {path.name}: {e}")
        if not isinstance(doc, dict):
            raise SystemExit(f"{path.name} holds a {type(doc).__name__}, expected one module object.")
        parsed.append((path, doc))
    return parsed


def resolve_index(path: Path, doc: dict):
    """Return (index, errors, notes) for one source file. See module docstring, step 2."""
    from_name = infer_module_index(path.name)
    raw = doc.get("index")
    try:
        raw = int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None, [f"`index` field {raw!r} is not a number"], []

    if from_name is None:
        if raw is None:
            return None, ["no module number in the filename and no `index` field"], []
        return raw + 1, [], [f"no module number in the filename - using `index` field {raw} (+1, 0-based)"]

    if raw is None or raw == from_name - 1:
        return from_name, [], []
    if raw == from_name:
        return from_name, [], [f"`index` field is {raw}, i.e. already 1-based - fine, the filename decides"]
    return None, [
        f"filename says module {from_name} but the `index` field is {raw} "
        f"(expected {from_name - 1}, 0-based). Fix whichever is wrong."
    ], []


def question_list(doc: dict) -> list:
    """`tutorial_questions` as a list, whether stored as a list or a dict."""
    questions = doc.get("tutorial_questions") or []
    return list(questions.values()) if isinstance(questions, dict) else list(questions)


def validate(doc: dict):
    """Return (errors, warnings) for one module document's content."""
    errors, warnings = [], []

    title = doc.get("title")
    if not isinstance(title, str) or not title.strip():
        errors.append("missing `title`")

    topics = doc.get("topics")
    if not isinstance(topics, list) or not topics:
        errors.append("`topics` must be a non-empty list")
        topics = []
    names = []
    for i, topic in enumerate(topics, start=1):
        name = topic.get("name") if isinstance(topic, dict) else None
        if not isinstance(name, str) or not name.strip():
            errors.append(f"topic {i} has no `name`")
            continue
        names.append(name)
        if "." in name or name.startswith("$"):
            errors.append(f"topic name {name!r} contains '.' or starts with '$' - "
                          "it can't be used as a progress key in Mongo")
        if name != name.strip():
            warnings.append(f"topic name {name!r} has leading/trailing whitespace")
        if not topic.get("description"):
            warnings.append(f"topic {name!r} has no `description` - the tutor builds its opener from it")
    for name, count in Counter(n.strip().casefold() for n in names).items():
        if count > 1:
            errors.append(f"topic name {name!r} appears {count} times - progress is keyed by name")

    raw_questions = doc.get("tutorial_questions")
    if not isinstance(raw_questions, (list, dict)):
        errors.append("`tutorial_questions` must be a list or dict")
    questions = question_list(doc) if isinstance(raw_questions, (list, dict)) else []
    if not questions:
        warnings.append("no tutorial questions")
    for i, question in enumerate(questions, start=1):
        label = question.get("question_id", f"#{i}") if isinstance(question, dict) else f"#{i}"
        if not isinstance(question, dict) or not question.get("question"):
            errors.append(f"question {label} has no `question` text")
        elif not question.get("expected_answer"):
            errors.append(f"question {label} has no `expected_answer` - the assessor grades against it")
    ids = [q.get("question_id") for q in questions if isinstance(q, dict) and q.get("question_id")]
    for qid, count in Counter(ids).items():
        if count > 1:
            warnings.append(f"question_id {qid!r} appears {count} times")

    dropped = sorted(set(doc) - set(_KEEP_FIELDS) - _DROPPED_QUIETLY)
    if dropped:
        warnings.append(f"fields not loaded (the app doesn't read them): {', '.join(dropped)}")

    return errors, warnings


def load_live_modules(collection) -> dict:
    """Read {index: module document} currently live in modules_live. Read-only."""
    live = {}
    for doc in collection.find({}):
        try:
            live[int(doc["index"])] = doc
        except (KeyError, TypeError, ValueError):
            continue
    return live


def transform(doc: dict, index: int, learning_outcomes_by_lecture: dict, live: dict):
    """Build a clean modules_live document. Returns (document, notes).

    See the module docstring for the vector_store_id and learning_outcomes rules.
    """
    notes = []
    out = {field: doc[field] for field in _KEEP_FIELDS if field in doc}
    out["index"] = index  # plain int, 1-based (app keys progress by str(index))

    source_vsid = doc.get("vector_store_id") or ""
    live_vsid = (live.get(index) or {}).get("vector_store_id") or ""
    if live_vsid:
        out["vector_store_id"] = live_vsid
        if source_vsid and source_vsid != live_vsid:
            notes.append(f"vector_store_id: keeping live {live_vsid!r} (file has {source_vsid!r})")
        else:
            notes.append(f"vector_store_id: keeping live {live_vsid!r}")
    else:
        out["vector_store_id"] = source_vsid
        notes.append(f"vector_store_id: {source_vsid or '(none)'} from file - "
                     "run setup_vector_stores.py to build a real store")

    topics = out.get("topics", [])
    outcomes = learning_outcomes_by_lecture.get(index, [])
    if outcomes and len(outcomes) != len(topics):
        notes.append(f"[warn] learning outcomes: lecture {index} has {len(outcomes)} topics but the "
                     f"module has {len(topics)} - not merged (they're matched by position)")
        outcomes = []
    merged_topics = []
    for i, topic in enumerate(topics):
        topic = dict(topic)
        if i < len(outcomes) and outcomes[i]:
            topic["learning_outcomes"] = outcomes[i]
        merged_topics.append(topic)
    out["topics"] = merged_topics

    return out, notes


def diff_against_live(new: dict, live_doc: dict, progress) -> list:
    """Warnings for changes that would detach students' existing progress."""
    warnings = []
    index = new["index"]

    new_names = {t.get("name") for t in new.get("topics", [])}
    for topic in live_doc.get("topics", []):
        name = topic.get("name")
        if not name or name in new_names:
            continue
        students = (
            progress.count_documents({f"modules.{index}.topics.{name}": {"$exists": True}})
            if "." not in name and not name.startswith("$") else "?"
        )
        warnings.append(f"topic {name!r} is live but not in the file - progress on it is orphaned "
                        f"({students} student record(s) have it). Renamed? Keep the old name.")

    live_ids = [q.get("question_id") for q in question_list(live_doc)]
    new_ids = [q.get("question_id") for q in question_list(new)]
    moved = [i + 1 for i, (a, b) in enumerate(zip(live_ids, new_ids)) if a != b]
    if moved:
        warnings.append(f"questions at position(s) {moved} have changed id - question results are "
                        "stored by position, so students' results now point at different questions")
    if len(new_ids) < len(live_ids):
        warnings.append(f"{len(live_ids) - len(new_ids)} question(s) removed from the end - "
                        "their results are orphaned")
    return warnings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--commit", action="store_true",
                        help="Actually replace modules_live. Without this flag the script is a dry run.")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR,
                        help=f"Directory of module JSON files (default: {DATA_DIR}).")
    parser.add_argument("--glob", default=FILE_GLOB,
                        help=f"Which files in --data-dir are module definitions (default: {FILE_GLOB!r}).")
    parser.add_argument("--learning-outcomes", type=Path, default=LEARNING_OUTCOMES_PATH,
                        help=f"learning_outcomes.json to merge in per topic (default: {LEARNING_OUTCOMES_PATH}).")
    args = parser.parse_args()

    db_name = st.secrets["MONGODB_DATABASE_NAME"]
    db = get_mongo_client()[db_name]
    collection = db[COLLECTION]

    # Read-only, so fetched in both modes: it's what makes the dry-run preview
    # of vector_store_id and of orphaned progress accurate.
    live = load_live_modules(collection)
    learning_outcomes_by_lecture = load_learning_outcomes(args.learning_outcomes)

    mode = "COMMIT" if args.commit else "DRY RUN"
    print(f"[{mode}] target database : {db_name!r}")
    print(f"[{mode}] target collection: {COLLECTION!r} (currently {len(live)} module(s))")
    print(f"[{mode}] source           : {args.data_dir / args.glob}")
    print(f"[{mode}] learning outcomes: {args.learning_outcomes}")

    all_errors = []
    transformed = []
    for path, doc in load_source_docs(args.data_dir, args.glob):
        index, errors, notes = resolve_index(path, doc)
        content_errors, warnings = validate(doc)
        errors += content_errors

        print(f"\n  {path.name}")
        print(f"    module index : {index if index is not None else '?'}")
        print(f"    title        : {doc.get('title')!r}")
        print(f"    topics       : {len(doc.get('topics') or [])}")
        print(f"    questions    : {len(question_list(doc)) if isinstance(doc.get('tutorial_questions'), (list, dict)) else '?'}")

        if not errors:
            new, transform_notes = transform(doc, index, learning_outcomes_by_lecture, live)
            notes += transform_notes
            if index in live:
                warnings += diff_against_live(new, live[index], db[PROGRESS_COLLECTION])
            else:
                notes.append("new module - not currently live")
            with_outcomes = sum(1 for t in new["topics"] if t.get("learning_outcomes"))
            notes.append(f"learning outcomes on {with_outcomes}/{len(new['topics'])} topics")
            transformed.append((path, new))

        for note in notes:
            print(f"    {note}")
        for warning in warnings:
            print(f"    [warn] {warning}")
        for error in errors:
            print(f"    [ERROR] {error}")
        all_errors += [f"{path.name}: {e}" for e in errors]

    for index, count in Counter(new["index"] for _, new in transformed).items():
        if count > 1:
            files = [p.name for p, new in transformed if new["index"] == index]
            all_errors.append(f"module {index} is defined by {count} files: {', '.join(files)}")

    indexes = sorted(new["index"] for _, new in transformed)
    print(f"\n[{mode}] modules to load: {indexes}")
    if indexes:
        gaps = sorted(set(range(1, max(indexes) + 1)) - set(indexes))
        if gaps:
            print(f"[{mode}] [warn] no file for module(s) {gaps} - their pages will show 'not available yet'")
    for index in sorted(set(live) - set(indexes)):
        print(f"[{mode}] [warn] live module {index} ({live[index].get('title')!r}) is not in the source "
              "and will be removed; students' progress for it is orphaned "
              "(scripts/cleanup_orphan_progress.py)")

    if all_errors:
        print(f"\n{len(all_errors)} error(s) - nothing written. Fix these and re-run:")
        for error in all_errors:
            print(f"  - {error}")
        raise SystemExit(1)

    if not args.commit:
        print("\nDry run complete - nothing written. Re-run with --commit to load.")
        return

    documents = [new for _, new in sorted(transformed, key=lambda pair: pair[1]["index"])]
    staging = db[STAGING_COLLECTION]
    staging.drop()
    staging.insert_many(documents)
    # One step, and only once every document is in: a failure before this line
    # leaves modules_live exactly as it was.
    staging.rename(COLLECTION, dropTarget=True)
    print(f"\n[COMMIT] Replaced {db_name}.{COLLECTION}: {len(live)} -> {len(documents)} module(s).")
    print("[COMMIT] Done. Run scripts/setup_vector_stores.py for any module without a real store.")


if __name__ == "__main__":
    main()
