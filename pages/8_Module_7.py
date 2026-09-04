from datetime import datetime

import streamlit as st
from utils.cache import get_cached_module
from utils.tutor import render_tutor_interface

# The only thing this page hard-codes: which module it is. Matched against the
# `index` field in modules_live; the title and description come from the data.
MODULE_ID = "7"

# Rollout control: module stays hidden until this date/time.
RELEASE_DATE = datetime(2026, 9, 5, 23, 59)

# Check if user is logged in
if "logged_in" not in st.session_state or not st.session_state.logged_in:
    st.warning("Please login from the Home page to access the module.")
    st.stop()

def main():
    # Load module data. Cached in utils/cache.py and keyed by MODULE_ID - a
    # per-page copy of this lookup collides with the other module pages' copies
    # in Streamlit's cache and serves them each other's module document.
    module_data = get_cached_module(MODULE_ID)
    if not module_data:
        st.info(
            f"Module {MODULE_ID} isn't available yet. It will appear here once the "
            "module has been loaded into the database with "
            "`scripts/load_week_json.py --commit`."
        )
        return

    # Show user ID
    st.sidebar.info(f"Logged in as: {st.session_state.user_id}")

    if datetime.now() <= RELEASE_DATE:
        st.info(f"Module {MODULE_ID} will unlock on {RELEASE_DATE:%B %d, %Y at %I:%M%p}.")
        return

    # Render the tutor interface
    render_tutor_interface(
        module_id=MODULE_ID,
        module_title=module_data.get("title", f"Module {MODULE_ID}"),
        module_description=module_data.get("description", ""),
        topics=module_data.get("topics", []),
        vector_store_id=module_data.get("vector_store_id")
    )

if __name__ == "__main__":
    main()
