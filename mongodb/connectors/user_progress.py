import streamlit as st
from datetime import datetime
from .base import get_mongo_client
from typing import List, Dict, Any, Optional
from .modules import get_cached_modules_data
from bson.binary import Binary

def get_user_progress(user_id="user123"):
    """
    Retrieve user progress data from MongoDB using the new user_module_progress collection.
    
    Args:
        user_id (str): The ID of the user (login code).
        
    Returns:
        dict: A dictionary containing the user's progress data.
    """
    try:
        client = get_mongo_client()
        db = client[st.secrets["MONGODB_DATABASE_NAME"]]
        user_progress_collection = db["user_module_progress"]
        
        # Get user progress
        user_data = user_progress_collection.find_one({"user_id": user_id})
        
        if not user_data:
            # Get modules data from cache
            modules_data = get_cached_modules_data()
            modules_list = modules_data.get("modules", [])
            
            # Create default progress structure for new user
            default_data = {
                "user_id": user_id,
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
                "modules": {}
            }
            
            # Initialize modules with default values
            for module in modules_list:
                # Use the module's explicit index field
                module_id = str(module.get("index", 0))
                default_data["modules"][module_id] = {
                    "progress": 0,
                    "status": "not_started",
                    "topics": {},
                    "questions": {}
                }
                
                # Initialize topics
                for topic in module.get("topics", []):
                    topic_name = topic.get("name")
                    default_data["modules"][module_id]["topics"][topic_name] = {
                        "progress": 0,
                        "status": "not_started"
                    }
                
                # Initialize questions
                for question_id, question_info in module.get("tutorial_questions", {}).items():
                    default_data["modules"][module_id]["questions"][question_id] = {
                        "status": "not_started",
                        "attempts": 0,
                        "last_attempt": None
                    }
            
            # Insert default progress data
            user_progress_collection.insert_one(default_data)
            
            # Return the default data
            return default_data
        
        if st.session_state.get('debug_mode', False):
            st.write("Debug: Retrieved user progress:", user_data)
        return user_data
    except Exception as e:
        if st.session_state.get('debug_mode', False):
            st.error(f"Debug: Error in get_user_progress: {str(e)}")
        else:
            st.error("Error retrieving user progress")
        return {"user_id": user_id, "modules": {}}

