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
    question_text = question_info.get("question", f"Question {question_id}")
    with st.expander(question_text, expanded=False):
        # Display the question
        
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
                competency_level = assessment.get("competency_level", 0)
                # Convert competency level to progress (0->0.33, 1->0.66, 2->1.0)
                progress = competency_level / 2
                st.progress(progress)
                competency_text = {
                    0: "No Understanding",
                    1: "Partial Understanding",
                    2: "Full Understanding"
                }.get(competency_level, "Unknown")
                st.write(f"Competency Level: {competency_text}")
                st.write(f"Feedback: {assessment.get('feedback', 'No feedback available.')}")
        
        # Answer input
        answer = st.text_area("Your Answer", key=f"answer_{question_id}")
        
        # File upload - Allow multiple files
        uploaded_files = st.file_uploader(
            "Upload Worked Solution(s)",
            type=["png", "jpg", "jpeg"],
            key=f"upload_{question_id}",
            accept_multiple_files=True # Allow multiple files
        )
        
        # Submit button
        if st.button("Submit Answer", key=f"submit_{question_id}"):
            if answer.strip() or uploaded_files:
                # Increment attempts *before* assessment
                new_attempts = attempts + 1
                update_question_progress(user_id, module_id, question_id, {"attempts": new_attempts})
                # Optional: Add a log or print statement for debugging
                # print(f"Attempt {new_attempts} recorded for {user_id}, Module {module_id}, Question {question_id}")

                # Process file uploads
                image_data_list = []
                if uploaded_files:
                    with st.spinner("Processing uploaded solution(s)..."):
                        for uploaded_file in uploaded_files:
                            # Read file content as bytes
                            image_bytes = uploaded_file.read()
                            image_data_list.append(image_bytes)
                            # Removed saving to file system: file_path = save_uploaded_file(...)
                            # Removed getting file URL: image_url = get_file_url(...)

                # Assess the answer
                with st.spinner("Assessing your answer..."):
                    # Fetch the expected answer from question_info
                    expected_answer_text = question_info.get("expected_answer", "No expected answer provided.") # Default if not found

                    # Pass image data list and expected answer
                    assessment = assess_answer(
                        question=question_text,
                        answer=answer.strip() if answer.strip() else "No text answer provided. Please refer to the uploaded solution(s).",
                        expected_answer=expected_answer_text, # Pass the expected answer
                        image_data_list=image_data_list
                    )

                    # Save assessment results, including the new fields
                    save_assessment_results(
                        user_id=user_id,
                        module_id=module_id,
                        question_id=question_id,
                        competency_level=assessment["competency_level"],
                        feedback=assessment["feedback"],
                        status=assessment["status"],
                        response_text=assessment["response_text"], # Pass response_text
                        input_image_data=assessment["input_image_data"] # Pass image data
                    )

                    # Display assessment results
                    st.success("Your answer has been assessed!")
                    
                    with st.container(border=True):
                        st.subheader("Assessment Results")
                        # Convert competency level to progress (0->0.33, 1->0.66, 2->1.0)
                        progress = assessment["competency_level"] / 2
                        st.progress(progress)
                        st.write(f"Feedback: {assessment['feedback']}")
                    
                    # Refresh the page to update the status
                    st.rerun()
            else:
                st.warning("Please provide either a text answer or upload a solution (or both) before submitting.") 