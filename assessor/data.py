import streamlit as st
from mongodb.connectors import (get_modules_data, get_user_progress, update_user_progress, 
                               save_assessment_results as db_save_assessment_results,
                               get_assessment_results as db_get_assessment_results,
                               get_module_data as db_get_module_data)
from typing import Dict, List, Optional
from datetime import datetime
from bson.binary import Binary

@st.cache_data(ttl=10)
def load_module_data() -> List[Dict]:
    """Load module information from MongoDB"""
    try:
        data = get_modules_data()
        if "modules" in data and isinstance(data["modules"], list):
            # Sort modules by their index attribute
            modules = data["modules"]
            modules.sort(key=lambda x: x.get("index", float('inf')))  # Use float('inf') as default for modules without index
            return modules
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

def update_question_progress(user_id: str, module_id: str, question_index: int, status: str = "in_progress", attempts: int = None) -> None:
    """Update user progress for a specific question
    
    Args:
        user_id: The user's ID
        module_id: The module ID
        question_index: The zero-based index of the question
        status: The status to set (default: "in_progress")
        attempts: The number of attempts to set (optional)
    """
    # Convert question index to question_id format (1-based) for MongoDB storage
    question_id = str(int(question_index) + 1)
    
    print(f"[DEBUG] Updating question progress - User: {user_id}, Module: {module_id}, Question: {question_id} (index: {question_index})")
    print(f"[DEBUG] Status: {status}, Attempts: {attempts}")
    
    # Calculate the appropriate progress value based on status
    if status == "completed":
        progress = 2
    elif status == "in_progress":
        progress = 1
    else:
        progress = 0
    
    # Update the question progress using the centralized connector function
    update_user_progress(
        user_id=user_id,
        module_id=module_id,
        question_id=question_id,
        progress=progress,
        status=status,
        attempts=attempts
    )

def save_assessment_results(user_id: str, module_id: str, question_index: int,
                            competency_level: int, feedback: str, status: str,
                            response_text: str,
                            input_image_data: Optional[List[bytes]] = None) -> None:
    """Save assessment results for a specific question
    
    This is a wrapper around the database connector function.

    Args:
        user_id: The user's ID
        module_id: The module ID
        question_index: The zero-based index of the question
        competency_level: The competency level (0, 1, or 2)
        feedback: Feedback for the student
        status: Question status (completed, in_progress)
        response_text: Raw response text from the assessment API
        input_image_data: List of image bytes provided by the user
    """
    # Convert question index to question_id format (1-based) for MongoDB storage
    question_id = str(int(question_index) + 1)
    
    print(f"[DEBUG] Saving assessment results - User: {user_id}, Module: {module_id}, Question: {question_id} (index: {question_index})")
    print(f"[DEBUG] Competency Level: {competency_level}, Status: {status}")
    
    # Delegate to the centralized database connector function
    result = db_save_assessment_results(
        user_id, 
        module_id,
        question_index,
        competency_level,
        feedback,
        status,
        response_text,
        input_image_data
    )
    
    if not result:
        st.error("Error saving assessment results")

@st.cache_data(ttl=300)  # Cache for 5 minutes
def get_module_data(user_id: str, module_id: str) -> Dict:
    """Get all module data including progress and assessments in one query
    
    This is a cached wrapper around the database connector function.
    """
    try:
        # Get module data from the database
        module_data = db_get_module_data(user_id, module_id)
        
        # Ensure question IDs are in the correct format (1-based string IDs)
        if "assessments" in module_data:
            # Convert any numeric keys to string keys
            assessments = module_data["assessments"]
            if any(isinstance(k, int) for k in assessments.keys()):
                module_data["assessments"] = {str(k): v for k, v in assessments.items()}
        
        return module_data
    except Exception as e:
        st.error(f"Error loading module data: {str(e)}")
        return {"progress": {}, "assessments": {}, "topics": {}}

def get_assessment_results(user_id: str, module_id: str, question_index: int) -> Optional[Dict]:
    """
    Retrieve assessment results for a specific question from the database.
    
    This is a wrapper around the database connector function.
    
    Args:
        user_id: The user's ID
        module_id: The module ID
        question_index: The zero-based index of the question
        
    Returns:
        Optional[Dict]: Assessment results if found, None otherwise
    """
    # Convert question index to question_id format (1-based) for MongoDB storage
    question_id = str(int(question_index) + 1)
    
    print(f"[DEBUG] Getting assessment results - User: {user_id}, Module: {module_id}, Question: {question_id} (index: {question_index})")
    
    return db_get_assessment_results(user_id, module_id, question_index) 