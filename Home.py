import streamlit as st
from mongodb.connector import verify_user_login, get_or_create_default_users

# Initialize session state
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    
if "user_id" not in st.session_state:
    st.session_state.user_id = None

# Title and introduction
st.title("Welcome to the FunCE Bot Learning Assistant!")

# Create default users if not already created
default_codes = get_or_create_default_users()

# Login form
with st.form("login_form"):
    login_code = st.text_input("Enter your login code:", help="Enter your assigned login code to access the system")
    
    submitted = st.form_submit_button("Login")
    
    if submitted:
        if login_code:
            # Verify login code
            if verify_user_login(login_code):
                st.session_state.logged_in = True
                st.session_state.user_id = login_code
                st.success(f"Login successful! Welcome to FunCE Bot.")
                st.rerun()
            else:
                st.error("Invalid login code. Please try again.")
        else:
            st.warning("Please enter a login code.")

# Only show content if logged in
if st.session_state.logged_in:
    st.markdown('## Instructions')
    st.markdown("""
    Welcome to FunCE Bot Learning Assistant, where you can:
    * Check your **Progress** on various modules
    * Receive **Tutoring** on chemical engineering concepts
    * Test your knowledge with the **Assessor**
    * Chat with **AI Chris** for help with any chemical engineering questions
    
    Use the navigation menu on the left to access these features.
    """)
    
    st.info(f"You are logged in with code: {st.session_state.user_id}")
    
    # Logout button
    if st.button("Logout"):
        st.session_state.logged_in = False
        st.session_state.user_id = None
        st.rerun()
else:
    st.markdown("""
    Please login with your assigned code to access the FunCE Bot Learning Assistant. 
    If you don't have a login code, please contact your instructor.
    """)

