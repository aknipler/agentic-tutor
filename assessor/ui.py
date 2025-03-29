import streamlit as st
from typing import Dict, List, Optional
from .utils import get_status_emoji
from .data import get_user_module_progress, update_question_progress, save_assessment_results, get_mongo_client
from .file_handler import save_uploaded_file, get_file_url
from .openai_assessor import assess_answer
from datetime import datetime

def get_assessment_results(user_id: str, module_id: str, question_id: str) -> Optional[Dict]:
    """Get assessment results for a specific question"""
    try:
        client = get_mongo_client()
        db = client["funce_db"]
        assessment_collection = db["question_assessments"]
        
        result = assessment_collection.find_one({
            "user_id": user_id,
            "module_id": module_id,
            "question_id": question_id
        })
        
        return result
    except Exception as e:
        st.error(f"Error retrieving assessment results: {str(e)}")
        return None

def render_sidebar(user_id: str):
    """Render the sidebar with user info and logout button"""
    col1, col2 = st.sidebar.columns([3, 1])
    with col1:
        st.info(f"Logged in as: {user_id}")
    with col2:
        if st.button("Logout"):
            st.session_state.logged_in = False
            st.session_state.user_id = None
            st.rerun()

def render_module_selector(modules: List[Dict]) -> str:
    """Render the module selector and return the selected module title"""
    module_titles = [module.get("title", f"Module {i+1}") for i, module in enumerate(modules)]
    return st.selectbox("Select Module", module_titles)

def render_question(question_id: str, question_info: Dict, user_id: str, module_id: str):
    """Render a single question with its answer input and file upload"""
    with st.expander(f"Question {question_id}", expanded=False):
        # Display the question
        question_text = question_info.get("question", "")
        st.write(question_text)
        
        # Get and display question progress
        module_progress = get_user_module_progress(user_id, module_id)
        question_progress = module_progress.get("questions", {}).get(question_id, {})
        status = question_progress.get("status", "not_started")
        attempts = question_progress.get("attempts", 0)
        
        st.write(f"Status: {get_status_emoji(status)} | Attempts: {attempts}")
        
        # Display previous feedback if available
        assessment = get_assessment_results(user_id, module_id, question_id)
        if assessment and assessment.get("assessed", False):
            with st.container(border=True):
                st.subheader("Assessment Results")
                score = assessment.get("score", 0)
                st.progress(score)
                st.write(f"Score: {int(score * 100)}%")
                st.write(f"Feedback: {assessment.get('feedback', 'No feedback available.')}")
        
        # Answer input
        answer = st.text_area("Your Answer", key=f"answer_{question_id}")
        
        # File upload
        uploaded_file = st.file_uploader(
            "Upload Worked Solution (Optional)", 
            type=["png", "jpg", "jpeg"], 
            key=f"upload_{question_id}"
        )
        
        # Submit button
        if st.button("Submit Answer", key=f"submit_{question_id}"):
            if answer.strip():
                # Process file upload first
                file_path = None
                image_url = None
                
                if uploaded_file:
                    with st.spinner("Uploading your solution..."):
                        file_path = save_uploaded_file(uploaded_file, user_id, question_id)
                        if file_path:
                            image_url = get_file_url(file_path)
                
                # Assess the answer
                with st.spinner("Assessing your answer..."):
                    assessment = assess_answer(
                        question=question_text,
                        answer=answer,
                        image_url=image_url
                    )
                    
                    # Save assessment results
                    save_assessment_results(
                        user_id=user_id,
                        module_id=module_id,
                        question_id=question_id,
                        score=assessment["score"],
                        feedback=assessment["feedback"],
                        status=assessment["status"]
                    )
                    
                    # Display assessment results
                    st.success("Your answer has been assessed!")
                    
                    with st.container(border=True):
                        st.subheader("Assessment Results")
                        st.progress(assessment["score"])
                        st.write(f"Score: {int(assessment['score'] * 100)}%")
                        st.write(f"Feedback: {assessment['feedback']}")
                    
                    # Refresh the page to update the status
                    st.rerun()
            else:
                st.warning("Please provide an answer before submitting.") 