def update_user_progress(user_id, module_id, topic_id=None, question_id=None, progress=None, status=None, attempts=None):
    """
    Update user progress in MongoDB using the user_module_progress collection.
    The data structure has topics and questions stored in nested objects.
    
    Args:
        user_id (str): The ID of the user.
        module_id (str): The ID of the module.
        topic_id (str, optional): The ID of the topic to update.
        question_id (str, optional): The ID of the question to update.
        progress (int, optional): The new progress value (0=not started, 1=in progress, 2=completed).
        status (str, optional): The new status to set.
        attempts (int, optional): The number of attempts to set for a question.
        
    Returns:
        bool: True if the update was successful, False otherwise.
    """
    try:
        print(f"[DEBUG] update_user_progress called - User: {user_id}, Module: {module_id}")
        print(f"[DEBUG] Topic: {topic_id}, Question: {question_id}")
        print(f"[DEBUG] Progress: {progress}, Status: {status}, Attempts: {attempts}")
        
        client = get_mongo_client()
        db = client[st.secrets["MONGODB_DATABASE_NAME"]]
        user_progress_collection = db["user_module_progress"]
        
        # Check if document exists for this user
        doc = user_progress_collection.find_one({"user_id": user_id})
        print(f"[DEBUG] Found existing user document: {bool(doc)}")
        
        # Debug: Log the existing questions for this module
        if doc and "modules" in doc and module_id in doc.get("modules", {}):
            questions = doc["modules"][module_id].get("questions", {})
            print(f"[DEBUG] BEFORE UPDATE: Questions in module {module_id}: {list(questions.keys())}")
        
        if not doc:
            print(f"[DEBUG] Creating new user document for {user_id}")
            # Create new user document with default structure
            doc = {
                "user_id": user_id,
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
                "modules": {}
            }
            user_progress_collection.insert_one(doc)
        
        print(f"[DEBUG] module_id: {module_id}")
        print(f"[DEBUG] module_id type: {type(module_id)}")
        # Ensure the module exists in the user's document
        if str(module_id) not in doc.get("modules", {}):
            print(f"[DEBUG] Initializing module {module_id} for user {user_id}")
            update_result = user_progress_collection.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        f"modules.{module_id}": {
                            "progress": 0,
                            "status": "not_started",
                            "topics": {},
                            "questions": {}
                        }
                    }
                }
            )
            print(f"[DEBUG] Module initialized with result: {update_result.modified_count}")
            
        if topic_id is not None:
            # Set status based on progress if not explicitly provided
            if status is None and progress is not None:
                status = ["not_started", "in_progress", "completed"][progress]
            
            # Update the specific topic within the module
            update_result = user_progress_collection.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        f"modules.{module_id}.topics.{topic_id}": {
                            "progress": progress if progress is not None else 0,
                            "status": status if status is not None else "not_started",
                            "last_updated": datetime.now()
                        },
                        "updated_at": datetime.now()
                    }
                }
            )
            
            # Debug: Check the state after topic update
            updated_doc = user_progress_collection.find_one({"user_id": user_id})
            if updated_doc and "modules" in updated_doc and module_id in updated_doc.get("modules", {}):
                updated_questions = updated_doc["modules"][module_id].get("questions", {})
                print(f"[DEBUG] AFTER TOPIC UPDATE: Questions in module {module_id}: {list(updated_questions.keys())}")
            
            return update_result.modified_count > 0
            
        if question_id is not None:
            print(f"[DEBUG] Updating question {question_id} in module {module_id}")
            # Set status based on progress if not explicitly provided
            if status is None and progress is not None:
                status = ["not_started", "in_progress", "completed"][progress]
                print(f"[DEBUG] Derived status from progress: {status}")
            
            # Get current attempts count if not provided
            current_attempts = attempts
            if current_attempts is None and module_id in doc.get("modules", {}):
                question_data = doc["modules"][module_id].get("questions", {}).get(question_id, {})
                current_attempts = question_data.get("attempts", 0) + 1
                print(f"[DEBUG] Calculated attempts: {current_attempts}")
            
            # Update the specific question within the module using dot notation
            update_data = {
                f"modules.{module_id}.questions.{question_id}.status": status if status is not None else "not_started",
                f"modules.{module_id}.questions.{question_id}.last_attempt": datetime.now(),
                f"modules.{module_id}.questions.{question_id}.attempts": current_attempts,
                "updated_at": datetime.now()
            }
            
            # Set competency_level consistent with status or progress
            if progress is not None:
                update_data[f"modules.{module_id}.questions.{question_id}.competency_level"] = progress
            elif status is not None:
                # Derive competency_level from status
                competency_level = {"not_started": 0, "in_progress": 1, "completed": 2}.get(status, 0)
                update_data[f"modules.{module_id}.questions.{question_id}.competency_level"] = competency_level
            
            print(f"[DEBUG] Update data being sent: {update_data}")
            print(f"[DEBUG] Using $set operator to update only these fields")
            
            update_result = user_progress_collection.update_one(
                {"user_id": user_id},
                {"$set": update_data}
            )
            print(f"[DEBUG] Question update result - Modified count: {update_result.modified_count}")
            
            # Debug: Check the state after question update
            updated_doc = user_progress_collection.find_one({"user_id": user_id})
            if updated_doc and "modules" in updated_doc and module_id in updated_doc.get("modules", {}):
                updated_questions = updated_doc["modules"][module_id].get("questions", {})
                print(f"[DEBUG] AFTER QUESTION UPDATE: Questions in module {module_id}: {list(updated_questions.keys())}")
                
                # Compare before and after to see what changed
                if doc and "modules" in doc and module_id in doc.get("modules", {}):
                    before_keys = set(doc["modules"][module_id].get("questions", {}).keys())
                    after_keys = set(updated_questions.keys())
                    
                    if before_keys != after_keys:
                        print(f"[ERROR] Question keys changed in update_user_progress! Before: {before_keys}, After: {after_keys}")
                        print(f"[ERROR] Lost questions: {before_keys - after_keys}")
                        print(f"[ERROR] New questions: {after_keys - before_keys}")
            
            return update_result.modified_count > 0
        
        return False
        
    except Exception as e:
        if st.session_state.get('debug_mode', False):
            st.error(f"Debug: Error in update_user_progress: {str(e)}")
        print(f"[Error] Exception in update_user_progress: {str(e)}")
        return False

