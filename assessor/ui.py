import streamlit as st
import hashlib
from typing import Dict, List, Optional
from .utils import get_status_emoji
from .voice import transcribe
from .data import (
    get_user_module_progress,
    save_assessment_results,
    get_module_data,
    get_assessment_results
)
from mongodb.connectors import get_mongo_client
from mongodb.logger import UserLogger
from .file_handler import save_uploaded_file, get_file_url
from .openai_assessor import assess_answer
from datetime import datetime
import os

# Initialize session state for pagination if not exists
if "question_page" not in st.session_state:
    st.session_state.question_page = 1

# Initialize logger
logger = UserLogger()

# Define image directory paths
QUESTION_IMAGES_DIR = "knowledge/images/questions"
ANSWER_IMAGES_DIR = "knowledge/images/answers"

def get_question_assessment_results(user_id: str, module_id: str, question_index: int) -> Optional[Dict]:
    """Get assessment results for a specific question"""
    try:
        # Get the assessment results from the database
        assessment = get_assessment_results(user_id, module_id, question_index)
        
        if assessment:
            # Convert datetime strings back to datetime objects if needed
            if "last_assessed" in assessment and isinstance(assessment["last_assessed"], str):
                assessment["last_assessed"] = datetime.fromisoformat(assessment["last_assessed"])
            if "last_attempt" in assessment and isinstance(assessment["last_attempt"], str):
                assessment["last_attempt"] = datetime.fromisoformat(assessment["last_attempt"])
            
            # Add a flag to indicate this is an assessed question
            assessment["assessed"] = True
        
        return assessment
    except Exception as e:
        print(f"[Error] Failed to get assessment results: {str(e)}")
        return None

