import streamlit as st
from datetime import datetime
from .base import get_mongo_client

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
            # Get modules data to create appropriate default progress structure
            from .modules import get_modules_data
            modules_data = get_modules_data()
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
                module_id = str(modules_list.index(module) + 1)
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
    Update user progress in MongoDB using the new user_module_progress collection.
    
    Args:
        user_id (str): The ID of the user.
        module_id (str): The ID of the module.
        topic_id (str, optional): The ID of the topic to update.
        question_id (str, optional): The ID of the question to update.
        progress (int, optional): The new progress value (0=not started, 1=in progress, 2=completed).
        status (str, optional): The new status to set.
    """
    try:
        client = get_mongo_client()
        db = client["funce_db"]
        user_progress_collection = db["user_module_progress"]
        
        update_data = {
            "last_updated": datetime.now()
        }
        
        if topic_id is not None:
            if progress is not None:
                update_data["topics.$[topic].progress"] = progress
                # Set status based on progress if not explicitly provided
                if status is None:
                    status = ["not_started", "in_progress", "completed"][progress]
            if status is not None:
                update_data["topics.$[topic].status"] = status
        
        if question_id is not None:
            if progress is not None:
                update_data["tutorial_questions.$[question].progress"] = progress
                # Set status based on progress if not explicitly provided
                if status is None:
                    status = ["not_started", "in_progress", "completed"][progress]
            if status is not None:
                update_data["tutorial_questions.$[question].status"] = status
            update_data["tutorial_questions.$[question].last_attempt"] = datetime.now()
            update_data["tutorial_questions.$[question].attempts"] = {"$inc": 1}
        
        if update_data:
            array_filters = []
            if topic_id:
                array_filters.append({"topic.topic_id": topic_id})
            if question_id:
                array_filters.append({"question.question_id": question_id})
            
            user_progress_collection.update_one(
                {"user_id": user_id},
                {"$set": update_data},
                array_filters=array_filters
            )
            
            if st.session_state.get('debug_mode', False):
                st.write(f"Debug: Updated progress for user {user_id}")
    except Exception as e:
        if st.session_state.get('debug_mode', False):
            st.error(f"Debug: Error in update_user_progress: {str(e)}")
        else:
            st.error("Error updating user progress")

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
        from .modules import get_modules_data
        modules_data = get_modules_data()
        target_module_id = None
        
        # Find which module contains this topic
        for module in modules_data.get("modules", []):
            for topic in module.get("topics", []):
                if isinstance(topic, dict) and topic.get("name") == topic_name:
                    target_module_id = str(modules_data["modules"].index(module) + 1)
                    break
            if target_module_id:
                break
        
        if not target_module_id:
            print(f"[Error] Topic {topic_name} not found in any module")
            return False
        
        # Update the topic in the correct module
        result = user_progress_collection.update_one(
            {
                "user_id": user_id,
                f"modules.{target_module_id}.topics.{topic_name}": {"$exists": True}
            },
            {
                "$set": {
                    f"modules.{target_module_id}.topics.{topic_name}.progress": level,
                    f"modules.{target_module_id}.topics.{topic_name}.status": status,
                    f"modules.{target_module_id}.topics.{topic_name}.last_updated": datetime.now()
                }
            }
        )
        
        # If no topic was updated (modified_count == 0), the topic doesn't exist, so create it
        if result.modified_count == 0:
            if st.session_state.get('debug_mode', False):
                st.write(f"Debug: Topic {topic_name} not found for user {user_id}. Creating new topic.")
            
            # Check if user exists
            user_exists = user_progress_collection.find_one({"user_id": user_id})
            
            if user_exists:
                # Create the topic in the correct module
                new_topic = {
                    "progress": level,
                    "status": status,
                    "last_updated": datetime.now()
                }
                
                result = user_progress_collection.update_one(
                    {"user_id": user_id},
                    {
                        "$set": {
                            f"modules.{target_module_id}.topics.{topic_name}": new_topic
                        }
                    }
                )
        
        return result.modified_count > 0
        
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
        
        # Find by topic name only
        user_data = user_progress_collection.find_one(
            {
                "user_id": user_id,
                "topics.name": topic_name
            },
            {
                "topics.$": 1
            }
        )
        
        if st.session_state.get('debug_mode', False):
            st.write("Debug: Raw user data from MongoDB:", user_data)
        
        if user_data and user_data.get("topics"):
            topic_data = user_data["topics"][0]
            # Progress is now directly the level (0, 1, 2)
            progress = topic_data.get("progress", 0)
            
            result = {
                "topic_name": topic_name,
                "level": progress,
                "progress": progress,
                "status": topic_data.get("status", "not_started"),
                "last_updated": topic_data.get("last_updated")
            }
            
            if st.session_state.get('debug_mode', False):
                st.write("Debug: Found topic data:", result)
            
            return result
        
        # Return default values if topic not found
        default_result = {
            "topic_name": topic_name,
            "level": 0,
            "progress": 0,
            "status": "not_started",
            "last_updated": None
        }
        
        if st.session_state.get('debug_mode', False):
            st.write("Debug: No topic data found, returning default values")
        
        return default_result
        
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