def update_competency(user_id, topic_name, level):
    """
    Update a user's competency level (0, 1, or 2) for a specific topic by name only.
    If the topic doesn't exist for the user, it will be created.
    
    Args:
        user_id (str): The user's ID
        topic_name (str): Name of the topic
        level (int): Competency level (0=not started, 1=in progress, 2=completed)
    """
    try:
        if st.session_state.get('debug_mode', False):
            st.write(f"Debug: Starting competency update for user {user_id}, topic {topic_name}, level {level}")
        
        client = get_mongo_client()
        db = client[st.secrets["MONGODB_DATABASE_NAME"]]
        user_progress_collection = db["user_module_progress"]
        
        # Map level directly to status
        status = ["not_started", "in_progress", "completed"][level]
        
        if st.session_state.get('debug_mode', False):
            st.write(f"Debug: Setting level {level} and status '{status}'")
        
        # Get modules data to find which module contains this topic
        modules_data = get_cached_modules_data()
        target_module_id = None
        
        # Find which module contains this topic
        for module in modules_data.get("modules", []):
            for topic in module.get("topics", []):
                if isinstance(topic, dict) and topic.get("name") == topic_name:
                    # Use the module's explicit index field
                    target_module_id = str(module.get("index", 0))
                    break
            if target_module_id:
                break
        
        if not target_module_id:
            print(f"[Error] Topic {topic_name} not found in any module")
            return False
            
        # Get the user's progress document
        user_doc = user_progress_collection.find_one({"user_id": user_id})
        
        if not user_doc:
            print(f"[Error] No document found for user {user_id}")
            # Create new user document with default structure
            user_doc = {
                "user_id": user_id,
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
                "modules": {}
            }
            user_progress_collection.insert_one(user_doc)
        
        # Ensure the module exists in the user's document
        if target_module_id not in user_doc.get("modules", {}):
            update_result = user_progress_collection.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        f"modules.{target_module_id}": {
                            "progress": 0,
                            "status": "not_started",
                            "topics": {},
                            "questions": {}
                        }
                    }
                }
            )
        
        # Update the specific topic within the module
        update_result = user_progress_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    f"modules.{target_module_id}.topics.{topic_name}": {
                        "progress": level,
                        "status": status,
                        "last_updated": datetime.now()
                    },
                    "updated_at": datetime.now()
                }
            }
        )
        
        if st.session_state.get('debug_mode', False):
            st.write(f"Debug: Update result: {update_result.modified_count} document(s) modified")
        
        return update_result.modified_count > 0
        
    except Exception as e:
        if st.session_state.get('debug_mode', False):
            st.error(f"Debug: Error in update_competency: {str(e)}")
        print(f"[Error] Exception in update_competency: {str(e)}")
        return False

