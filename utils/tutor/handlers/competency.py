"""Handlers for competency-related operations"""
from typing import Dict, Any, NamedTuple, Optional, Union, List
import streamlit as st
import json
from mongodb.connectors import (
    get_topic_competency,
    update_competency,
    get_user_progress,
    update_user_progress
)
from ..config.settings import COMPETENCY_LEVELS
from ..state import TutorState
from utils.cache import get_cached_modules_data
from utils.modules import find_module_by_index


class ToolCallResult(NamedTuple):
    """The outcome of one tutor function call.

    `output` is what gets fed back to the model as the function_call_output.

    `topic_completed` is set only when a level-2 competency write has been
    accepted by the database, and it is the *only* thing that triggers a topic
    transition. Previously any non-None return - including "Failed to update
    competency for X" - moved the student on, so a write that never landed still
    produced a green "you've completed the topic" message, and the next topic was
    then chosen from progress data that still said the topic was unfinished.
    """
    output: str
    topic_completed: Optional[str] = None


def topic_belongs_to_module(module_id: Union[str, int], topic_name: str) -> bool:
    """Whether `topic_name` is one of this module's own topics."""
    from ..interface import get_cached_modules_data as _get_modules
    module_data = find_module_by_index(_get_modules(), str(module_id))
    if not module_data:
        return False
    return any(
        isinstance(topic, dict) and topic.get("name") == topic_name
        for topic in module_data.get("topics", [])
    )


def is_module_complete(module_id: Union[str, int]) -> bool:
    """Whether every topic in this module is at level 2 for the current student.

    Reads the cached progress snapshot rather than the database: this is called on
    every render, and the cache is dropped on every competency write, so it is
    already accurate the moment a topic is finished.
    """
    from ..interface import get_cached_modules_data as _get_modules, get_cached_user_progress
    module_data = find_module_by_index(_get_modules(), str(module_id))
    if not module_data:
        return False

    topics = module_data.get("topics", [])
    if not topics:
        return False

    progress_data = get_cached_user_progress() or {}
    module_index = str(module_data.get("index", 0))
    topics_progress = progress_data.get("modules", {}).get(module_index, {}).get("topics", {})

    return all(
        topics_progress.get(
            topic.get("name") if isinstance(topic, dict) else str(topic), {}
        ).get("progress", 0) >= 2
        for topic in topics
    )


def ensure_current_topic_for_module(module_id: Union[str, int]) -> Optional[Dict[str, Any]]:
    """Return the topic this module is teaching, resyncing session state if it drifted.

    `current_topic` is a single session-wide key shared by every module page, and a
    page only sets it while initialising its chat history - so visiting a second
    module and coming back leaves the first module tracking the *other* module's
    topic. Every turn then writes competency against that foreign topic (in the
    other module's progress), tells the model the wrong "Current Topic", and files
    the conversation log under it. Until the key is scoped per module, re-point it
    at this module's own next topic whenever it has drifted, before anything else
    in the turn reads it.
    """
    current = TutorState.get_current_topic() or {}
    topic_name = current.get("name", "")

    if topic_name and topic_belongs_to_module(module_id, topic_name):
        return current

    print(f"[Current Topic] {topic_name!r} is not a topic of module {module_id} - resyncing")
    repaired = get_next_non_competent_topic(module_id)
    if repaired:
        TutorState.set_current_topic(repaired)
        print(f"[Current Topic] Resynced module {module_id} to: {repaired.get('name')}")
    return repaired

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

def handle_competency_update(args: Dict[str, Any], user_id: str, module_id: Union[str, int]) -> ToolCallResult:
    """Record the student's competency for the topic this module is teaching.

    The topic is taken from session state, never from the model. The tool used to
    accept a `topic_name` argument that was matched exactly (case- and
    whitespace-sensitive) against the canonical topic names; the tutor routinely
    paraphrases the topic in its own output ("Definition of reliability.",
    "Fundamental reliability functions (reliability, failure distribution, ...)"),
    and any such paraphrase matched no module, so the write was dropped while the
    student was still told they had completed the topic. There is only ever one
    topic in play per module, so it is not the model's to name.
    """
    level = args.get("level")
    reason = args.get("reason")
    claimed_topic = args.get("topic_name")  # legacy/hallucinated - logged, never used for routing

    try:
        level = int(level)
    except (TypeError, ValueError):
        print(f"[Competency Update Error] Non-integer level: {level!r}")
        return ToolCallResult("Failed to update competency - level must be 0, 1 or 2")

    if level not in COMPETENCY_LEVELS:
        print(f"[Competency Update Error] Level out of range: {level}")
        return ToolCallResult("Failed to update competency - level must be 0, 1 or 2")

    current_topic = TutorState.get_current_topic() or {}
    topic_name = current_topic.get("name", "")

    # Safety net. get_bot_response resyncs the current topic at the start of every
    # turn, so this should not fire; if it does, the session's idea of what is
    # being taught is unreliable and the student's work cannot be attributed to a
    # topic with any confidence. Reject rather than write to the wrong one.
    if not topic_name or not topic_belongs_to_module(module_id, topic_name):
        print(f"[Competency Update Error] Current topic {topic_name!r} does not belong to module {module_id}")
        return ToolCallResult(
            "Competency not recorded - the current topic could not be confirmed. "
            "Continue the conversation; do not tell the student they have finished the topic."
        )

    if claimed_topic and claimed_topic != topic_name:
        print(f"[Competency Update] Ignoring supplied topic_name {claimed_topic!r}; current topic is {topic_name!r}")

    print(f"[Competency Update] Starting update for topic: {topic_name}, level: {level}, reason: {reason}")

    try:
        success = update_competency(user_id=user_id, topic_name=topic_name, level=level)
    except Exception as e:
        print(f"[Competency Update Error] Exception: {str(e)}")
        success = False

    # Unconditional: the cached progress and the rendered progress summary are
    # stale either way once a write has been attempted, and leaving them in place
    # on the failure path is what kept the green tick from appearing.
    from ..interface import invalidate_caches
    invalidate_caches()

    if not success:
        print(f"[Competency Update Failed] Topic: {topic_name}, Attempted Level: {level}")
        return ToolCallResult(
            f"Failed to record competency for {topic_name} - the update was not saved. "
            "Continue the conversation; do not tell the student they have finished the topic."
        )

    print(f"[Competency Update Success] Topic: {topic_name}, New Level: {level}, Reason: {reason}")
    return ToolCallResult(
        f"Successfully updated competency for {topic_name} to level {level}",
        topic_completed=topic_name if level == 2 else None
    )

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

        # Locate the module by its index. Titles come from the lecturers' data and
        # must never be used as lookup keys.
        module_data = find_module_by_index(modules_data, module_id)
        if not module_data:
            print(f"[Progress Summary] No module found with index {module_id}")
            return None

        topics = module_data.get("topics", [])
        print(f"[Progress Summary] Found topics for module: {topics}")

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

