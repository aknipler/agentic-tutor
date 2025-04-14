"""Handlers for competency-related operations"""
from typing import Dict, Any, Optional, Union, List
import streamlit as st
import json
from mongodb.connectors import (
    get_topic_competency,
    update_competency,
    get_user_progress,
    update_user_progress
)
from ..config.settings import COMPETENCY_LEVELS, MODULE_TITLES
from utils.cache import get_cached_modules_data

def batch_update_competencies(user_id: str, updates: List[Dict[str, Any]]) -> str:
    """Batch update multiple competencies at once"""
    try:
        # Get user progress data
        progress_data = get_user_progress(user_id)
        
        if not progress_data:
            return "Failed to update competencies - No user data found"
        
        # Group updates by module
        module_updates = {}
        for update in updates:
            topic_name = update.get("topic_name")
            level = update.get("level")
            reason = update.get("reason")
            
            if topic_name is None or level is None:
                continue
                
            # Find which module contains this topic
            target_module_id = None
            for module_id, module_data in progress_data.get("modules", {}).items():
                topics = module_data.get("topics", {})
                if topic_name in topics:
                    target_module_id = module_id
                    break
            
            if target_module_id is None:
                continue
                
            if target_module_id not in module_updates:
                module_updates[target_module_id] = []
            
            module_updates[target_module_id].append({
                "topic_name": topic_name,
                "level": level,
                "reason": reason
            })
        
        # Process updates by module
        for module_id, module_updates_list in module_updates.items():
            for update in module_updates_list:
                success = update_user_progress(
                    user_id=user_id,
                    module_id=module_id,
                    topic_id=update["topic_name"],
                    progress=update["level"]
                )
                
                if not success:
                    return f"Failed to update competency for {update['topic_name']}"
        
        # Invalidate caches after updates
        from ..interface import invalidate_caches
        invalidate_caches()
        
        return "Successfully updated competencies"
        
    except Exception as e:
        return f"Failed to update competencies - Error: {str(e)}"

def handle_competency_update(args: Dict[str, Any], user_id: str) -> str:
    """Handle competency update function calls"""
    topic_name = args.get("topic_name")
    level = args.get("level")
    reason = args.get("reason")
    
    print(f"[Competency Update] Starting update for topic: {topic_name}, level: {level}, reason: {reason}")
    
    # Check if this topic was already updated in this session to prevent loops
    update_key = f"competency_update_{topic_name}"
    if update_key in st.session_state and st.session_state[update_key] == level:
        print(f"[Competency Update] Topic {topic_name} already updated to level {level} in this session, skipping")
        return f"Skipping duplicate competency update for {topic_name} to level {level}"
    
    if topic_name is not None and level is not None:
        try:
            # Get modules data to find which module contains this topic
            from mongodb.connectors import get_modules_data
            modules_data = get_modules_data()
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
            
            if target_module_id is None:
                print(f"[Competency Update Error] Topic {topic_name} not found in any module")
                return f"Failed to update competency for {topic_name} - Topic not found"
            
            print(f"[Competency Update] Found target module: {target_module_id}")
            
            # Update the topic's competency using the new update_competency function
            from mongodb.connectors import update_competency
            success = update_competency(
                user_id=user_id,
                topic_name=topic_name,
                level=level
            )
            
            if success:
                print(f"[Competency Update Success] Topic: {topic_name}, New Level: {level}, Reason: {reason}")
                # Store this update in session state to prevent loops
                st.session_state[update_key] = level
                # Invalidate caches after update
                from ..interface import invalidate_caches
                invalidate_caches()
                return f"Successfully updated competency for {topic_name} to level {level}"
            else:
                print(f"[Competency Update Failed] Topic: {topic_name}, Attempted Level: {level}")
                return f"Failed to update competency for {topic_name}"
                
        except Exception as e:
            print(f"[Competency Update Error] Exception: {str(e)}")
            return f"Failed to update competency for {topic_name} - Error: {str(e)}"
            
    print("[Competency Update Error] Invalid parameters")
    return "Invalid competency update parameters"