def get_topic_competency(user_id, topic_name):
    """
    Get a user's competency level for a specific topic, using only topic name.
    
    Args:
        user_id (str): The user's ID
        topic_name (str): Name of the topic
        
    Returns:
        dict: A dictionary containing the topic's competency information
    """
    try:
        if st.session_state.get('debug_mode', False):
            st.write(f"Debug: Fetching competency for user {user_id}, topic {topic_name}")
        
        client = get_mongo_client()
        db = client[st.secrets["MONGODB_DATABASE_NAME"]]
        user_progress_collection = db["user_module_progress"]
        
        # Get modules data to find which module contains this topic
        modules_data = get_cached_modules_data()
        target_module_id = None
        
        # Find which module contains this topic
        for module in modules_data.get("modules", []):
            for topic in module.get("topics", []):
                if isinstance(topic, dict) and topic.get("name") == topic_name:
                    # Use the module's explicit index field
                    target_module_id = str(module.get("index", 0))
                    break
            if target_module_id:
                break
        
        if not target_module_id:
            print(f"[Error] Topic {topic_name} not found in any module")
            return {
                "topic_name": topic_name,
                "level": 0,
                "progress": 0,
                "status": "not_started",
                "last_updated": None
            }
        
        # Get user's progress document
        user_doc = user_progress_collection.find_one({"user_id": user_id})
        
        if not user_doc:
            if st.session_state.get('debug_mode', False):
                st.write(f"Debug: No progress data found for user {user_id}")
            return {
                "topic_name": topic_name,
                "level": 0,
                "progress": 0,
                "status": "not_started",
                "last_updated": None
            }
        
        # Get the topic data from the correct module
        module_data = user_doc.get("modules", {}).get(target_module_id, {})
        topic_data = module_data.get("topics", {}).get(topic_name, {})
        
        if not topic_data:
            if st.session_state.get('debug_mode', False):
                st.write(f"Debug: No data found for topic {topic_name}")
            return {
                "topic_name": topic_name,
                "level": 0,
                "progress": 0,
                "status": "not_started",
                "last_updated": None
            }
        
        result = {
            "topic_name": topic_name,
            "level": topic_data.get("progress", 0),
            "progress": topic_data.get("progress", 0),
            "status": topic_data.get("status", "not_started"),
            "last_updated": topic_data.get("last_updated")
        }
        
        if st.session_state.get('debug_mode', False):
            st.write("Debug: Found topic data:", result)
        
        return result
        
    except Exception as e:
        if st.session_state.get('debug_mode', False):
            st.error(f"Debug: Error in get_topic_competency: {str(e)}")
            st.exception(e)
        
        # Return default values on error
        return {
            "topic_name": topic_name,
            "level": 0,
            "progress": 0,
            "status": "not_started",
            "last_updated": None
        }

def batch_update_user_progress(user_id: str, updates: List[Dict[str, Any]]) -> bool:
    """
    Batch update user progress in MongoDB for multiple topics/questions at once.
    
    Args:
        user_id (str): The ID of the user.
        updates (List[Dict]): List of updates, each containing:
            - module_id (str): The module ID
            - topic_id (str, optional): The topic ID to update
            - question_id (str, optional): The question ID to update
            - progress (int, optional): The new progress value
            - status (str, optional): The new status
    """
    try:
        client = get_mongo_client()
        db = client[st.secrets["MONGODB_DATABASE_NAME"]]
        user_progress_collection = db["user_module_progress"]
        
        # Group updates by module for efficient processing
        module_updates = {}
        for update in updates:
            module_id = update.get("module_id")
            if module_id not in module_updates:
                module_updates[module_id] = []
            module_updates[module_id].append(update)
        
        # Process updates by module
        for module_id, module_updates_list in module_updates.items():
            # First, get the current user document to get current values
            user_doc = user_progress_collection.find_one({"user_id": user_id})
            if not user_doc:
                print(f"[Error] No document found for user {user_id}")
                return False
                
            # Prepare update data
            set_data = {
                "last_updated": datetime.now()
            }
            
            # Collect all updates for this module
            for update in module_updates_list:
                if "topic_id" in update:
                    topic_id = update["topic_id"]
                    if "progress" in update:
                        set_data[f"modules.{module_id}.topics.{topic_id}.progress"] = update["progress"]
                        if "status" not in update:
                            set_data[f"modules.{module_id}.topics.{topic_id}.status"] = ["not_started", "in_progress", "completed"][update["progress"]]
                    if "status" in update:
                        set_data[f"modules.{module_id}.topics.{topic_id}.status"] = update["status"]
                
                if "question_id" in update:
                    question_id = update["question_id"]
                    if "progress" in update:
                        progress_value = update["progress"]
                        set_data[f"modules.{module_id}.questions.{question_id}.progress"] = progress_value
                        # Set both status and competency_level for consistency
                        if "status" not in update:
                            set_data[f"modules.{module_id}.questions.{question_id}.status"] = ["not_started", "in_progress", "completed"][progress_value]
                        # Set competency_level based on progress
                        set_data[f"modules.{module_id}.questions.{question_id}.competency_level"] = progress_value
                    if "status" in update:
                        status = update["status"]
                        set_data[f"modules.{module_id}.questions.{question_id}.status"] = status
                        # Infer competency_level from status if not explicitly provided
                        if "competency_level" not in update:
                            competency_level = {"not_started": 0, "in_progress": 1, "completed": 2}.get(status, 0)
                            set_data[f"modules.{module_id}.questions.{question_id}.competency_level"] = competency_level
                    if "competency_level" in update:
                        set_data[f"modules.{module_id}.questions.{question_id}.competency_level"] = update["competency_level"]
                        # Update status based on competency_level if status not explicitly provided
                        if "status" not in update:
                            status = ["not_started", "in_progress", "completed"][min(update["competency_level"], 2)]
                            set_data[f"modules.{module_id}.questions.{question_id}.status"] = status
                    set_data[f"modules.{module_id}.questions.{question_id}.last_attempt"] = datetime.now()
                    
                    # Get current attempts count
                    current_attempts = 0
                    if module_id in user_doc.get("modules", {}):
                        question_data = user_doc["modules"][module_id].get("questions", {}).get(question_id, {})
                        current_attempts = question_data.get("attempts", 0)
                    
                    # Set the incremented value
                    set_data[f"modules.{module_id}.questions.{question_id}.attempts"] = current_attempts + 1
            
            # Execute the update
            if set_data:
                update_result = user_progress_collection.update_one(
                    {"user_id": user_id},
                    {"$set": set_data}
                )
                return update_result.modified_count > 0
            
            return False
    except Exception as e:
        print(f"[Error] Exception in batch_update_user_progress: {str(e)}")
        return False

