import streamlit as st
from .data import load_module_data, get_module_by_title
from .ui import render_sidebar, render_module_selector, render_question
from .utils import convert_questions_to_dict

def main():
    """Main entry point for the assessor module"""
    # Check if user is logged in
    if "logged_in" not in st.session_state or not st.session_state.logged_in:
        st.warning("Please login from the Home page to access the assessor.")
        st.markdown("### [Return to Home Page](/)")
        st.stop()
    
    st.title("Tutorial Questions")
    
    # Render sidebar
    render_sidebar(st.session_state.user_id)
    
    # Load modules data
    modules = load_module_data()
    if not modules:
        st.error("No modules data available. Please try again later.")
        return
    
    # Render module selector
    selected_module_title = render_module_selector(modules)
    
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
    
    # Get module ID
    module_id = str(modules.index(selected_module_data) + 1)
    
    # Render each question
    for question_id, question_info in tutorial_questions.items():
        render_question(question_id, question_info, st.session_state.user_id, module_id) 