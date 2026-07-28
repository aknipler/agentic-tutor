"""Generate login codes and create matching users + progress records.

Adapted from a sibling project's generate_and_load_identifiers.py to this app's
schema: a user is a `login_code` document in the `users` collection plus a
matching per-module progress document in `user_module_progress`. Every code
gets the same initialized module/topic/question skeleton the app expects -
not just a bare identifier.

The skeleton is identical for every user (it only depends on modules_live,
never on the user), so it's built once from get_cached_modules_data() and
deep-copied per user, then both collections are written with a single
insert_many() each - not a create_user_progress() call per user, which would
mean two find_one existence checks plus two insert_one calls per code (for
120 codes that's ~480 sequential round-trips to Mongo instead of 2).

get_cached_modules_data() returns {"modules": []} without raising if
modules_live hasn't been loaded yet (e.g. the app has never been run) - see
mongodb/connectors/modules.py. Silently proceeding would create every user
with an empty `modules: {}` progress doc that never self-heals, so this
script refuses to run if no modules are found.

Codes are `<prefix><random suffix>`, e.g. --prefix PRQ26D --suffix-length 4
-> PRQ26D7K2M. The prefix is always supplied by the caller, never hardcoded.

Safety: dry run by default. Pass --commit to write. Combine with --wipe to
delete every existing user and progress record first (e.g. resetting for a
new cohort) - --wipe on its own does nothing without --commit.

Usage:
    .venv/Scripts/python.exe scripts/generate_and_load_codes.py --prefix PRQ26D                      # preview 120 codes
    .venv/Scripts/python.exe scripts/generate_and_load_codes.py --prefix PRQ26D --commit              # create them
    .venv/Scripts/python.exe scripts/generate_and_load_codes.py --prefix PRQ26D --wipe --commit       # wipe cohort + recreate
"""

import argparse
import copy
import csv
import random
import string
import sys
from datetime import datetime
from pathlib import Path

# Make the `mongodb` package importable when run as `python scripts/generate_and_load_codes.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from mongodb.connectors.base import get_mongo_client
from mongodb.connectors.modules import get_cached_modules_data

USERS_COLLECTION = "users"
PROGRESS_COLLECTION = "user_module_progress"
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "data" / "user_codes.csv"


def generate_code(prefix: str, suffix_length: int, existing: set) -> str:
    """Generate a random `<prefix><suffix>` code not already in `existing`, and reserve it."""
    alphabet = string.ascii_uppercase + string.digits
    while True:
        suffix = "".join(random.choices(alphabet, k=suffix_length))
        code = f"{prefix}{suffix}"
        if code not in existing:
            existing.add(code)
            return code


def build_progress_template(modules_data: dict) -> dict:
    """Build the `modules` skeleton every new user's progress doc starts with.

    Mirrors the per-user structure create_user_progress() builds in
    mongodb/connectors/user_progress.py, but computed once since it's the
    same for every user - only module/topic/question shape, no user data.
    """
    modules = {}
    for module in modules_data.get("modules", []):
        module_id = str(module.get("index", 0))
        modules[module_id] = {
            "progress": 0,
            "status": "not_started",
            "topics": {
                topic.get("name"): {"progress": 0, "status": "not_started"}
                for topic in module.get("topics", [])
            },
            "questions": {
                str(idx + 1): {
                    "status": "not_started",
                    "attempts": 0,
                    "last_attempt": None,
                    "competency_level": 0,
                    "feedback": "",
                    "response_text": "",
                    "input_image_data": [],
                    "last_assessed": None,
                }
                for idx in range(len(module.get("tutorial_questions", [])))
            },
        }
    return modules


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--prefix", required=True, help="Login code prefix, e.g. PRQ26D.")
    parser.add_argument("--count", type=int, default=120, help="Number of codes to generate (default: 120).")
    parser.add_argument("--suffix-length", type=int, default=4, help="Length of the random suffix (default: 4).")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help=f"CSV path to write codes to (default: {DEFAULT_OUTPUT}).")
    parser.add_argument("--wipe", action="store_true",
                        help="Delete every existing user and progress record first. Requires --commit to take effect.")
    parser.add_argument("--commit", action="store_true",
                        help="Actually write to the database and CSV. Without this flag the script is a dry run.")
    args = parser.parse_args()

    db_name = st.secrets["MONGODB_DATABASE_NAME"]
    mode = "COMMIT" if args.commit else "DRY RUN"

    print(f"[{mode}] database   : {db_name!r}")
    print(f"[{mode}] prefix     : {args.prefix!r}")
    print(f"[{mode}] count      : {args.count}")
    print(f"[{mode}] suffix len : {args.suffix_length}")
    print(f"[{mode}] output csv : {args.output}")
    print(f"[{mode}] wipe first : {args.wipe}")

    modules_data = get_cached_modules_data()
    if not modules_data.get("modules"):
        raise SystemExit(
            f"No modules found in {db_name}.modules_live - refusing to run. "
            "Every new user would get an empty progress skeleton that never self-heals. "
            "Load module data first with: python scripts/load_week_json.py --commit"
        )
    progress_template = build_progress_template(modules_data)
    print(f"[{mode}] modules found : {len(progress_template)}")

    client = get_mongo_client()
    db = client[db_name]

    existing_codes = set()
    if args.wipe:
        users_count = db[USERS_COLLECTION].count_documents({})
        progress_count = db[PROGRESS_COLLECTION].count_documents({})
        print(f"\n[{mode}] would delete {users_count} document(s) from {USERS_COLLECTION!r} "
              f"and {progress_count} document(s) from {PROGRESS_COLLECTION!r}")
        if args.commit:
            db[USERS_COLLECTION].delete_many({})
            db[PROGRESS_COLLECTION].delete_many({})
            print(f"[COMMIT] wiped {users_count} user(s) and {progress_count} progress record(s)")
    else:
        existing_codes = {
            doc["login_code"] for doc in db[USERS_COLLECTION].find({}, {"login_code": 1}) if doc.get("login_code")
        }
        print(f"\n[{mode}] {len(existing_codes)} existing login code(s) will be avoided for uniqueness")

    codes = [generate_code(args.prefix, args.suffix_length, existing_codes) for _ in range(args.count)]
    print(f"\n[{mode}] sample codes: {codes[:5]}{' ...' if len(codes) > 5 else ''}")

    if not args.commit:
        print("\nDry run complete - nothing written. Re-run with --commit to create users and write the CSV.")
        return

    now = datetime.now()
    user_docs = [{"login_code": code, "name": "", "created_at": now} for code in codes]
    progress_docs = [
        {"user_id": code, "created_at": now, "updated_at": now, "modules": copy.deepcopy(progress_template)}
        for code in codes
    ]

    db[USERS_COLLECTION].insert_many(user_docs)
    db[PROGRESS_COLLECTION].insert_many(progress_docs)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Code"])
        writer.writerows([[code] for code in codes])

    print(f"\n[COMMIT] created {len(codes)} user(s) and {len(codes)} progress record(s)")
    print(f"[COMMIT] codes written to {args.output}")


if __name__ == "__main__":
    main()
