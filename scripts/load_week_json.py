"""Load week_*_assessor_questions.json files into the modules_live collection.

Each source file is one module, supplied as Mongo Extended JSON. Three things are
normalised on the way in:

  1. Extended JSON wrappers ({"$oid": ...}, {"$numberInt": ...}) are parsed with
     bson.json_util, so they become real types rather than literal subdocuments.
  2. `index` is renumbered to 1-based. The app keys everything off it: module pages
     use it to find their module, and user progress is stored under str(index).
  3. The source `_id` is dropped so Mongo assigns its own.

Per-topic `learning_outcomes` are merged in from knowledge/learning_outcomes.json.
That file is keyed by lecture number and topic name, but topic names there don't
always match the wording in the week_*.json topics (e.g. "Process capability" vs.
"Process Potential and Capability") - both files are built by hand from the same
lecture material in the same order, so topics are matched positionally within each
lecture rather than by name. Lecture number == the module's 1-based `index`. The
field is optional: a topic with no positional match (missing lecture, or fewer
learning-outcome entries than topics) is left without it.

Placeholder `vector_store_id` values and missing per-topic `question` or
`learning_outcomes` fields are left alone (the first is handled by
setup_vector_stores.py, the rest are optional) but all are reported so nothing is
forgotten.

Safety: this wipes and replaces the whole modules_live collection, so it runs as a
DRY RUN by default. Pass --commit to write.

Usage:
    .venv/Scripts/python.exe scripts/load_week_json.py            # preview
    .venv/Scripts/python.exe scripts/load_week_json.py --commit   # load
"""

import argparse
import json
import sys
from pathlib import Path

# Make the `mongodb` package importable when run as `python scripts/load_week_json.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
from bson import json_util

from mongodb.connectors.base import get_mongo_client

# Fields we keep, in the order the rest of the codebase writes them.
_KEEP_FIELDS = ("title", "topics", "tutorial_questions", "vector_store_id", "index")

DATA_DIR = Path(__file__).resolve().parent.parent / "knowledge" / "MCEN_resources_extracted"
FILE_GLOB = "week_*_assessor_questions.json"
COLLECTION = "modules_live"
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


def load_source_docs(data_dir: Path):
    """Read and parse every week_*_assessor_questions.json in data_dir.

    Returns a list of (path, parsed_doc) tuples, sorted by the file's original
    0-based `index` so renumbering is deterministic even if filenames change.
    """
    files = sorted(data_dir.glob(FILE_GLOB))
    if not files:
        raise SystemExit(f"No files matching {FILE_GLOB!r} found in {data_dir}")

    parsed = []
    for path in files:
        # json_util.loads resolves $oid -> ObjectId and $numberInt -> int.
        doc = json_util.loads(path.read_text(encoding="utf-8"))
        parsed.append((path, doc))

    parsed.sort(key=lambda pair: int(pair[1].get("index", 0)))
    return parsed


def load_existing_vector_store_ids(collection) -> dict:
    """Read {index: vector_store_id} currently live in modules_live.

    setup_vector_stores.py and admin.py write real vector store ids straight to
    Mongo; they are never synced back to the source JSON files, so a source file
    can carry a stale empty/placeholder value while the database holds the real
    one (this happened for modules 4-6). Read-only, so safe to call in dry runs.
    """
    return {
        doc["index"]: doc["vector_store_id"]
        for doc in collection.find({}, {"index": 1, "vector_store_id": 1})
        if doc.get("vector_store_id")
    }


def transform(doc: dict, new_index: int, learning_outcomes_by_lecture: dict,
              existing_vector_store_ids: dict) -> dict:
    """Build a clean modules_live document: drop _id, set 1-based int index.

    `learning_outcomes` is merged into each topic positionally (see module
    docstring). Lecture number == new_index. Topics beyond the available
    outcomes list, or lectures with no entry at all, are left untouched -
    the field stays optional.

    A source file with no `vector_store_id` (or an empty one) falls back to
    whatever is already live in the database for this index, rather than
    wiping out a real link that only ever existed in Mongo. A source file that
    does supply one (including a lecturer placeholder for a brand new module)
    always wins - that's the signal to link a fresh module.
    """
    out = {field: doc[field] for field in _KEEP_FIELDS if field in doc}
    out["index"] = new_index  # plain int, 1-based (app keys progress by str(index))

    if not out.get("vector_store_id") and new_index in existing_vector_store_ids:
        out["vector_store_id"] = existing_vector_store_ids[new_index]

    outcomes_for_lecture = learning_outcomes_by_lecture.get(new_index, [])
    topics = out.get("topics", [])
    merged_topics = []
    for i, topic in enumerate(topics):
        topic = dict(topic)
        if i < len(outcomes_for_lecture) and outcomes_for_lecture[i]:
            topic["learning_outcomes"] = outcomes_for_lecture[i]
        merged_topics.append(topic)
    out["topics"] = merged_topics

    return out


