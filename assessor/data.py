import streamlit as st
from mongodb.connectors import get_modules_data, get_user_progress, update_user_progress, get_mongo_client
from typing import Dict, List, Optional
from datetime import datetime
from bson.binary import Binary

@st.cache_data(ttl=10)
def load_module_data() -> List[Dict]:
    """Load module information from MongoDB"""
    try:
        data = get_modules_data()
        if "modules" in data and isinstance(data["modules"], list):
            return data["modules"]
        return []
    except Exception as e:
        st.error(f"Error loading module data: {str(e)}")
        return []

def get_module_by_title(modules: List[Dict], title: str) -> Optional[Dict]:
    """Get module data by title"""
    return next((module for module in modules if module.get("title") == title), None)

def get_user_module_progress(user_id: str, module_id: str) -> Dict:
    """Get user progress for a specific module"""
    user_progress = get_user_progress(user_id)
    return user_progress.get("modules", {}).get(module_id, {})

def update_question_progress(user_id: str, module_id: str, question_id: str, status: str = "in_progress") -> None:
    """Update user progress for a specific question"""
    update_user_progress(
        user_id=user_id,
        module_id=module_id,
        question_id=question_id,
        progress=1,
        status=status
    )

def save_assessment_results(user_id: str, module_id: str, question_id: str,
                            competency_level: int, feedback: str, status: str,
                            response_text: str,
                            input_image_data: Optional[List[bytes]]
                           ) -> None:
    """Save assessment results for a specific question

    Args:
        user_id: The user's ID
        module_id: The module ID
        question_id: The question ID
        competency_level: The competency level (0, 1, or 2)
        feedback: Feedback for the student
        status: Question status (completed, in_progress)
        response_text: Raw response text from the assessment API
        input_image_data: List of image bytes provided by the user
    """
    # Calculate progress value (1-10) based on competency level
    # Level 0 -> 1-3, Level 1 -> 4-7, Level 2 -> 8-10
    progress = max(1, min(10, competency_level * 4))

    # Update user progress with assessment data (consider if this needs more info)
    update_user_progress(
        user_id=user_id,
        module_id=module_id,
        question_id=question_id,
        progress=progress,
        status=status
    )

    # Store assessment data in a separate collection
    try:
        client = get_mongo_client()
        db = client["funce_db"]
        assessment_collection = db["question_assessments"]

        # Convert image bytes to BSON Binary format
        bson_image_data = []
        if input_image_data:
            bson_image_data = [Binary(img_bytes) for img_bytes in input_image_data]

        # Create or update assessment record
        assessment_collection.update_one(
            {
                "user_id": user_id,
                "module_id": module_id,
                "question_id": question_id
            },
            {
                "$set": {
                    "competency_level": competency_level,
                    "feedback": feedback,
                    "response_text": response_text,
                    "input_image_data": bson_image_data,
                    "assessed": True,
                    "last_assessed": datetime.now()
                }
            },
            upsert=True
        )
    except Exception as e:
        st.error(f"Error saving assessment results: {str(e)}") 