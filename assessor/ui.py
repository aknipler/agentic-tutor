import streamlit as st
from typing import Dict, List, Optional
from .utils import get_status_emoji
from .data import (
    get_user_module_progress, 
    update_question_progress, 
    save_assessment_results, 
    get_mongo_client, 
    get_module_data,
    get_assessment_results
)
from .file_handler import save_uploaded_file, get_file_url
from .openai_assessor import assess_answer
from datetime import datetime

# Initialize session state for pagination if not exists
if "question_page" not in st.session_state:
    st.session_state.question_page = 1

def get_assessment_results(user_id: str, module_id: str, question_id: str) -> Optional[Dict]:
    """Get assessment results for a specific question"""
    try:
        client = get_mongo_client()
        db = client["funce_db"]
        progress_collection = db["user_module_progress"]
        
        # Find the user's progress document
        user_doc = progress_collection.find_one({"user_id": user_id})
        
        if user_doc:
            # Extract question data from the nested structure
            question_data = user_doc.get("modules", {}).get(module_id, {}).get("questions", {}).get(question_id)
            
            if question_data:
                # Convert datetime objects to strings for JSON serialization
                if "last_assessed" in question_data:
                    question_data["last_assessed"] = question_data["last_assessed"].isoformat()
                if "last_attempt" in question_data:
                    question_data["last_attempt"] = question_data["last_attempt"].isoformat()
                return question_data
            
        return None
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

def render_module_selector(modules: List[Dict], default: Optional[str] = None) -> str:
    """Render the module selector dropdown"""
    module_titles = [m.get("title", f"Module {i+1}") for i, m in enumerate(modules)]
    
    # Use the default if provided, otherwise use the first module
    initial_index = module_titles.index(default) if default in module_titles else 0
    
    return st.selectbox(
        "Select Module",
        options=module_titles,
        index=initial_index
    )

def render_questions_paginated(questions: Dict, user_id: str, module_id: str, per_page: int = 5):
    """Render questions with pagination"""
    # Calculate pagination
    total_questions = len(questions)
    total_pages = (total_questions + per_page - 1) // per_page
    current_page = st.session_state.question_page
    start_idx = (current_page - 1) * per_page
    end_idx = min(start_idx + per_page, total_questions)
    
    # Get current page of questions
    question_items = list(questions.items())
    current_questions = dict(question_items[start_idx:end_idx])
    
    # Get module data (cached) which now includes both progress and assessment data
    module_data = get_module_data(user_id, module_id)
    module_progress = module_data["progress"]
    questions_data = module_data["assessments"]  # This now contains the assessment data
    
    # Render current page of questions
    for question_id, question_info in current_questions.items():
        render_question(
            question_id, 
            question_info, 
            user_id, 
            module_id,
            module_progress,
            questions_data.get(question_id)  # Pass the question data which includes assessment info
        )
    
    # Pagination controls
    if total_pages > 1:
        col1, col2, col3 = st.columns([1, 3, 1])
        with col1:
            if current_page > 1:
                if st.button("Previous"):
                    st.session_state.question_page = current_page - 1
                    st.rerun()
        with col3:
            if current_page < total_pages:
                if st.button("Next"):
                    st.session_state.question_page = current_page + 1
                    st.rerun()
        with col2:
            st.write(f"Page {current_page} of {total_pages}")

