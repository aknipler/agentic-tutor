"""Read access to the `modules_live` collection (one document per module)."""
import streamlit as st
from .base import get_mongo_client


def get_modules_data():
    """Retrieve all modules, cached in session state for the run.

    Returns:
        dict: {"modules": [module documents]}. Empty list on error or if the
        collection has not been populated yet.
    """
    if "cached_modules_data" in st.session_state:
        return st.session_state.cached_modules_data

    print("[get_modules_data] Retrieving modules data")  # Only logs on actual DB fetch
    try:
        db_name = st.secrets["MONGODB_DATABASE_NAME"]
        modules_collection = get_mongo_client()[db_name]["modules_live"]
        modules = list(modules_collection.find({}))

        if not modules:
            # An empty collection means setup is incomplete. Say so rather than
            # inventing placeholder modules.
            print(f"[get_modules_data] No documents in {db_name}.modules_live")
            st.error(
                f"No modules found in the database (`{db_name}.modules_live`).\n\n"
                "This usually means the module data hasn't been loaded yet. Load it with:\n\n"
                "`python scripts/load_week_json.py --commit`\n\n"
                "If you expected data to be there, check that `MONGODB_DATABASE_NAME` in "
                "`.streamlit/secrets.toml` points at the right database."
            )
            return {"modules": []}

        modules_data = {"modules": modules}
        st.session_state.cached_modules_data = modules_data
        return modules_data

    except Exception as e:
        if st.session_state.get("debug_mode", False):
            st.error(f"Debug: Error in get_modules_data: {str(e)}")
        else:
            st.error("Error retrieving modules data")
        return {"modules": []}


# Kept as a named alias: callers across the app import one or the other.
get_cached_modules_data = get_modules_data