def handle_competency_check(args: Dict[str, Any], user_id: str) -> str:
    """Handle competency check function calls"""
    topic_name = args.get("topic_name")
    print(f"[Competency Check] Checking competency for topic: {topic_name}")
    
    if topic_name is not None:
        try:
            # Get modules data from cache
            from ..interface import get_cached_modules_data, get_cached_user_progress
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
            
            if target_module_id is None:
                print(f"[Competency Check Error] Topic {topic_name} not found in any module")
                return json.dumps({
                    "topic_name": topic_name,
                    "progress": 0,
                    "level": 0
                })
            
            # Get user progress data from cache
            progress_data = get_cached_user_progress()
            
            if not progress_data:
                print(f"[Competency Check Error] No progress data found for user: {user_id}")
                return json.dumps({
                    "topic_name": topic_name,
                    "progress": 0,
                    "level": 0
                })
            
            # Get the topic data from the correct module
            module_data = progress_data.get("modules", {}).get(target_module_id, {})
            topic_data = module_data.get("topics", {}).get(topic_name, {})
            
            if topic_data:
                progress = topic_data.get("progress", 0)
                print(f"[Competency Check] Found topic data: {topic_data}, progress: {progress}")
                return json.dumps({
                    "topic_name": topic_name,
                    "progress": progress,
                    "level": progress
                })
            
            # Topic not found in user progress - initialize it
            print(f"[Competency Check] Topic {topic_name} not found in user progress, initializing it")
            
            # Initialize the topic with progress level 0
            success = update_competency(
                user_id=user_id,
                topic_name=topic_name,
                level=0
            )
            
            if success:
                print(f"[Competency Check] Successfully initialized topic {topic_name}")
                return json.dumps({
                    "topic_name": topic_name,
                    "progress": 0,
                    "level": 0
                })
            
            print(f"[Competency Check] Failed to initialize topic {topic_name}")
            return json.dumps({
                "topic_name": topic_name,
                "progress": 0,
                "level": 0
            })
            
        except Exception as e:
            print(f"[Competency Check Error] Exception: {str(e)}")
            return json.dumps({
                "topic_name": topic_name,
                "progress": 0,
                "level": 0
            })
            
    print("[Competency Check Error] Invalid topic name")
    return "Invalid topic name provided"

def get_module_progress_summary(module: Union[str, int]) -> Optional[str]:
    """Get the user's progress summary for topics in the current module."""
    try:
        user_id = st.session_state.user_id
        print(f"[Progress Summary] Getting progress for user: {user_id}, module: {module}")
        
        # Get user progress data from cache
        from ..interface import get_cached_user_progress, get_cached_modules_data
        progress_data = get_cached_user_progress()
        
        if not progress_data:
            print("[Progress Summary] No progress data found")
            return None
            
        modules_data = get_cached_modules_data()
        module_id = str(module)
        print(f"[Progress Summary] Module ID: {module_id}")
        
        # Get the module's topics from modules_data
        if "modules" in modules_data and isinstance(modules_data["modules"], list):
            # Find module by title based on module ID
            module_data = None
            target_title = MODULE_TITLES.get(module_id)
            print(f"[Progress Summary] Looking for module with title: {target_title}")
            
            if not target_title:
                print("[Progress Summary] No title found for module ID")
                return None
                
            # Find the module with matching title
            for m in modules_data["modules"]:
                if m.get("title") == target_title:
                    module_data = m
                    break
            
            if module_data:
                topics = module_data.get("topics", [])
                print(f"[Progress Summary] Found topics for module: {topics}")
            else:
                print("[Progress Summary] No module data found")
                return None
        
        # Get user's progress for this module
        module_progress = progress_data.get("modules", {}).get(str(module_data.get("index", 0)), {})
        topics_progress = module_progress.get("topics", {})
        print(f"[Progress Summary] Module progress data: {module_progress}")
        
        progress_summary = []
        for topic in topics:
            if isinstance(topic, dict):
                topic_name = topic.get('name', 'Unnamed Topic')
            else:
                topic_name = str(topic)
            print(f"[Progress Summary] Processing topic: {topic_name}")
            
            # Get topic progress from the new structure
            topic_data = topics_progress.get(topic_name, {})
            print(f"[Progress Summary] Topic data found: {topic_data}")
            
            progress = topic_data.get("progress", 0)
            status = COMPETENCY_LEVELS.get(progress, "🔴")
            progress_summary.append(f"{status} {topic_name}")
            print(f"[Progress Summary] Added to summary: {status} {topic_name}")
        
        result = "\n\n".join(progress_summary)
        return result
    except Exception as e:
        print(f"[Progress Summary Error] Exception: {str(e)}")
        if st.session_state.get("debug_mode", False):
            st.error(f"Error getting user progress: {str(e)}")
        return None

