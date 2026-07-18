import streamlit as st
from utils.cache import get_cached_modules_data
from utils.modules import find_module_by_index
from utils.tutor import render_tutor_interface

# The only thing this page hard-codes: which module it is. Matched against the
# `index` field in modules_live; the title and description come from the data.
MODULE_ID = "3"

# Check if user is logged in
if "logged_in" not in st.session_state or not st.session_state.logged_in:
    st.warning("Please login from the Home page to access the module.")
    st.stop()

# Load module data
@st.cache_data(ttl=10)
def load_module_data():
    """Load this module's document from the cached modules data"""
    try:
        return find_module_by_index(get_cached_modules_data(), MODULE_ID)
    except Exception as e:
        st.error(f"Error loading module data: {str(e)}")
        return None

def main():
    # Load module data
    module_data = load_module_data()
    if not module_data:
        st.info(
            f"Module {MODULE_ID} isn't available yet. It will appear here once the "
            "module has been loaded into the database with "
            "`scripts/load_week_json.py --commit`."
        )
        return

    # Show user ID
    st.sidebar.info(f"Logged in as: {st.session_state.user_id}")

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
