import streamlit as st

def main():
    """Main entry point for the assessor module"""
    # Import here to avoid circular imports
    from .data import load_module_data, get_module_by_title
    from .ui import render_sidebar, render_module_selector, render_questions_paginated
    from .utils import convert_questions_to_dict
    
    # Check if user is logged in
    if "logged_in" not in st.session_state or not st.session_state.logged_in:
        st.warning("Please login from the Home page to access the assessor.")
        st.markdown("### [Return to Home Page](/)")
        st.stop()
    
    st.title("Tutorial Questions")
    
    # Get user ID from session state
    user_id = st.session_state.get("user_id", "user123")
    
    # Load module data
    modules = load_module_data()
    if not modules:
        st.error("No modules data available. Please try again later.")
        return
    
    # Check for preselected module from session state
    preselected_module_id = st.session_state.get("selected_module_id")
    preselected_question_id = st.session_state.get("selected_question_id")
    
    # Get the module title if we have a preselected module. Match on the module's
    # own `index`, not its position in the list.
    preselected_module_title = None
    if preselected_module_id:
        for module in modules:
            if str(module.get("index")) == str(preselected_module_id):
                preselected_module_title = module.get("title")
                break
    
    # Render sidebar with user info
    render_sidebar(user_id)
    
    # Render module selector with preselection if available
    selected_module_title = render_module_selector(modules, default=preselected_module_title)
    
    # Clear the session state values after using them
    if "selected_module_id" in st.session_state:
        del st.session_state.selected_module_id
    if "selected_question_id" in st.session_state:
        del st.session_state.selected_question_id
    
    # Get the selected module's data
    selected_module_data = get_module_by_title(modules, selected_module_title)
    if not selected_module_data:
        st.error("Selected module data not found.")
        return
    
    # Get tutorial questions
    tutorial_questions = convert_questions_to_dict(selected_module_data.get("tutorial_questions", {}))
    if not tutorial_questions:
        st.info("No tutorial questions available for this module.")
        return
    
    # Get module ID. This MUST be the module's own 1-based `index`, which is what
    # user_module_progress is keyed by. Using the list position (0-based) instead
    # made attempt counts and assessment results land in two different module
    # records - see the compensating "+1" hacks this replaced.
    module_id = str(selected_module_data.get("index", ""))
    if not module_id:
        st.error("Selected module has no `index` field; cannot record progress against it.")
        return
    
    # Initialize question_page in session state if not exists
    if "question_page" not in st.session_state:
        st.session_state.question_page = 1
    
    # If we have a preselected question, set the page to show that question
    if preselected_question_id and preselected_question_id in tutorial_questions:
        # Find the page number for the preselected question
        questions_list = list(tutorial_questions.items())
        question_index = next((i for i, (q_id, _) in enumerate(questions_list) if q_id == preselected_question_id), -1)
        if question_index >= 0:
            st.session_state.question_page = (question_index // 5) + 1  # Assuming 5 questions per page
    
    # Render questions with pagination
    render_questions_paginated(tutorial_questions, user_id, module_id) 