def create_user_progress(user_id: str) -> bool:
    """
    Create a new user and initialize their progress data for all modules.
    Also adds the user to the users collection.
    
    Args:
        user_id (str): The ID of the user to create.
        
    Returns:
        bool: True if the user was created successfully, False otherwise.
    """
    try:
        client = get_mongo_client()
        db = client[st.secrets["MONGODB_DATABASE_NAME"]]
        user_progress_collection = db["user_module_progress"]
        users_collection = db["users"]
        
        # Check if user already exists in either collection
        existing_user_progress = user_progress_collection.find_one({"user_id": user_id})
        existing_user = users_collection.find_one({"login_code": user_id})
        
        if existing_user_progress or existing_user:
            print(f"[Error] User {user_id} already exists")
            return False
        
        # Create user in users collection
        user_data = {
            "login_code": user_id,
            "last_login": datetime.now(),
            "total_study_time": 0,
            "created_at": datetime.now()
        }
        users_collection.insert_one(user_data)
        
        # Get modules data to create appropriate progress structure
        modules_data = get_cached_modules_data()
        modules_list = modules_data.get("modules", [])
        
        # Create default progress structure for new user
        default_data = {
            "user_id": user_id,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
            "modules": {}
        }
        
        # Initialize modules with default values
        for module in modules_list:
            module_id = str(module.get("index", 0))
            default_data["modules"][module_id] = {
                "progress": 0,
                "status": "not_started",
                "topics": {},
                "questions": {}
            }
            
            # Initialize topics
            for topic in module.get("topics", []):
                topic_name = topic.get("name")
                default_data["modules"][module_id]["topics"][topic_name] = {
                    "progress": 0,
                    "status": "not_started"
                }
            
            # Initialize questions with assessment fields
            tutorial_questions = module.get("tutorial_questions", [])
            for idx, _ in enumerate(tutorial_questions):
                question_id = str(idx + 1)
                default_data["modules"][module_id]["questions"][question_id] = {
                    # Basic progress fields
                    "status": "not_started",
                    "attempts": 0,
                    "last_attempt": None,
                    # Assessment fields
                    "competency_level": 0,
                    "feedback": "",
                    "response_text": "",
                    "input_image_data": [],
                    "last_assessed": None
                }
        
        # Insert default progress data
        user_progress_collection.insert_one(default_data)
        
        print(f"[Success] Created user {user_id} with initialized progress data")
        return True
    except Exception as e:
        print(f"[Error] Exception in create_user_progress: {str(e)}")
        return False