def get_next_non_competent_topic(module_id: Union[str, int],
                                 after_topic_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Get the next topic the student hasn't completed in this module.

    With `after_topic_name` the search starts at the topic *following* that one and
    wraps back to the start of the module only once the tail is exhausted, and the
    named topic is never returned. Without it (resuming a module, or recovering
    drifted state) the search starts from the top as before.

    This scan used to always restart from the top and return the first topic below
    level 2, which turned any single missed write into a trap: the topic the
    student had just finished was still the first incomplete one, so "next topic"
    handed back the topic they had just done - or an earlier one they finished
    days ago - and did so again on every subsequent attempt.
    """
    try:
        user_id = st.session_state.user_id
        print(f"[Next Topic] Getting next topic for user: {user_id}, module: {module_id}")
        
        # Get modules data from cache
        from ..interface import get_cached_modules_data, get_fresh_user_progress
        modules_data = get_cached_modules_data()
        module_id_str = str(module_id)
        print(f"[Next Topic] Module ID string: {module_id_str}")
        
        # Locate the module by its index. Titles come from the lecturers' data and
        # must never be used as lookup keys.
        module_data = find_module_by_index(modules_data, module_id_str)
        if not module_data:
            print(f"[Next Topic Error] No module found with index {module_id_str}")
            return None

        topics = module_data.get("topics", [])
        print(f"[Next Topic] Found topics for module: {topics}")

        if not topics:
            print(f"[Next Topic Error] No topics found for module index {module_id_str}")
            return None
            
        # Read progress fresh: choosing the next topic is a once-per-topic
        # decision, and a stale snapshot here is what sent students back to topics
        # they had already finished.
        progress_data = get_fresh_user_progress()
        if not progress_data:
            print(f"[Next Topic Error] No progress data found for user: {user_id}")
            return None
            
        # Get the module's progress data using its index
        module_index = str(module_data.get("index", 0))
        module_progress = progress_data.get("modules", {}).get(module_index, {})
        topics_progress = module_progress.get("topics", {})
        print(f"[Next Topic] Module progress data: {module_progress}")
        
        # Search order: everything after the topic just completed, then wrap around
        # to pick up anything skipped earlier in the module.
        topic_names = [
            topic.get('name', 'Unnamed Topic') if isinstance(topic, dict) else str(topic)
            for topic in topics
        ]
        start = 0
        if after_topic_name in topic_names:
            start = topic_names.index(after_topic_name) + 1
        search_order = list(range(start, len(topics))) + list(range(0, start))
        print(f"[Next Topic] Searching after {after_topic_name!r}, order: {search_order}")

        for position in search_order:
            topic = topics[position]
            topic_name = topic_names[position]
            print(f"[Next Topic] Checking topic: {topic_name}")

            # Never hand back the topic that was just completed: if its write went
            # missing it would still read as incomplete and restart on the spot.
            if topic_name == after_topic_name:
                print(f"[Next Topic] Skipping {topic_name} - just completed")
                continue

            # Get topic progress from the new structure
            topic_data = topics_progress.get(topic_name, {})
            print(f"[Next Topic] Topic data found: {topic_data}")
            
            progress = topic_data.get("progress", 0)
            print(f"[Next Topic] Topic progress: {progress}")
            
            if progress < 2:  # Not completed
                # Pull the topic's description (and optional diagnostic question) from
                # the module data. PRQ topics carry `description` but no `question`,
                # so both are looked up with .get and passed on to the tutor prompt.
                question = ""
                description = ""
                learning_outcomes = ""
                for module_topic in module_data.get("topics", []):
                    if module_topic.get("name") == topic_name:
                        question = module_topic.get("question", "")
                        description = module_topic.get("description", "")
                        learning_outcomes = module_topic.get("learning_outcomes", "")
                        break
                result = {
                    "name": topic_name,
                    "progress": progress,
                    "status": topic_data.get("status", "not_started"),
                    "description": description,
                    "question": question,
                    "learning_outcomes": learning_outcomes
                }
                print(f"[Next Topic] Found non-competent topic: {result}")
                return result
        
        print("[Next Topic] No non-competent topics found")
        return None
    except Exception as e:
        print(f"[Next Topic Error] Exception: {str(e)}")
        return None 