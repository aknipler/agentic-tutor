import streamlit as st
from mongodb.connectors import get_modules_data
from utils.tutor import render_tutor_interface

# Check if user is logged in
if "logged_in" not in st.session_state or not st.session_state.logged_in:
    st.warning("Please login from the Home page to access the module.")
    st.stop()

# Load module data
@st.cache_data(ttl=10)
def load_module_data():
    """Load module information from MongoDB"""
    try:
        data = get_modules_data()
        if "modules" in data and isinstance(data["modules"], list):
            # Find the module with the specific ID
            target_title = "Introduction to Chemical Engineering"
            for module in data["modules"]:
                if module.get("title") == target_title:
                    return module
        return None
    except Exception as e:
        st.error(f"Error loading module data: {str(e)}")
        return None

def main():
    # Load module data
    module_data = load_module_data()
    if not module_data:
        st.error("Module data not found. Please try again later.")
        return
    
    # Show user ID
    st.sidebar.info(f"Logged in as: {st.session_state.user_id}")
    
    # Render the tutor interface
    render_tutor_interface(
        module_id="1",
        module_title=module_data.get("title", "Introduction to Chemical Engineering"),
        module_description=module_data.get("description", ""),
        topics=module_data.get("topics", []),
        file_id=st.session_state.get("module_1_file_id")
    )

if __name__ == "__main__":
    main() 