def list_users() -> List[Dict]:
    """
    Retrieve all users from the user_module_progress collection.
    Each user may have multiple entries (one per module), but we'll show each user only once in the UI.
    
    Returns:
        List[Dict]: A list of dictionaries containing user information.
    """
    try:
        client = get_mongo_client()
        db = client[st.secrets["MONGODB_DATABASE_NAME"]]
        user_progress_collection = db["user_module_progress"]
        
        # Get all users
        users = list(user_progress_collection.find({}, {
            "user_id": 1,
            "created_at": 1,
            "updated_at": 1,
            "_id": 0
        }))
        
        # Use a dictionary to track unique user_ids for UI display only
        unique_users = {}
        for user in users:
            user_id = user.get("user_id", "Unknown")
            if user_id not in unique_users:
                unique_users[user_id] = {
                    "user_id": user_id,
                    "created_at": user.get("created_at", datetime.now()).strftime('%Y-%m-%d %H:%M:%S'),
                    "updated_at": user.get("updated_at", datetime.now()).strftime('%Y-%m-%d %H:%M:%S')
                }
        
        # Convert dictionary to list
        formatted_users = list(unique_users.values())
        
        return formatted_users
    except Exception as e:
        print(f"[Error] Exception in list_users: {str(e)}")
        return []

def delete_user(user_id: str) -> bool:
    """
    Delete a user and all their progress data from both users and user_module_progress collections.
    
    Args:
        user_id (str): The ID of the user to delete.
        
    Returns:
        bool: True if the user was successfully deleted from either collection, False otherwise.
        
    Note:
        This function will delete all entries for a user from both collections.
        The user is considered deleted if removed from either collection successfully.
    """
    try:
        client = get_mongo_client()
        db = client[st.secrets["MONGODB_DATABASE_NAME"]]
        
        # Delete from user_module_progress collection
        progress_result = db["user_module_progress"].delete_many({"user_id": user_id})
        
        # Delete from users collection
        users_result = db["users"].delete_many({"login_code": user_id})
        
        # Return True if user was deleted from either collection
        return progress_result.deleted_count > 0 or users_result.deleted_count > 0
    except Exception as e:
        print(f"Error deleting user: {str(e)}")
        return False

def get_user_progress_details(user_id: str) -> Dict:
    """
    Retrieve detailed progress information for a specific user.
    Each user may have multiple entries (one per module).
    
    Args:
        user_id (str): The ID of the user.
        
    Returns:
        Dict: A dictionary containing the user's detailed progress information.
    """
    try:
        client = get_mongo_client()
        db = client[st.secrets["MONGODB_DATABASE_NAME"]]
        user_progress_collection = db["user_module_progress"]
        
        # Get all user progress entries for this user
        user_entries = list(user_progress_collection.find({"user_id": user_id}))
        
        if not user_entries:
            print(f"[Error] User {user_id} not found")
            return {}
        
        # Format the data for display
        formatted_data = {
            "user_id": user_id,
            "total_modules": len(user_entries),
            "entries": []
        }
        
        # Add each module entry
        for entry in user_entries:
            module_entry = {
                "created_at": entry.get("created_at", datetime.now()).strftime('%Y-%m-%d %H:%M:%S'),
                "updated_at": entry.get("updated_at", datetime.now()).strftime('%Y-%m-%d %H:%M:%S'),
                "modules": {}
            }
            
            # Format module data
            for module_id, module_data in entry.get("modules", {}).items():
                module_entry["modules"][module_id] = {
                    "progress": module_data.get("progress", 0),
                    "status": module_data.get("status", "not_started"),
                    "topics": module_data.get("topics", {}),
                    "questions": module_data.get("questions", {})
                }
            
            formatted_data["entries"].append(module_entry)
        
        return formatted_data
    except Exception as e:
        print(f"[Error] Exception in get_user_progress_details: {str(e)}")
        return {}

