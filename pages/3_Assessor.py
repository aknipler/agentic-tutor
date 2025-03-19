import streamlit as st

# Check if user is logged in
if "logged_in" not in st.session_state or not st.session_state.logged_in:
    st.warning("Please login from the Home page to access the assessor.")
    st.stop()

st.title("Assessor - Coming Soon")
st.info("The Assessor functionality is under development and will be available soon!")

# Display user ID
st.sidebar.info(f"Logged in as: {st.session_state.user_id}")
