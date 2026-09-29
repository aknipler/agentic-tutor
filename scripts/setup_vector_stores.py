"""Create one OpenAI vector store per module and link it into modules_live.

The tutor passes a module's stored `vector_store_id` straight into its `file_search`
tool, so a module whose id is a placeholder (or missing) will fail on every message.
Run this once per module before students use it.

For each module found in `modules_live` it:
  1. gathers that module's source files from knowledge/MCEN_resources_extracted/
  2. creates an OpenAI vector store named after the module
  3. uploads the files and waits for indexing to finish
  4. writes the real vector store id back to the module document

Which file belongs to which module is *derived from the filename*, not hard-coded:
`L01a ....pdf` and `Module 1 - ....docx` both resolve to module index 1, and a file
with no number of its own takes it from its folder (`week_04/slides.pdf`). The rules
live in utils/course_files.py, shared with load_week_json.py. Dropping a new week's
files into the directory is therefore all that is needed to extend this. Files that
can't be placed are listed rather than silently skipped.

Modules are matched on `index` (see utils/modules.py) - never on title.

Files whose names look like answers ("Tutorial 3 Solutions.pdf", "marking guide")
are left out unless --include-answer-files is passed: the tutor retrieves from these
stores and would hand the answers to students.

IMPORTANT: only files under --data-dir (default knowledge/MCEN_resources_extracted/)
are considered.

Safety: creating stores and uploading files bills your OpenAI account and is not
undone by re-running. Runs as a DRY RUN by default; pass --commit to act.

Usage:
    .venv/Scripts/python.exe scripts/setup_vector_stores.py             # preview
    .venv/Scripts/python.exe scripts/setup_vector_stores.py --commit    # do it
    .venv/Scripts/python.exe scripts/setup_vector_stores.py --commit --force
"""

import argparse
import os
import sys
from pathlib import Path

# Make project packages importable when run as `python scripts/setup_vector_stores.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
from openai import OpenAI

from mongodb.connectors.base import get_mongo_client
from utils.course_files import looks_like_answers, module_index_for_path
from utils.modules import module_index, sort_modules_by_index

DATA_DIR = Path(__file__).resolve().parent.parent / "knowledge" / "MCEN_resources_extracted"
COLLECTION = "modules_live"
# Deliberately excludes .json: the week_*_assessor_questions.json files in this
# same directory carry `expected_answer` for every tutorial question. Indexing
# them would let the tutor retrieve and hand students the model answers.
# Everything else here is a format OpenAI's file_search can index.
SOURCE_SUFFIXES = {".pdf", ".docx", ".doc", ".pptx", ".txt", ".md", ".html", ".tex"}


def collect_source_files(data_dir: Path, include_answer_files: bool = False):
    """Sort every file under data_dir into its module.

    Returns (grouped, unplaced, answers): {index: [paths]}, files of an indexable
    type with no module number, and files held back because their names look like
    answers. Searches subfolders, so material can be organised per week.
    """
    grouped, unplaced, answers = {}, [], []
    for path in sorted(p for p in data_dir.rglob("*") if p.is_file()):
        if path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        if looks_like_answers(path) and not include_answer_files:
            answers.append(path)
            continue
        index = module_index_for_path(path, data_dir)
        if index is None:
            unplaced.append(path)
            continue
        grouped.setdefault(index, []).append(path)
    return grouped, unplaced, answers


def store_exists(client: OpenAI, vector_store_id: str) -> bool:
    """True if this id refers to a vector store that actually exists on OpenAI.

    Placeholder ids can look plausible, so ask the API rather than pattern-matching.
    """
    if not vector_store_id:
        return False
    try:
        client.vector_stores.retrieve(vector_store_id)
        return True
    except Exception:
        return False


