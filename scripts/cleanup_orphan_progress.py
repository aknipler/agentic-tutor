"""Remove orphaned module records from user_module_progress.

Progress is stored per user as modules[<module index>]. If a module is removed from
modules_live, or a bug writes progress under a key that never existed, the stale
record lingers and can surface as misleading progress in the UI.

This finds progress records whose module key matches no module in modules_live and
removes them. Real progress is never touched.

Safety: dry run by default. Pass --commit to delete.

Usage:
    .venv/Scripts/python.exe scripts/cleanup_orphan_progress.py            # preview
    .venv/Scripts/python.exe scripts/cleanup_orphan_progress.py --commit   # delete
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from mongodb.connectors.base import get_mongo_client
from utils.modules import module_index

PROGRESS_COLLECTION = "user_module_progress"
MODULES_COLLECTION = "modules_live"


def summarise(module_record: dict) -> str:
    """One-line description of what a module progress record contains."""
    questions = module_record.get("questions", {}) or {}
    topics = module_record.get("topics", {}) or {}
    with_feedback = sum(1 for q in questions.values() if isinstance(q, dict) and q.get("feedback"))
    return (f"{len(questions)} question record(s) "
            f"({with_feedback} with feedback), {len(topics)} topic record(s)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--commit", action="store_true", help="Actually delete the orphaned records.")
    args = parser.parse_args()

    db_name = st.secrets["MONGODB_DATABASE_NAME"]
    db = get_mongo_client()[db_name]

    valid_keys = {
        str(idx) for idx in (module_index(m) for m in db[MODULES_COLLECTION].find({})) if idx is not None
    }
    if not valid_keys:
        raise SystemExit(
            f"No modules found in {db_name}.{MODULES_COLLECTION}. Refusing to run - "
            "without a module list every progress record would look orphaned."
        )

    mode = "COMMIT" if args.commit else "DRY RUN"
    print(f"[{mode}] database      : {db_name!r}")
    print(f"[{mode}] valid module keys: {sorted(valid_keys, key=int)}")

    orphans_found = 0
    for doc in db[PROGRESS_COLLECTION].find({}):
        user_id = doc.get("user_id")
        modules = doc.get("modules", {}) or {}
        orphan_keys = [key for key in modules if key not in valid_keys]
        if not orphan_keys:
            continue

        print(f"\n  user {user_id!r}")
        for key in sorted(orphan_keys):
            print(f"    orphan modules[{key!r}]: {summarise(modules[key])}")
        kept = sorted(set(modules) - set(orphan_keys), key=lambda k: (not k.isdigit(), k))
        print(f"    keeping: {kept}")
        orphans_found += len(orphan_keys)

        if args.commit:
            db[PROGRESS_COLLECTION].update_one(
                {"_id": doc["_id"]},
                {"$unset": {f"modules.{key}": "" for key in orphan_keys}},
            )
            print(f"    [COMMIT] removed {len(orphan_keys)} orphaned module record(s)")

    if not orphans_found:
        print("\nNo orphaned module records found - nothing to do.")
        return

    if not args.commit:
        print(f"\nDry run complete. {orphans_found} orphaned record(s) would be removed. "
              "Re-run with --commit to delete them.")
    else:
        print(f"\n[COMMIT] Done. Removed {orphans_found} orphaned module record(s).")


if __name__ == "__main__":
    main()
