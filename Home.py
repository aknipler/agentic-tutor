import streamlit as st
from mongodb.connectors import verify_user_login, get_or_create_default_users
from utils.cache import get_cached_modules_data

def initialize_session():
    """Initialize session state with required data"""
    if "cached_modules_data" not in st.session_state:
        # Pre-fetch modules data at session start
        get_cached_modules_data()

# Initialize session
initialize_session()

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
    
    st.info(f"You are logged in with code: {st.session_state.user_id}")
    
    # New content sections
    st.markdown("""

    ## How to Use This Learning Assistant

    ### For General Learning
    - Use the sidebar menu to navigate to different modules
    - Each module has its own dedicated page with the AI tutor

    ### For Topic Assessment
    - Click on any specific topic to test your knowledge with the assessor
    - The assessor will evaluate your understanding and provide feedback

    ### Tutorial Questions
    - Each module includes tutorial questions to test your understanding
    - Complete these to solidify your knowledge and practice for the exam
    - For quantitative questions, take a photo of your workings and upload them to the assessor. When solving these questions, try to be as clear as possible in your steps, showing the formulas you are using and the units (e.g, if you use Pa or kPa in your ideal gas equation). Also, separate your units from your numbers, for example, writing L (for litres) very close to your answer, the OCR technology and AI assessor could confuse this with a 1 - so instead of reading V = 40 L it reads V = 401.

    The assessor also has a flag icon if you believe your answer is correct and it has not given you full understanding or if you believe its feedback is not valid. This is also provided in the AI tutor bot. This will help to refine this model, so it works better each time a student uses it.

    ## Progress Tracking
    - ✅ = Completed
    - 🟠 = In Progress
    - 🔴 = Not Started
                
    ## Motivation for Using this Learning Assistant

    ### GPT Knowledge Enhancement
    Companies are already starting to develop and integrate GPTs into their workforce. These models are set up very similar to this Learning Assistant, in that they are closed off to the internet so that confidential internal documents and data are not being shared outside of the company. By practicing with this Learning Assistant, you are developing a skill that you can bring to the workforce and be more proficient than people who have been working for many years. By utilising GPT models effectively you will be able to enhance your efficiency in workflows and be more useful as graduates.

    ### OCR Technology Development
    This Learning Assistant enables you to handwrite answers to the tute questions and upload a photo. The OCR technology then has the capability of reading these files and transforming them into text which can be analysed by the AI/ GPT assessor. The applications of this technology are limitless. For example, a normal processing plant can have hundreds of different P&ID's which can be very detailed and complex. The OCR technology could be utilised to analyse and assess these P&ID and provide feedback to engineers, greatly improving their workflow on sometimes monotonous/ strenuous tasks (reading over hundreds if not thousands of P&ID's). This would help free up a lot of the work capacity for engineers and allow them to focus more on the critical thinking side of engineering (making the job more enjoyable!).

    ### Practice for Exams
    As you approach your first round of chemical engineering exams, the questions set by subject coordinators like Chris are often novel problems (which you haven't come across) used to assess your critical thinking, rather than your ability to memorise formulas and answers to tute questions. This Learning Assistant and Assessor is set up in a way that you can improve your critical thinking and helps you break down problems well and answer them clearly.

    It can also be hard to mark yourself honestly when you complete practice questions, the assessor allows you to get feedback on how you are approaching questions and your level of understanding of each topic - giving you more confidence as you approach the exam.
    """)
    
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