def describe(path: Path, doc: dict, transformed: dict) -> None:
    """Print a per-module preview plus any format warnings."""
    topics = doc.get("topics", [])
    questions = doc.get("tutorial_questions", [])
    new_index = transformed["index"]
    print(f"\n  {path.name}")
    print(f"    title            : {doc.get('title')!r}")
    print(f"    index            : {doc.get('index')} (raw) -> {new_index} (1-based)")
    print(f"    topics           : {len(topics)}")
    print(f"    tutorial_questions: {len(questions)}")

    source_vsid = doc.get("vector_store_id", "")
    final_vsid = transformed.get("vector_store_id", "")
    if source_vsid != final_vsid:
        print(f"    vector_store_id  : source has none - preserving live value {final_vsid!r} from the database")
    elif not final_vsid or not final_vsid.startswith("vs_") or "week" in final_vsid:
        # Real OpenAI ids look like vs_abc123...; the lecturer placeholders read
        # vs_week1_probability_reliability_quality.
        print(f"    [warn] vector_store_id looks like a placeholder: {final_vsid!r}")
        print("           -> create a real store in admin.py and relink before use.")

    topics_missing_q = [t.get("name") for t in topics if not t.get("question")]
    if topics_missing_q:
        print(f"    [warn] {len(topics_missing_q)}/{len(topics)} topics have no 'question' field")
        print("           -> tutor topic flow needs this (fixed in utils/tutor/interface.py).")

    topics_missing_lo = [t.get("name") for t in transformed.get("topics", []) if not t.get("learning_outcomes")]
    if topics_missing_lo:
        print(f"    [warn] {len(topics_missing_lo)}/{len(topics)} topics have no 'learning_outcomes'")
        print(f"           -> add lecture {new_index} to {LEARNING_OUTCOMES_PATH.name}, "
              "or leave as-is (field is optional).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--commit", action="store_true",
                        help="Actually wipe and reload modules_live. Without this flag the script is a dry run.")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR,
                        help=f"Directory of week_*_assessor_questions.json files (default: {DATA_DIR}).")
    parser.add_argument("--learning-outcomes", type=Path, default=LEARNING_OUTCOMES_PATH,
                        help=f"learning_outcomes.json to merge in per topic (default: {LEARNING_OUTCOMES_PATH}).")
    args = parser.parse_args()

    db_name = st.secrets["MONGODB_DATABASE_NAME"]
    client = get_mongo_client()
    collection = client[db_name][COLLECTION]

    # Read-only, so fetched in both modes: it's what makes the dry-run preview
    # of vector_store_id accurate instead of just describing the source files.
    existing_vector_store_ids = load_existing_vector_store_ids(collection)

    parsed = load_source_docs(args.data_dir)
    learning_outcomes_by_lecture = load_learning_outcomes(args.learning_outcomes)
    transformed = [
        transform(doc, new_index=i, learning_outcomes_by_lecture=learning_outcomes_by_lecture,
                  existing_vector_store_ids=existing_vector_store_ids)
        for i, (_path, doc) in enumerate(parsed, start=1)
    ]

    mode = "COMMIT" if args.commit else "DRY RUN"
    print(f"[{mode}] target database : {db_name!r}")
    print(f"[{mode}] target collection: {COLLECTION!r}")
    print(f"[{mode}] source directory : {args.data_dir}")
    print(f"[{mode}] learning outcomes: {args.learning_outcomes}")
    print(f"[{mode}] modules to load  : {len(transformed)}")

    for (path, doc), new in zip(parsed, transformed):
        describe(path, doc, new)

    if not args.commit:
        print("\nDry run complete - nothing written. Re-run with --commit to load.")
        return

    existing = collection.count_documents({})
    print(f"\n[COMMIT] {COLLECTION} currently holds {existing} document(s); replacing them.")
    collection.delete_many({})
    result = collection.insert_many(transformed)
    print(f"[COMMIT] Inserted {len(result.inserted_ids)} module document(s) into {db_name}.{COLLECTION}.")
    print("[COMMIT] Done.")


if __name__ == "__main__":
    main()