def save_assessment_results(user_id: str, module_id: str, question_index: int,
                           competency_level: int, feedback: str, status: str,
                           response_text: str,
                           input_image_data: Optional[List[bytes]] = None) -> bool:
    """
    Save assessment results for a specific question to the database.
    
    Args:
        user_id: The user's ID
        module_id: The module ID (as a string)
        question_index: The zero-based index of the question
        competency_level: The competency level (0, 1, or 2)
        feedback: Feedback for the student
        status: Question status (completed, in_progress)
        response_text: Raw response text from the assessment API
        input_image_data: List of image bytes provided by the user
        
    Returns:
        bool: True if the operation was successful, False otherwise
    """
    try:
        print(f"[DEBUG] Saving assessment results - User: {user_id}, Module: {module_id}, Question: {question_index}")
        print(f"[DEBUG] Competency Level: {competency_level}, Status: {status}")
        
        # Convert question index to question_id format (1-based) for MongoDB storage
        question_id = str(int(question_index) + 1)
        
        client = get_mongo_client()
        db = client[st.secrets["MONGODB_DATABASE_NAME"]]
        progress_collection = db["user_module_progress"]

        # Convert image bytes to BSON Binary format
        bson_image_data = []
        if input_image_data:
            bson_image_data = [Binary(img_bytes) for img_bytes in input_image_data]
            print(f"[DEBUG] Processed {len(bson_image_data)} images")

        # Get current attempts count from the user document
        user_doc = progress_collection.find_one({"user_id": user_id})
        current_attempts = 0
        
        # Convert module_id to string and handle potential module_id format differences (0-based vs 1-based indexing)
        module_key = str(module_id)
        if user_doc and module_key.isdigit() and all(k.isdigit() for k in user_doc.get("modules", {}).keys()):
            # If assessor is using 0-based but db uses 1-based, add 1
            if user_doc.get("modules", {}).get(module_key) is None and user_doc.get("modules", {}).get(str(int(module_key)+1)) is not None:
                module_key = str(int(module_key)+1)
                print(f"[DEBUG] Adjusted module_id from {module_key} to {module_key}")
        
        # Debug information about the current state
        if user_doc and "modules" in user_doc and module_key in user_doc.get("modules", {}):
            print(f"[DEBUG] All modules: {list(user_doc['modules'].keys())}")
            all_questions = user_doc["modules"][module_key].get("questions", {})
            print(f"[DEBUG] Current questions in module {module_key}: {list(all_questions.keys())}")
            
            if question_id in all_questions:
                current_attempts = all_questions[question_id].get("attempts", 0)
                print(f"[DEBUG] Current attempts from DB: {current_attempts}")
                print(f"[DEBUG] Current question state: {all_questions[question_id]}")
        else:
            print(f"[WARNING] User document or module {module_key} not found for user {user_id}. This might be a new user or module.")
        
        # Create the question update data
        question_data = {
            "status": status,
            "competency_level": competency_level,
            "feedback": feedback,
            "response_text": response_text,
            "last_assessed": datetime.now(),
            "attempts": current_attempts + 1,
            "last_attempt": datetime.now()
        }
        
        # Only add image data if it exists
        if bson_image_data:
            question_data["input_image_data"] = bson_image_data
        
        print(f"[DEBUG] New question data: {question_data}")
        
        # Create a specific update for just this question using the merge operator $set
        update_fields = {
            "updated_at": datetime.now()
        }
        
        # Use dot notation for each field to prevent overwriting the entire questions object
        for field, value in question_data.items():
            update_fields[f"modules.{module_key}.questions.{question_id}.{field}"] = value
        
        print(f"[DEBUG] Update fields: {update_fields}")
        
        # Update only this specific question without affecting others
        update_result = progress_collection.update_one(
            {"user_id": user_id},
            {"$set": update_fields}
        )
        
        print(f"[DEBUG] MongoDB update result - Matched: {update_result.matched_count}, Modified: {update_result.modified_count}")
        
        # Verify the update didn't overwrite other questions
        if st.session_state.get('debug_mode', False):
            after_doc = progress_collection.find_one({"user_id": user_id})
            if after_doc and "modules" in after_doc and module_key in after_doc["modules"]:
                after_questions = after_doc["modules"][module_key].get("questions", {})
                st.write(f"Debug: Questions after update: {list(after_questions.keys())}")
        
        return update_result.matched_count > 0
        
    except Exception as e:
        print(f"[ERROR] Failed to save assessment results: {str(e)}")
        if st.session_state.get('debug_mode', False):
            st.error(f"Debug: Error in save_assessment_results: {str(e)}")
        return False