def get_openai_client() -> OpenAI:
    """Build an OpenAI client, preferring the OS env var (as admin.py does)."""
    api_key = os.getenv("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit(
            "No OpenAI API key found. Set the OPENAI_API_KEY environment variable "
            "or add it to .streamlit/secrets.toml."
        )
    return OpenAI(api_key=api_key)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--commit", action="store_true",
                        help="Actually create stores, upload files and update the database.")
    parser.add_argument("--force", action="store_true",
                        help="Rebuild a store even if the module already links to a real one.")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR,
                        help=f"Directory holding the module source files (default: {DATA_DIR}).")
    parser.add_argument("--include-answer-files", action="store_true",
                        help="Upload files whose names look like solutions/answers/marking guides too.")
    parser.add_argument("--name-prefix", default=None,
                        help="Prefix for new store names in the OpenAI dashboard (default: the database name).")
    args = parser.parse_args()

    db_name = st.secrets["MONGODB_DATABASE_NAME"]
    name_prefix = args.name_prefix if args.name_prefix is not None else db_name

    mongo = get_mongo_client()
    collection = mongo[db_name][COLLECTION]
    modules = sort_modules_by_index(list(collection.find({})))
    if not modules:
        raise SystemExit(
            f"No modules in {db_name}.{COLLECTION}. Run scripts/load_week_json.py --commit first."
        )

    grouped, unplaced, answers = collect_source_files(args.data_dir, args.include_answer_files)
    client = get_openai_client()

    mode = "COMMIT" if args.commit else "DRY RUN"
    print(f"[{mode}] database    : {db_name!r}")
    print(f"[{mode}] source dir  : {args.data_dir}")
    print(f"[{mode}] modules     : {len(modules)}")
    for path in answers:
        print(f"[{mode}] [held back] {path.relative_to(args.data_dir)} - name looks like answers "
              "(--include-answer-files to upload)")
    for path in unplaced:
        print(f"[{mode}] [warn] {path.relative_to(args.data_dir)} - no module number in its name or "
              "folder, not uploaded (see utils/course_files.py)")
    module_indexes = {module_index(module) for module in modules}
    for index in sorted(set(grouped) - module_indexes):
        names = ", ".join(p.name for p in grouped[index])
        print(f"[{mode}] [warn] files for module {index} but no such module is loaded: {names}")

    planned = []
    for module in modules:
        index = module_index(module)
        title = module.get("title", f"Module {index}")
        files = grouped.get(index, [])
        current_id = module.get("vector_store_id", "")
        linked = store_exists(client, current_id)

        print(f"\n  Module {index}: {title}")
        print(f"    current vector_store_id: {current_id or '(none)'}"
              f"{'  [live]' if linked else '  [placeholder/missing]'}")

        if not files:
            print(f"    [skip] no source files found for module {index} in {args.data_dir.name}")
            continue

        for path in files:
            print(f"    file: {path.relative_to(args.data_dir)}  ({path.stat().st_size / 1_048_576:.1f} MB)")

        if linked and not args.force:
            print("    [skip] already linked to a live store (use --force to rebuild)")
            continue

        planned.append((module, index, title, files))

    if not planned:
        print("\nNothing to do.")
        return

    print(f"\n[{mode}] will build {len(planned)} vector store(s).")
    if not args.commit:
        print("Dry run complete - no stores created, nothing uploaded or written.")
        print("Re-run with --commit to proceed.")
        return

    for module, index, title, files in planned:
        store_name = f"{name_prefix} {title}".strip()
        print(f"\n[COMMIT] Creating vector store {store_name!r} ...")
        store = client.vector_stores.create(
            name=store_name,
            metadata={"created_by": "setup_vector_stores.py", "module_index": str(index)},
        )
        print(f"[COMMIT]   id={store.id}")

        print(f"[COMMIT]   uploading {len(files)} file(s) and waiting for indexing ...")
        handles = [open(path, "rb") for path in files]
        try:
            batch = client.vector_stores.file_batches.upload_and_poll(
                vector_store_id=store.id, files=handles
            )
        finally:
            for handle in handles:
                handle.close()

        counts = getattr(batch, "file_counts", None)
        print(f"[COMMIT]   batch status={batch.status} counts={counts}")
        if batch.status != "completed":
            print(f"[COMMIT]   [warn] indexing did not complete cleanly; not linking module {index}.")
            continue

        result = collection.update_one(
            {"index": index}, {"$set": {"vector_store_id": store.id}}
        )
        print(f"[COMMIT]   linked module {index} "
              f"(matched={result.matched_count}, modified={result.modified_count})")

    print("\n[COMMIT] Done. Restart the app (or clear its cache) to pick up the new ids.")


if __name__ == "__main__":
    main()