def render_question(question_id: str, question_info: Dict, user_id: str, module_id: str, 
                  module_progress: Dict = None, assessment: Dict = None):
    """Render a single question with its answer input and file upload"""
    question_text = question_info.get("question", f"Question {question_id}")
    
    # Get and prepare question progress first
    if module_progress is None:
        module_progress = get_user_module_progress(user_id, module_id)
    question_progress = module_progress.get("questions", {}).get(question_id, {})
    status = question_progress.get("status", "not_started")
    attempts = question_progress.get("attempts", 0)
    
    # Get status emoji for the label
    status_emoji = get_status_emoji(status)
    
    # Create a unique key for this question's session state
    question_key = f"question_{user_id}_{module_id}_{question_id}"
    
    # Initialize or retrieve the question's session state
    if question_key not in st.session_state:
        st.session_state[question_key] = {
            "assessment": None,
            "last_attempt": None
        }
    
    # Use lazy loading with expander
    with st.expander(f"{status_emoji} {question_text}", expanded=False):
        # Display the question
        st.write(question_text)
        
        st.write(f"Status: {status_emoji} | Attempts: {attempts}")
        
        # Get and display question progress
        if module_progress is None:
            module_progress = get_user_module_progress(user_id, module_id)
        question_progress = module_progress.get("questions", {}).get(question_id, {})
        status = question_progress.get("status", "not_started")
        attempts = question_progress.get("attempts", 0)
        
        # Answer input
        answer = st.text_area("Your Answer", key=f"answer_{question_id}")
        
        # File upload - Allow multiple files
        uploaded_files = st.file_uploader(
            "Upload Worked Solution(s)",
            type=["png", "jpg", "jpeg"],
            key=f"upload_{question_id}",
            accept_multiple_files=True
        )
        
        # Submit button
        if st.button("Submit Answer", key=f"submit_{question_id}"):
            if answer.strip() or uploaded_files:
                # Increment attempts *before* assessment
                new_attempts = attempts + 1
                update_question_progress(user_id, module_id, question_id, status="in_progress", attempts=new_attempts)

                # Process file uploads
                image_data_list = []
                if uploaded_files:
                    with st.spinner("Processing uploaded solution(s)..."):
                        for uploaded_file in uploaded_files:
                            image_bytes = uploaded_file.read()
                            image_data_list.append(image_bytes)

                # Assess the answer
                with st.spinner("Assessing your answer..."):
                    expected_answer_text = question_info.get("expected_answer", "No expected answer provided.")

                    assessment = assess_answer(
                        question=question_text,
                        answer=answer.strip() if answer.strip() else "No text answer provided. Please refer to the uploaded solution(s).",
                        expected_answer=expected_answer_text,
                        image_data_list=image_data_list
                    )

                    save_assessment_results(
                        user_id=user_id,
                        module_id=module_id,
                        question_id=question_id,
                        competency_level=assessment["competency_level"],
                        feedback=assessment["feedback"],
                        status=assessment["status"],
                        response_text=assessment["response_text"],
                        input_image_data=assessment["input_image_data"]
                    )

                    # Update session state with the new assessment
                    st.session_state[question_key]["assessment"] = assessment
                    st.session_state[question_key]["last_attempt"] = datetime.now()

                    st.success("Your answer has been assessed!")
                    
                    with st.container(border=True):
                        st.subheader("Assessment Results")
                        progress = assessment["competency_level"] / 2
                        st.progress(progress)
                        competency_text = {
                            0: "Not Attempted",
                            1: "Partial Understanding",
                            2: "Full Understanding"
                        }.get(assessment["competency_level"], "Unknown")
                        st.write(f"Competency Level: {competency_text}")
                        st.write(f"Feedback: {assessment['feedback']}")
                    
                    st.rerun()
            else:
                st.warning("Please provide either a text answer or upload a solution (or both) before submitting.")
        
        # Retrieve assessment results if not provided
        if assessment is None:
            # First try to get from session state
            cached_assessment = st.session_state[question_key]["assessment"]
            if cached_assessment:
                assessment = cached_assessment
            else:
                # If not in session state, get from database
                assessment = get_assessment_results(user_id, module_id, question_id)
                if assessment:
                    # Update session state with the retrieved assessment
                    st.session_state[question_key]["assessment"] = assessment
        
        # Display previous feedback if available
        if assessment and assessment.get("assessed", False):
            with st.container(border=True):
                st.subheader("Assessment Results")
                competency_level = assessment.get("competency_level", 0)
                # Convert competency level to progress (0->0.33, 1->0.66, 2->1.0)
                progress = competency_level / 2
                st.progress(progress)
                competency_text = {
                    0: "Not Attempted",
                    1: "Partial Understanding",
                    2: "Full Understanding"
                }.get(competency_level, "Unknown")
                st.write(f"Competency Level: {competency_text}")
                st.write(f"Feedback: {assessment.get('feedback', 'No feedback available.')}") 