def get_assessment_results(user_id: str, module_id: str, question_index: int) -> Optional[Dict]:
    """
    Retrieve assessment results for a specific question from the database.
    
    Args:
        user_id: The user's ID
        module_id: The module ID (as a string)
        question_index: The zero-based index of the question
        
    Returns:
        Optional[Dict]: Assessment results if found, None otherwise
    """
    try:
        # Convert question index to question_id format (1-based) for MongoDB storage
        question_id = str(int(question_index) + 1)
        
        client = get_mongo_client()
        db = client[st.secrets["MONGODB_DATABASE_NAME"]]
        progress_collection = db["user_module_progress"]
        
        # Find the user's progress document
        user_doc = progress_collection.find_one({"user_id": user_id})
        
        if user_doc:
            # Convert module_id to string and handle potential module_id format differences (0-based vs 1-based indexing)
            module_key = str(module_id)
            if module_key.isdigit() and all(k.isdigit() for k in user_doc.get("modules", {}).keys()):
                # If assessor is using 0-based but db uses 1-based, add 1
                if user_doc.get("modules", {}).get(module_key) is None and user_doc.get("modules", {}).get(str(int(module_key)+1)) is not None:
                    module_key = str(int(module_key)+1)
            
            # Extract question data from the nested structure
            question_data = user_doc.get("modules", {}).get(module_key, {}).get("questions", {}).get(question_id)
            
            if question_data:
                # Convert datetime objects to strings for JSON serialization
                if "last_assessed" in question_data and isinstance(question_data["last_assessed"], datetime):
                    question_data["last_assessed"] = question_data["last_assessed"].isoformat()
                if "last_attempt" in question_data and isinstance(question_data["last_attempt"], datetime):
                    question_data["last_attempt"] = question_data["last_attempt"].isoformat()
                return question_data
            
        return None
    except Exception as e:
        print(f"[Error] Failed to retrieve assessment results: {str(e)}")
        if st.session_state.get('debug_mode', False):
            st.error(f"Debug: Error in get_assessment_results: {str(e)}")
        return None

def get_module_data(user_id: str, module_id: str) -> Dict:
    """
    Get all module data including progress and assessments in one query.
    
    Args:
        user_id (str): The user's ID
        module_id (str): The module ID (adjusted to work with 0-based indexes)
        
    Returns:
        Dict: A dictionary containing progress and assessment information
    """
    try:
        client = get_mongo_client()
        db = client[st.secrets["MONGODB_DATABASE_NAME"]]
        
        # Get user progress document
        user_doc = db["user_module_progress"].find_one({"user_id": user_id})
        
        if not user_doc:
            return {"progress": {}, "assessments": {}, "topics": {}}
        
        # Convert module_id to correct format if needed
        # Check if module_id needs to be adjusted to match the database format
        module_key = str(module_id)
        if module_key.isdigit() and all(k.isdigit() for k in user_doc.get("modules", {}).keys()):
            # If assessor is using 0-based but db uses 1-based, add 1
            if user_doc.get("modules", {}).get(module_id) is None and user_doc.get("modules", {}).get(str(int(module_id)+1)) is not None:
                module_key = str(int(module_id)+1)
        
        # Extract progress data for the specific module
        progress_data = user_doc.get("modules", {}).get(module_key, {})
        
        # Extract topics and questions data separately
        topics_data = progress_data.get("topics", {})
        questions_data = progress_data.get("questions", {})
        
        # Create a progress dict without topics and questions to avoid redundancy
        progress_without_topics_questions = {k: v for k, v in progress_data.items() 
                                          if k not in ["topics", "questions"]}
        
        return {
            "progress": progress_without_topics_questions,
            "assessments": questions_data,  # Questions contain assessment data
            "topics": topics_data  # Topics data is now separate
        }
    except Exception as e:
        print(f"[Error] Error loading module data: {str(e)}")
        if st.session_state.get('debug_mode', False):
            st.error(f"Debug: Error in get_module_data: {str(e)}")
        return {"progress": {}, "assessments": {}, "topics": {}} 