"""Handlers for competency-related operations"""
from typing import Dict, Any, Optional, Union
import streamlit as st
import json
from mongodb.connectors import (
    get_topic_competency,
    update_competency,
    get_user_progress,
    update_user_progress,
    get_modules_data
)
from ..config.settings import COMPETENCY_LEVELS, MODULE_TITLES

def handle_competency_update(args: Dict[str, Any], user_id: str) -> str:
    """Handle competency update function calls"""
    topic_name = args.get("topic_name")
    level = args.get("level")
    reason = args.get("reason")
    
    print(f"[Competency Update] Starting update for topic: {topic_name}, level: {level}, reason: {reason}")
    
    if topic_name is not None and level is not None:
        try:
            # Get user progress data
            progress_data = get_user_progress(user_id)
            print(f"[Competency Update] Raw progress data: {progress_data}")
            
            if not progress_data:
                print(f"[Competency Update Error] No progress data found for user: {user_id}")
                return f"Failed to update competency for {topic_name} - No user data found"
            
            # Find which module contains this topic
            target_module_id = None
            for module_id, module_data in progress_data.get("modules", {}).items():
                topics = module_data.get("topics", {})
                print(f"[Competency Update] Checking module {module_id}, topics: {topics}")
                if topic_name in topics:
                    target_module_id = module_id
                    break
            
            if target_module_id is None:
                print(f"[Competency Update Error] Topic {topic_name} not found in any module")
                return f"Failed to update competency for {topic_name} - Topic not found"
            
            print(f"[Competency Update] Found target module: {target_module_id}")
            
            # Update the topic's progress
            success = update_user_progress(
                user_id=user_id,
                module_id=target_module_id,
                topic_id=topic_name,
                progress=level
            )
            
            if success:
                print(f"[Competency Update Success] Topic: {topic_name}, New Level: {level}, Reason: {reason}")
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
            # Get user progress data
            progress_data = get_user_progress(user_id)
            print(f"[Competency Check] Raw progress data: {progress_data}")
            
            if not progress_data:
                print(f"[Competency Check Error] No progress data found for user: {user_id}")
                return json.dumps({
                    "topic_name": topic_name,
                    "progress": 0,
                    "level": 0
                })
            
            # Search through all modules to find the topic
            for module_id, module_data in progress_data.get("modules", {}).items():
                topics = module_data.get("topics", {})
                print(f"[Competency Check] Checking module {module_id}, topics: {topics}")
                if topic_name in topics:
                    topic_data = topics[topic_name]
                    progress = topic_data.get("progress", 0)
                    print(f"[Competency Check] Found topic data: {topic_data}, progress: {progress}")
                    return json.dumps({
                        "topic_name": topic_name,
                        "progress": progress,
                        "level": progress
                    })
            
            # Topic not found in any module
            print(f"[Competency Check] Topic {topic_name} not found in any module")
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
        
        progress_data = get_user_progress(user_id)
        print(f"[Progress Summary] Raw progress data: {progress_data}")
        
        if not progress_data:
            print("[Progress Summary] No progress data found")
            return None
            
        modules_data = get_modules_data()
        module_id = str(module)
        print(f"[Progress Summary] Module ID: {module_id}")
        
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
        
        # Map topics by name from root level progress data
        topics_data = progress_data.get("topics", [])
        print(f"[Progress Summary] Topics from progress data: {topics_data}")
        
        user_topics_by_name = {topic["name"]: topic for topic in topics_data}
        print(f"[Progress Summary] Mapped topics by name: {user_topics_by_name}")
        
        progress_summary = []
        for topic in topics:
            if isinstance(topic, dict):
                topic_name = topic.get('name', 'Unnamed Topic')
            else:
                topic_name = str(topic)
            print(f"[Progress Summary] Processing topic: {topic_name}")
            
            topic_data = user_topics_by_name.get(topic_name, {})
            print(f"[Progress Summary] Topic data found: {topic_data}")
            
            progress = topic_data.get("progress", 0)
            status = COMPETENCY_LEVELS.get(progress, "🔴")
            progress_summary.append(f"{status} {topic_name}")
            print(f"[Progress Summary] Added to summary: {status} {topic_name}")
        
        result = "\n\n".join(progress_summary)
        print(f"[Progress Summary] Final summary: {result}")
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
        
        modules_data = get_modules_data()
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
            
        # Get user's progress for all topics
        progress_data = get_user_progress(user_id)
        print(f"[Next Topic] Raw progress data: {progress_data}")
        
        if not progress_data:
            print(f"[Next Topic Error] No progress data found for user: {user_id}")
            return None
            
        # Map topics by name from root level progress data
        topics_data = progress_data.get("topics", [])
        print(f"[Next Topic] Topics from progress data: {topics_data}")
        
        user_topics_by_name = {topic["name"]: topic for topic in topics_data}
        print(f"[Next Topic] Mapped topics by name: {user_topics_by_name}")
        
        # Find the first topic that isn't completed
        for topic in topics:
            if isinstance(topic, dict):
                topic_name = topic.get('name', 'Unnamed Topic')
            else:
                topic_name = str(topic)
            print(f"[Next Topic] Checking topic: {topic_name}")
            
            topic_data = user_topics_by_name.get(topic_name, {})
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