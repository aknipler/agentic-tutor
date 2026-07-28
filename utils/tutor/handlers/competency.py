"""Handlers for competency-related operations"""
import difflib
import re
from typing import Dict, Any, NamedTuple, Optional, Union, List
import streamlit as st
import json
from mongodb.connectors import (
    get_topic_competency,
    update_competency,
    update_last_topic,
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

    `topic_switched` is the canonical name of a topic the *student* explicitly
    asked to move to, resolved against this module's own topic list. Like
    `topic_completed` it is only ever set once the request has been validated, and
    it is the only thing that moves a student off-sequence.
    """
    output: str
    topic_completed: Optional[str] = None
    topic_switched: Optional[str] = None


def get_module_topics(module_id: Union[str, int]) -> List[Dict[str, Any]]:
    """Return this module's topic documents (dicts only), or []."""
    from ..interface import get_cached_modules_data as _get_modules
    module_data = find_module_by_index(_get_modules(), str(module_id))
    if not module_data:
        return []
    return [topic for topic in module_data.get("topics", []) if isinstance(topic, dict)]


def get_module_topic_names(module_id: Union[str, int]) -> List[str]:
    """Return this module's topic names, in module order."""
    return [topic.get("name", "") for topic in get_module_topics(module_id) if topic.get("name")]


def topic_belongs_to_module(module_id: Union[str, int], topic_name: str) -> bool:
    """Whether `topic_name` is one of this module's own topics."""
    return topic_name in get_module_topic_names(module_id)


def _normalise_topic_name(name: str) -> str:
    """Reduce a topic name to a comparable form: lowercase, alphanumerics only."""
    return re.sub(r"[^a-z0-9]+", " ", str(name).casefold()).strip()


def resolve_topic_name(module_id: Union[str, int], requested: str) -> Optional[str]:
    """Map whatever the student called a topic onto this module's canonical name.

    Students ask for topics the way they say them out loud ("can we jump to
    ANOVA", "the gauge R&R one"), and the model passes that wording straight
    through. An exact string match would reject nearly all of it - the same trap
    that made the old `topic_name` argument on update_topic_competency silently
    drop competency writes - so match progressively: exact, then normalised, then
    containment either way, then a close-match fallback. Returns None when nothing
    matches well enough, so the caller can ask the student rather than guess.
    """
    if not requested:
        return None

    names = get_module_topic_names(module_id)
    if not names:
        return None

    if requested in names:
        return requested

    target = _normalise_topic_name(requested)
    if not target:
        return None

    normalised = {name: _normalise_topic_name(name) for name in names}

    for name, candidate in normalised.items():
        if candidate == target:
            return name

    # Containment: "ANOVA" is inside "Analysis of Variance (ANOVA)", and "the
    # ANOVA table topic" contains a shorter topic name. Only when it picks out one
    # topic - a bare "reliability" sits inside half the module, and guessing which
    # one they meant is worse than asking.
    contained = [
        name for name, candidate in normalised.items()
        if candidate and (candidate in target or target in candidate)
    ]
    if len(contained) == 1:
        return contained[0]

    # Abbreviations students actually use: "gauge r&r" -> "Gauge Repeatability and
    # Reproducibility". Every word they said has to prefix a word of the topic
    # name, in order, so it stays a match on the real words rather than a vague
    # resemblance.
    abbreviated = [
        name for name, candidate in normalised.items()
        if _is_abbreviation_of(target, candidate)
    ]
    if len(abbreviated) == 1:
        return abbreviated[0]

    # Last resort, and deliberately strict. Switching to the wrong topic is the
    # exact failure this whole path exists to prevent - a confident near-miss
    # would send the student's next competency write to a topic they never asked
    # for - so anything short of a close match returns None and the tutor asks.
    close = difflib.get_close_matches(target, list(normalised.values()), n=1, cutoff=0.75)
    if close:
        for name, candidate in normalised.items():
            if candidate == close[0]:
                return name

    return None


def _is_abbreviation_of(said: str, topic: str) -> bool:
    """Whether each word of `said` prefixes a later word of `topic`, in order."""
    said_words = said.split()
    topic_words = topic.split()
    if not said_words or len(said_words) > len(topic_words):
        return False

    position = 0
    for word in said_words:
        while position < len(topic_words) and not topic_words[position].startswith(word):
            position += 1
        if position == len(topic_words):
            return False
        position += 1
    return True


def build_topic_payload(module_id: Union[str, int], topic_name: str,
                        progress_data: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Build the topic dict the tutor flow passes around, for one named topic.

    One shape, built in one place: `name`, the student's current `progress`/
    `status`, and the lecturer-supplied `description`, `question` and
    `learning_outcomes` that the prompt builders read. Pass `progress_data` in
    when the caller has already read it this turn; otherwise it is read fresh,
    because every caller is at a decision point about what to teach next.
    """
    from ..interface import get_cached_modules_data as _get_modules, get_fresh_user_progress

    module_data = find_module_by_index(_get_modules(), str(module_id))
    if not module_data:
        return None

    topic = next(
        (t for t in module_data.get("topics", [])
         if isinstance(t, dict) and t.get("name") == topic_name),
        None
    )
    if topic is None:
        return None

    if progress_data is None:
        progress_data = get_fresh_user_progress()

    module_index = str(module_data.get("index", 0))
    topics_progress = (progress_data or {}).get("modules", {}).get(module_index, {}).get("topics", {})
    topic_progress = topics_progress.get(topic_name, {})

    return {
        "name": topic_name,
        "progress": topic_progress.get("progress", 0),
        "status": topic_progress.get("status", "not_started"),
        "description": topic.get("description", ""),
        "question": topic.get("question", ""),
        "learning_outcomes": topic.get("learning_outcomes", "")
    }


def format_module_topic_overview(module_id: Union[str, int], current_topic_name: str) -> str:
    """List this module's topics, and where the student is up to, for the prompt.

    The model cannot switch a student to a topic it doesn't know the name of: with
    only "Current Topic" in the instructions it had to invent a name from the
    student's wording. Sending the canonical list, marked up with each topic's
    status, lets it pass an exact name to `switch_topic` and lets it answer "what
    else is in this module?" without guessing.
    """
    from ..interface import get_cached_user_progress

    topics = get_module_topics(module_id)
    if not topics:
        return ""

    progress_data = get_cached_user_progress() or {}
    topics_progress = progress_data.get("modules", {}).get(str(module_id), {}).get("topics", {})

    lines = []
    for topic in topics:
        name = topic.get("name", "")
        if not name:
            continue
        if name == current_topic_name:
            state = "current topic"
        else:
            progress = topics_progress.get(name, {}).get("progress", 0)
            state = {0: "not started", 1: "in progress", 2: "completed"}.get(progress, "not started")
        lines.append(f"- {name} ({state})")

    if not lines:
        return ""

    return (
        "## Topics in this module\n"
        + "\n".join(lines)
        + "\n\nThese are the exact topic names. Students do not have to work through them in "
        "order. Use `switch_topic` only when the student explicitly asks to move to a different "
        "one, and pass the name exactly as written above."
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


def set_active_topic(module_id: Union[str, int], topic: Optional[Dict[str, Any]]) -> None:
    """Make `topic` the module's current topic, for this session and the next one.

    The single place a topic becomes current. Session state is what the rest of
    the turn reads; the write to the student's record is what makes the choice
    outlive the session, since nothing else on that record distinguishes "the
    topic they are working on" from "the first one they haven't finished".
    """
    TutorState.set_current_topic(str(module_id), topic or {})

    topic_name = (topic or {}).get("name", "")
    user_id = st.session_state.get("user_id", "")
    if topic_name and user_id:
        update_last_topic(user_id, str(module_id), topic_name)


def get_resume_topic(module_id: Union[str, int]) -> Optional[Dict[str, Any]]:
    """The topic to put the student on when they open this module.

    Where they left off, if that is still one of the module's topics, and the
    first unfinished topic otherwise - which is also the answer for every student
    whose record predates `last_topic`, and for anyone who has never chosen a
    topic for themselves. A finished module resumes nowhere, as before: the page
    congratulates them and disables the chat.
    """
    from ..interface import get_fresh_user_progress

    progress_data = get_fresh_user_progress() or {}
    last_topic = progress_data.get("modules", {}).get(str(module_id), {}).get("last_topic")

    # is_module_complete reads the cached snapshot, which get_fresh_user_progress
    # has just refreshed.
    if last_topic and topic_belongs_to_module(module_id, last_topic) and not is_module_complete(module_id):
        resumed = build_topic_payload(module_id, last_topic, progress_data)
        if resumed:
            print(f"[Resume Topic] Module {module_id} resuming where the student left off: {last_topic!r}")
            return resumed

    print(f"[Resume Topic] Module {module_id} has no topic to resume ({last_topic!r}) - using the first unfinished one")
    return get_next_non_competent_topic(module_id)


def ensure_current_topic_for_module(module_id: Union[str, int]) -> Optional[Dict[str, Any]]:
    """Return the topic this module is teaching, resyncing session state if it drifted.

    The current topic is now stored per module (`current_topic_{module_id}`), so
    the cross-module drift this used to repair - one shared key, overwritten by
    whichever module page ran last - can no longer happen. It stays as the single
    place a turn resolves its topic: it still recovers a session that has no topic
    yet, or one naming a topic that has since been renamed or removed from the
    module data, before anything in the turn reads it.

    A topic the student explicitly switched to is left alone even when earlier
    topics are unfinished - it belongs to this module, so it is honoured, not
    "corrected" back to the first incomplete one.
    """
    current = TutorState.get_current_topic(str(module_id)) or {}
    topic_name = current.get("name", "")

    if topic_name and topic_belongs_to_module(module_id, topic_name):
        return current

    print(f"[Current Topic] {topic_name!r} is not a topic of module {module_id} - resyncing")
    repaired = get_resume_topic(module_id)
    if repaired:
        set_active_topic(module_id, repaired)
        print(f"[Current Topic] Resynced module {module_id} to: {repaired.get('name')}")
    return repaired


def handle_topic_switch(args: Dict[str, Any], module_id: Union[str, int]) -> ToolCallResult:
    """Handle the student asking to work on a different topic in this module.

    Students do not work through a module in order, and until now nothing in the
    app registered that: the tutor would happily *talk* about the topic they asked
    for while the application still believed the old topic was current, so the
    per-topic prompt, the learning outcomes and - worst - every competency write
    went to the topic they had left behind.

    Validation happens here, not in the model: the requested name is resolved
    against this module's own topics, and a name that can't be resolved returns
    the topic list to the model so it can ask, rather than switching to a guess.
    """
    requested = str(args.get("topic_name") or "").strip()
    reason = args.get("reason")
    print(f"[Topic Switch] Requested topic: {requested!r} in module {module_id} (reason: {reason})")

    if not requested:
        return ToolCallResult(
            "Topic not switched - no topic name was supplied. Ask the student which topic they "
            "want to move to."
        )

    resolved = resolve_topic_name(module_id, requested)
    if not resolved:
        names = get_module_topic_names(module_id)
        print(f"[Topic Switch] Could not resolve {requested!r}; module topics are {names}")
        return ToolCallResult(
            f"Topic not switched - '{requested}' does not match a topic in this module. "
            f"The topics are: {'; '.join(names)}. Ask the student which of these they meant "
            "and do not switch until they confirm."
        )

    current_topic_name = (TutorState.get_current_topic(str(module_id)) or {}).get("name", "")
    if resolved == current_topic_name:
        print(f"[Topic Switch] Already on {resolved}, nothing to do")
        return ToolCallResult(
            f"Already teaching {resolved} - no switch needed. Continue with this topic."
        )

    print(f"[Topic Switch] Resolved {requested!r} -> {resolved!r}")
    return ToolCallResult(
        f"Switched to {resolved}. The application will introduce the new topic and ask the "
        "opening question, so do not write one yourself.",
        topic_switched=resolved
    )

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

    current_topic = TutorState.get_current_topic(str(module_id)) or {}
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

    # Competency only goes up. Asked to leave a topic, the model will summarise
    # the state of it - and reads "no substantive attempt yet" as something to
    # record, calling update_topic_competency(0) on a topic the student had
    # already reached level 1 on. That erases work they actually did, and the
    # green ticks on the progress page are the record students trust. Nothing
    # the model observes in a single turn is evidence that earlier work stopped
    # counting, so a lower level is dropped rather than written.
    existing_level = 0
    try:
        existing = get_topic_competency(user_id, topic_name) or {}
        existing_level = int(existing.get("progress", 0) or 0)
    except Exception as e:
        print(f"[Competency Update] Could not read the current level for {topic_name}: {str(e)}")

    if level < existing_level:
        print(f"[Competency Update] Refusing to lower {topic_name} from {existing_level} to {level}")
        return ToolCallResult(
            f"{topic_name} is already recorded at level {existing_level}, so it was left there - "
            "competency is never lowered. Continue the conversation."
        )

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
                # Pulls the topic's description (and optional diagnostic question)
                # from the module data. PRQ topics carry `description` but no
                # `question`, so both are looked up with .get before being passed
                # on to the tutor prompt.
                result = build_topic_payload(module_id, topic_name, progress_data)
                print(f"[Next Topic] Found non-competent topic: {result}")
                return result
        
        print("[Next Topic] No non-competent topics found")
        return None
    except Exception as e:
        print(f"[Next Topic Error] Exception: {str(e)}")
        return None 