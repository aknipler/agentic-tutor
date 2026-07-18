"""Load lecturer week_*_assessor_questions.json files into the modules_live collection.

The lecturers deliver each module as a Mongo Extended JSON document under
`knowledge/MCEN_resources_extracted/`. Those files are close to drop-in
`modules_live` documents but need three fixes before insertion (see docs/HANDOVER.md):

  1. Extended JSON wrappers ({"$oid": ...}, {"$numberInt": ...}) must be parsed
     with bson.json_util, not plain json, or they get stored as literal subdocuments.
  2. `index` is 0-based in the files (0, 1, 2) but the app is 1-based: module pages
     hard-code module_id "1", "2", ...; user_progress keys progress docs by
     str(module["index"]). This script renumbers `index` to 1-based on import.
  3. `_id` is a placeholder $oid; we drop it and let Mongo assign real ones.

It does NOT touch the placeholder `vector_store_id` values or add the missing
per-topic `question` field on purpose (real vector stores are created via admin.py;
the topic `question` KeyError is fixed separately in utils/tutor/interface.py) - but
it warns about both so nothing is silently forgotten.

Safety: this wipes and replaces the whole `modules_live` collection. It runs as a
DRY RUN by default (prints what it would do, touches nothing). Pass --commit to write.

Usage:
    .venv/Scripts/python.exe scripts/load_week_json.py            # dry run / preview
    .venv/Scripts/python.exe scripts/load_week_json.py --commit   # actually load
"""

import argparse
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


def transform(doc: dict, new_index: int) -> dict:
    """Build a clean modules_live document: drop _id, set 1-based int index."""
    out = {field: doc[field] for field in _KEEP_FIELDS if field in doc}
    out["index"] = new_index  # plain int, 1-based (app keys progress by str(index))
    return out


def describe(path: Path, doc: dict, new_index: int) -> None:
    """Print a per-module preview plus any format warnings."""
    topics = doc.get("topics", [])
    questions = doc.get("tutorial_questions", [])
    print(f"\n  {path.name}")
    print(f"    title            : {doc.get('title')!r}")
    print(f"    index            : {doc.get('index')} (raw) -> {new_index} (1-based)")
    print(f"    topics           : {len(topics)}")
    print(f"    tutorial_questions: {len(questions)}")

    vsid = doc.get("vector_store_id", "")
    if not vsid or not vsid.startswith("vs_") or "week" in vsid:
        # Real OpenAI ids look like vs_abc123...; the lecturer placeholders read
        # vs_week1_probability_reliability_quality.
        print(f"    [warn] vector_store_id looks like a placeholder: {vsid!r}")
        print("           -> create a real store in admin.py and relink before use.")

    topics_missing_q = [t.get("name") for t in topics if not t.get("question")]
    if topics_missing_q:
        print(f"    [warn] {len(topics_missing_q)}/{len(topics)} topics have no 'question' field")
        print("           -> tutor topic flow needs this (fixed in utils/tutor/interface.py).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--commit", action="store_true",
                        help="Actually wipe and reload modules_live. Without this flag the script is a dry run.")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR,
                        help=f"Directory of week_*_assessor_questions.json files (default: {DATA_DIR}).")
    args = parser.parse_args()

    db_name = st.secrets["MONGODB_DATABASE_NAME"]
    # Guard against the known FunCE bug (README): never write to the old subject's db.
    if db_name.strip().lower() == "funce_db":
        raise SystemExit(
            "Refusing to run: MONGODB_DATABASE_NAME is 'funce_db' (the old FunCE database, a known bug). "
            "Point .streamlit/secrets.toml at the PRQ database before loading."
        )

    parsed = load_source_docs(args.data_dir)
    transformed = [transform(doc, new_index=i) for i, (_path, doc) in enumerate(parsed, start=1)]

    mode = "COMMIT" if args.commit else "DRY RUN"
    print(f"[{mode}] target database : {db_name!r}")
    print(f"[{mode}] target collection: {COLLECTION!r}")
    print(f"[{mode}] source directory : {args.data_dir}")
    print(f"[{mode}] modules to load  : {len(transformed)}")

    for (path, doc), new in zip(parsed, transformed):
        describe(path, doc, new["index"])

    if not args.commit:
        print("\nDry run complete - nothing written. Re-run with --commit to load.")
        return

    client = get_mongo_client()
    db = client[db_name]
    collection = db[COLLECTION]

    existing = collection.count_documents({})
    print(f"\n[COMMIT] {COLLECTION} currently holds {existing} document(s); replacing them.")
    collection.delete_many({})
    result = collection.insert_many(transformed)
    print(f"[COMMIT] Inserted {len(result.inserted_ids)} module document(s) into {db_name}.{COLLECTION}.")
    print("[COMMIT] Done.")


if __name__ == "__main__":
    main()