def get_next_non_competent_topic(module_id: Union[str, int]) -> Optional[Dict[str, Any]]:
    """Get the next topic that the user hasn't completed yet."""
    try:
        user_id = st.session_state.user_id
        print(f"[Next Topic] Getting next topic for user: {user_id}, module: {module_id}")
        
        # Get modules data from cache
        from ..interface import get_cached_modules_data, get_cached_user_progress
        modules_data = get_cached_modules_data()
        module_id_str = str(module_id)
        print(f"[Next Topic] Module ID string: {module_id_str}")
        
        if "modules" not in modules_data or not isinstance(modules_data["modules"], list):
            print(f"[Next Topic Error] Invalid modules data structure: {modules_data}")
            return None
            
        # Find module by title based on module ID
        module_data = None
        target_title = MODULE_TITLES.get(module_id_str)
        print(f"[Next Topic] Looking for module with title: {target_title}")
        
        if not target_title:
            print(f"[Next Topic Error] No title found for module ID: {module_id_str}")
            return None
            
        # Find the module with matching title
        for m in modules_data["modules"]:
            if m.get("title") == target_title:
                module_data = m
                break
        
        if not module_data:
            print(f"[Next Topic Error] Module not found for title: {target_title}")
            return None
            
        topics = module_data.get("topics", [])
        print(f"[Next Topic] Found topics for module: {topics}")
        
        if not topics:
            print(f"[Next Topic Error] No topics found for module: {target_title}")
            return None
            
        # Get user's progress for this module
        progress_data = get_cached_user_progress()
        if not progress_data:
            print(f"[Next Topic Error] No progress data found for user: {user_id}")
            return None
            
        # Get the module's progress data using its index
        module_index = str(module_data.get("index", 0))
        module_progress = progress_data.get("modules", {}).get(module_index, {})
        topics_progress = module_progress.get("topics", {})
        print(f"[Next Topic] Module progress data: {module_progress}")
        
        # Find the first topic that isn't completed
        for topic in topics:
            if isinstance(topic, dict):
                topic_name = topic.get('name', 'Unnamed Topic')
            else:
                topic_name = str(topic)
            print(f"[Next Topic] Checking topic: {topic_name}")
            
            # Get topic progress from the new structure
            topic_data = topics_progress.get(topic_name, {})
            print(f"[Next Topic] Topic data found: {topic_data}")
            
            progress = topic_data.get("progress", 0)
            print(f"[Next Topic] Topic progress: {progress}")
            
            if progress < 2:  # Not completed
                result = {
                    "name": topic_name,
                    "progress": progress,
                    "status": topic_data.get("status", "not_started")
                }
                print(f"[Next Topic] Found non-competent topic: {result}")
                return result
        
        print("[Next Topic] No non-competent topics found")
        return None
    except Exception as e:
        print(f"[Next Topic Error] Exception: {str(e)}")
        return None 