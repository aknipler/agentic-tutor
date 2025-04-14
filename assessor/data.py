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

def update_question_progress(user_id: str, module_id: str, question_id: str, status: str = "in_progress", attempts: int = None) -> None:
    """Update user progress for a specific question
    
    Args:
        user_id: The user's ID
        module_id: The module ID
        question_id: The question ID
        status: The status to set (default: "in_progress")
        attempts: The number of attempts to set (optional)
    """
    print(f"[DEBUG] Updating question progress - User: {user_id}, Module: {module_id}, Question: {question_id}")
    print(f"[DEBUG] Status: {status}, Attempts: {attempts}")
    
    update_user_progress(
        user_id=user_id,
        module_id=module_id,
        question_id=question_id,
        progress=1,
        status=status,
        attempts=attempts
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
    try:
        print(f"[DEBUG] Saving assessment results - User: {user_id}, Module: {module_id}, Question: {question_id}")
        print(f"[DEBUG] Competency Level: {competency_level}, Status: {status}")
        
        client = get_mongo_client()
        db = client["funce_db"]
        progress_collection = db["user_module_progress"]

        # Convert image bytes to BSON Binary format
        bson_image_data = []
        if input_image_data:
            bson_image_data = [Binary(img_bytes) for img_bytes in input_image_data]
            print(f"[DEBUG] Processed {len(bson_image_data)} images")

        # First, get the current question data to get the current attempts count
        user_doc = progress_collection.find_one({"user_id": user_id})
        current_attempts = 0
        if user_doc:
            question_data = user_doc.get("modules", {}).get(module_id, {}).get("questions", {}).get(question_id, {})
            current_attempts = question_data.get("attempts", 0)
            print(f"[DEBUG] Current attempts from DB: {current_attempts}")

        # Update user progress with assessment data
        update_data = {
            "status": status,
            "competency_level": competency_level,
            "feedback": feedback,
            "response_text": response_text,
            "input_image_data": bson_image_data,
            "last_assessed": datetime.now(),
            "attempts": current_attempts + 1,
            "last_attempt": datetime.now()
        }
        print(f"[DEBUG] Updating with data: {update_data}")
        
        update_result = progress_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    f"modules.{module_id}.questions.{question_id}": update_data,
                    "updated_at": datetime.now()
                }
            }
        )
        print(f"[DEBUG] MongoDB update result - Modified count: {update_result.modified_count}")
        
    except Exception as e:
        print(f"[ERROR] Failed to save assessment results: {str(e)}")
        st.error(f"Error saving assessment results: {str(e)}")

@st.cache_data(ttl=300)  # Cache for 5 minutes
def get_module_data(user_id: str, module_id: str) -> Dict:
    """Get all module data including progress and assessments in one query"""
    try:
        client = get_mongo_client()
        db = client["funce_db"]
        
        # Get user progress document
        user_doc = db["user_module_progress"].find_one({"user_id": user_id})
        
        if not user_doc:
            return {"progress": {}, "assessments": {}}
        
        # Extract progress data for the specific module
        progress_data = user_doc.get("modules", {}).get(module_id, {})
        
        # Extract questions data which now includes assessment information
        questions_data = progress_data.get("questions", {})
        
        return {
            "progress": progress_data,
            "assessments": questions_data  # Questions now contain assessment data
        }
    except Exception as e:
        st.error(f"Error loading module data: {str(e)}")
        return {"progress": {}, "assessments": {}}

def get_assessment_results(user_id: str, module_id: str, question_id: str) -> Optional[Dict]:
    """
    Retrieve assessment results for a specific question from the database.
    
    Args:
        user_id: The user's ID
        module_id: The module ID
        question_id: The question ID
        
    Returns:
        Optional[Dict]: Assessment results if found, None otherwise
    """
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
        print(f"[Error] Failed to retrieve assessment results: {str(e)}")
        return None 