def render_sidebar(user_id: str):
    """Render the sidebar with user info and logout button"""
    with st.sidebar:
        st.write(f"User: {user_id}")
        if st.button("Logout"):
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
    
    # Get module data (cached) which now includes progress, topics, and assessment data
    module_data = get_module_data(user_id, module_id)
    module_progress = module_data["progress"]
    topics_data = module_data["topics"]  # This contains the topics data
    questions_data = module_data["assessments"]  # This contains the assessment data
    
    # Create a complete module_progress object to pass to render_question
    complete_progress = {
        **module_progress,
        "topics": topics_data,
        "questions": questions_data
    }
    
    # Render current page of questions
    for question_id, question_info in current_questions.items():
        # Ensure question_id is in the correct format for MongoDB lookup
        # If it's a numeric string, keep it as is (it's already 1-based)
        # If it's in format 'q1', 'q2', etc., extract the number
        if question_id.startswith('q') and question_id[1:].isdigit():
            db_question_id = question_id[1:]  # Extract the number part
        else:
            db_question_id = question_id
            
        render_question(
            question_id, 
            question_info, 
            user_id, 
            module_id,
            complete_progress,  # Pass the complete progress data
            questions_data.get(db_question_id)  # Pass the question data which includes assessment info
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

def run_assessment(user_id: str, module_id: str, question_index: int, question_key: str,
                   question_text: str, question_info: Dict, answer_text: str,
                   image_data_list: Optional[List[bytes]] = None) -> None:
    """Assess an answer, persist the result, then rerun so it renders once.

    Shared by the typed and spoken submission paths so both record progress
    identically. Does not return - it ends in st.rerun().
    """
    image_data_list = image_data_list or []

    with st.spinner("Assessing your answer..."):
        assessment = assess_answer(
            question=question_text,
            answer=answer_text,
            expected_answer=question_info.get("expected_answer", "No expected answer provided."),
            image_data_list=image_data_list,
            success_criteria=question_info.get("success_criteria", "")
        )

        logger.log_submission(
            user_id=user_id,
            module=str(module_id),
            question=question_text,
            submission=answer_text,
            grade=assessment["competency_level"] / 2  # Convert to 0-1 scale
        )

        # Owns the whole question record: status, competency, feedback, attempts.
        save_assessment_results(
            user_id=user_id,
            module_id=str(module_id),
            question_index=question_index,
            competency_level=assessment["competency_level"],
            feedback=assessment["feedback"],
            status=assessment["status"],
            response_text=assessment["response_text"],
            input_image_data=assessment["input_image_data"]
        )

        st.session_state[question_key]["assessment"] = assessment
        st.session_state[question_key]["last_attempt"] = datetime.now()
        st.session_state[question_key]["just_assessed"] = True

        # Drop the cached progress, else the page keeps serving pre-submission
        # state until the cache expires.
        get_module_data.clear()

        # Rerun so the results render once, below, from the database.
        st.rerun()


def render_voice_answer(question_id: str, question_key: str, question_text: str,
                        question_info: Dict, user_id: str, module_id: str,
                        question_index: int) -> None:
    """Record a spoken answer, transcribe it, and submit once confirmed.

    The transcript is always shown for review before it counts: speech models
    mangle technical terms, and an unchecked mis-transcription would be graded and
    consume an attempt.
    """
    voice_key = f"voice_{question_key}"
    voice_state = st.session_state.setdefault(voice_key, {"processed_hash": None, "transcript": None})

    recording = st.audio_input("Record your answer", key=f"audio_{question_id}")

    if recording is not None:
        audio_bytes = recording.getvalue()
        # st.audio_input keeps returning the same recording on every rerun, so
        # fingerprint it and only transcribe one we haven't already handled.
        digest = hashlib.sha256(audio_bytes).hexdigest()
        if digest != voice_state["processed_hash"]:
            voice_state["processed_hash"] = digest
            with st.spinner("Transcribing your answer..."):
                voice_state["transcript"] = transcribe(
                    audio_bytes,
                    filename=getattr(recording, "name", None) or "answer.wav",
                    question_text=question_text
                )

    transcript = voice_state.get("transcript")
    if not transcript:
        return

    st.caption("Check the transcription before submitting - edit it if anything was misheard.")
    edited = st.text_area("Transcribed answer", value=transcript, key=f"transcript_{question_id}")

    confirm_col, discard_col = st.columns(2)
    with confirm_col:
        if st.button("Submit this answer", key=f"submit_voice_{question_id}"):
            if edited.strip():
                # Clear the transcript but keep the fingerprint, so the same
                # recording isn't transcribed again on the post-submit rerun.
                voice_state["transcript"] = None
                run_assessment(
                    user_id, module_id, question_index, question_key,
                    question_text, question_info, edited.strip()
                )
            else:
                st.warning("The transcribed answer is empty. Please record again.")
    with discard_col:
        if st.button("Discard & re-record", key=f"discard_voice_{question_id}"):
            voice_state["transcript"] = None
            st.rerun()


def render_question(question_id: str, question_info: Dict, user_id: str, module_id: str,
                  module_progress: Dict = None, assessment: Dict = None):
    """Render a single question with its answer input and file upload"""
    # Convert question_id to index (zero-based)
    # If question_id is in format like 'q1', 'q2', etc., extract the number and subtract 1
    if question_id.startswith('q') and question_id[1:].isdigit():
        question_index = int(question_id[1:]) - 1
    # If it's just numeric, convert directly
    elif question_id.isdigit():
        question_index = int(question_id) - 1
    else:
        # Fallback - use as is, but warn
        question_index = 0
        print(f"[WARNING] Could not convert question_id '{question_id}' to index. Using 0.")
    
    question_text = question_info.get("question", f"Question {question_id}")
    question_label = question_info.get("label", f"Question {question_id}")
    
    # Get and prepare question progress first
    if module_progress is None:
        module_progress = get_user_module_progress(user_id, module_id)
    
    # For DB lookup, we need the 1-based string ID that's in the database
    db_question_id = str(question_index + 1)  # Convert to 1-based string ID for MongoDB
    question_progress = module_progress.get("questions", {}).get(db_question_id, {})
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
    with st.expander(f"{status_emoji} {question_label}", expanded=False):
        # Display the question
        st.write(question_text)
        
        # Display question image if available
        # Old implementation using URLs (commented out)
        # question_image_url = question_info.get("question_image_url")
        # print(f"[DEBUG] question_image_url: {question_image_url}")
        # if question_image_url:
        #     st.image(question_image_url, caption="Question Image")
        
        # New implementation using local images
        question_image_path = os.path.join(QUESTION_IMAGES_DIR, f"{question_label}.png")
        if os.path.exists(question_image_path):
            st.image(question_image_path, caption="Question Image")
        
        st.write(f"Status: {status_emoji} | Attempts: {attempts}")
        
        # Get and display question progress
        if module_progress is None:
            module_progress = get_user_module_progress(user_id, module_id)
        question_progress = module_progress.get("questions", {}).get(db_question_id, {})
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
                # Process file uploads
                image_data_list = []
                if uploaded_files:
                    with st.spinner("Processing uploaded solution(s)..."):
                        for uploaded_file in uploaded_files:
                            image_bytes = uploaded_file.read()
                            image_data_list.append(image_bytes)

                run_assessment(
                    user_id, module_id, question_index, question_key,
                    question_text, question_info,
                    answer.strip() or "No text answer provided. Please refer to the uploaded solution(s).",
                    image_data_list
                )
            else:
                st.warning("Please provide either a text answer or upload a solution (or both) before submitting.")

        # Spoken answers, as an alternative to typing
        if st.toggle("🎤 Answer by voice", key=f"voice_toggle_{question_id}"):
            render_voice_answer(
                question_id, question_key, question_text, question_info,
                user_id, module_id, question_index
            )

        # Retrieve assessment results if not provided
        if assessment is None:
            # First try to get from session state
            cached_assessment = st.session_state[question_key]["assessment"]
            if cached_assessment:
                assessment = cached_assessment
            else:
                # If not in session state, get from database
                assessment = get_question_assessment_results(user_id, module_id, question_index)
                if assessment:
                    # Update session state with the retrieved assessment
                    st.session_state[question_key]["assessment"] = assessment
        
        # Confirm a submission that just completed (set before the rerun above)
        if st.session_state[question_key].get("just_assessed"):
            st.success("Your answer has been assessed!")
            st.session_state[question_key]["just_assessed"] = False

        # Display previous feedback if available
        print(f"[DEBUG] assessment: {assessment}")
        if assessment and assessment.get("competency_level", 0) > 0:
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

                # Display answer image if available
                answer_image_path = os.path.join(ANSWER_IMAGES_DIR, f"{question_label}.png")
                if os.path.exists(answer_image_path):
                    st.image(answer_image_path, caption="Answer Image") 