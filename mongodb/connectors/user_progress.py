import streamlit as st
from datetime import datetime
from .base import get_mongo_client
from typing import List, Dict, Any
from .modules import get_cached_modules_data

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
        db = client["funce_db"]
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

def update_user_progress(user_id, module_id, topic_id=None, question_id=None, progress=None, status=None):
    """
    Update user progress in MongoDB using the user_module_progress collection.
    The data structure has topics and questions stored as arrays.
    
    Args:
        user_id (str): The ID of the user.
        module_id (str): The ID of the module.
        topic_id (str, optional): The ID of the topic to update.
        question_id (str, optional): The ID of the question to update.
        progress (int, optional): The new progress value (0=not started, 1=in progress, 2=completed).
        status (str, optional): The new status to set.
        
    Returns:
        bool: True if the update was successful, False otherwise.
    """
    try:
        client = get_mongo_client()
        db = client["funce_db"]
        user_progress_collection = db["user_module_progress"]
        
        # Check if document exists for this user and module
        doc = user_progress_collection.find_one({
            "user_id": user_id,
            "module_id": module_id
        })
        
        if not doc:
            print(f"[Error] No document found for user {user_id} and module {module_id}")
            return False
            
        if topic_id is not None:
            # Set status based on progress if not explicitly provided
            if status is None and progress is not None:
                status = ["not_started", "in_progress", "completed"][progress]
            
            # Try to find and update existing topic
            result = user_progress_collection.update_one(
                {
                    "user_id": user_id,
                    "module_id": module_id,
                    "topics": {
                        "$elemMatch": {
                            "topic_id": topic_id
                        }
                    }
                },
                {
                    "$set": {
                        "topics.$.progress": progress,
                        "topics.$.status": status,
                        "last_updated": datetime.now()
                    }
                }
            )
            
            if result.matched_count == 0:
                # Topic not found, add new topic to array
                modules_data = get_cached_modules_data()
                
                # Find topic name from modules data
                topic_name = None
                for module in modules_data.get("modules", []):
                    if str(modules_data["modules"].index(module) + 1) == module_id:
                        for topic in module.get("topics", []):
                            if isinstance(topic, dict) and topic.get("topic_id") == topic_id:
                                topic_name = topic.get("name")
                                break
                        break
                
                if not topic_name:
                    print(f"[Error] Could not find topic name for topic_id {topic_id}")
                    return False
                
                result = user_progress_collection.update_one(
                    {
                        "user_id": user_id,
                        "module_id": module_id
                    },
                    {
                        "$push": {
                            "topics": {
                                "topic_id": topic_id,
                                "name": topic_name,
                                "progress": progress if progress is not None else 0,
                                "status": status if status is not None else "not_started"
                            }
                        },
                        "$set": {
                            "last_updated": datetime.now()
                        }
                    }
                )
            
            return result.modified_count > 0
            
        if question_id is not None:
            # Set status based on progress if not explicitly provided
            if status is None and progress is not None:
                status = ["not_started", "in_progress", "completed"][progress]
            
            # Try to find and update existing question
            result = user_progress_collection.update_one(
                {
                    "user_id": user_id,
                    "module_id": module_id,
                    "tutorial_questions": {
                        "$elemMatch": {
                            "question_id": question_id
                        }
                    }
                },
                {
                    "$set": {
                        "tutorial_questions.$.progress": progress,
                        "tutorial_questions.$.status": status,
                        "tutorial_questions.$.last_attempt": datetime.now()
                    },
                    "$inc": {
                        "tutorial_questions.$.attempts": 1
                    }
                }
            )
            
            if result.matched_count == 0:
                # Question not found, add new question to array
                result = user_progress_collection.update_one(
                    {
                        "user_id": user_id,
                        "module_id": module_id
                    },
                    {
                        "$push": {
                            "tutorial_questions": {
                                "question_id": question_id,
                                "progress": progress if progress is not None else 0,
                                "status": status if status is not None else "not_started",
                                "last_attempt": datetime.now(),
                                "attempts": 1
                            }
                        },
                        "$set": {
                            "last_updated": datetime.now()
                        }
                    }
                )
            
            return result.modified_count > 0
        
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
        db = client["funce_db"]
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
        db = client["funce_db"]
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
        db = client["funce_db"]
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
            update_data = {
                "last_updated": datetime.now()
            }
            array_filters = []
            
            # Collect all updates for this module
            for update in module_updates_list:
                if "topic_id" in update:
                    topic_id = update["topic_id"]
                    if "progress" in update:
                        update_data[f"topics.$[topic_{topic_id}].progress"] = update["progress"]
                        if "status" not in update:
                            update_data[f"topics.$[topic_{topic_id}].status"] = ["not_started", "in_progress", "completed"][update["progress"]]
                    if "status" in update:
                        update_data[f"topics.$[topic_{topic_id}].status"] = update["status"]
                    array_filters.append({f"topic_{topic_id}.topic_id": topic_id})
                
                if "question_id" in update:
                    question_id = update["question_id"]
                    if "progress" in update:
                        update_data[f"tutorial_questions.$[question_{question_id}].progress"] = update["progress"]
                        if "status" not in update:
                            update_data[f"tutorial_questions.$[question_{question_id}].status"] = ["not_started", "in_progress", "completed"][update["progress"]]
                    if "status" in update:
                        update_data[f"tutorial_questions.$[question_{question_id}].status"] = update["status"]
                    update_data[f"tutorial_questions.$[question_{question_id}].last_attempt"] = datetime.now()
                    update_data[f"tutorial_questions.$[question_{question_id}].attempts"] = {"$inc": 1}
                    array_filters.append({f"question_{question_id}.question_id": question_id})
            
            if update_data:
                user_progress_collection.update_one(
                    {"user_id": user_id},
                    {"$set": update_data},
                    array_filters=array_filters
                )
        
        if st.session_state.get('debug_mode', False):
            st.write(f"Debug: Batch updated progress for user {user_id}")
        return True
    except Exception as e:
        if st.session_state.get('debug_mode', False):
            st.error(f"Debug: Error in batch_update_user_progress: {str(e)}")
        else:
            st.error("Error updating user progress")
        return False

def create_user(user_id: str) -> bool:
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
        db = client["funce_db"]
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
            
            # Initialize questions - handle both dict and list formats
            tutorial_questions = module.get("tutorial_questions", [])
            for idx, _ in enumerate(tutorial_questions):
                question_id = str(idx + 1)
                default_data["modules"][module_id]["questions"][question_id] = {
                    "status": "not_started",
                    "attempts": 0,
                    "last_attempt": None
                }
        
        # Insert default progress data
        user_progress_collection.insert_one(default_data)
        
        print(f"[Success] Created user {user_id} with initialized progress data")
        return True
    except Exception as e:
        print(f"[Error] Exception in create_user: {str(e)}")
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
        db = client["funce_db"]
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
        db = client["funce_db"]
        
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
        db = client["funce_db"]
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