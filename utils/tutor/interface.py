"""Main tutor interface implementation"""
import sys
import traceback
import streamlit as st
import openai
import json
from typing import Optional, Dict, Any, Union, List, Tuple
from datetime import datetime

# This module's debug prints echo raw model output (equations, special
# characters like the Unicode minus sign U+2212) straight to the console. On
# Windows, stdout defaults to the cp1252 "charmap" codec, which can't encode
# those characters and raises UnicodeEncodeError - crashing the whole tutor
# response before it ever reaches the student. Force UTF-8 so a debug print
# can never take down a real answer.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from .config.settings import TutorConfig
from .models.chat import ChatMessage
from .state import TutorState
from .handlers.competency import (
    ToolCallResult,
    build_topic_payload,
    ensure_current_topic_for_module,
    format_module_topic_overview,
    is_module_complete,
    handle_competency_update,
    handle_competency_check,
    handle_topic_switch,
    set_active_topic,
    get_module_progress_summary,
    get_next_non_competent_topic,
    get_resume_topic
)
from .ui.components import render_sidebar, render_chat_history, render_progress_summary
from mongodb.connectors import get_modules_data, get_user_progress, update_competency
from mongodb.logger import UserLogger
from utils.cache import get_cached_modules_data, invalidate_modules_cache
from utils.modules import find_module_by_index
from assessor.utils import get_status_emoji

# Base URL for the application
BASE_URL = "http://localhost:8502/"

# Initialize logger
logger = UserLogger()

def invalidate_caches():
    """Drop cached progress after a write, so the next render reflects it.

    The progress-summary keys are collected from session state rather than
    hardcoded: the list used to run progress_summary_1..6, so a seventh module
    would have kept rendering a stale panel forever. `cached_modules_data` is
    deliberately left alone - module documents don't change when a student's
    progress does, and clearing it forced a full re-fetch of every module on the
    next read.
    """
    keys_to_clear = ["cached_user_progress"]
    keys_to_clear += [
        key for key in st.session_state
        if isinstance(key, str) and key.startswith("progress_summary_")
    ]
    for key in keys_to_clear:
        if key in st.session_state:
            del st.session_state[key]

def get_cached_modules_data():
    """Get modules data from cache or fetch if not available"""
    from mongodb.connectors import get_modules_data
    return get_modules_data()  # Now uses internal caching

def invalidate_modules_cache():
    """Invalidate the modules cache when data needs to be refreshed"""
    if "cached_modules_data" in st.session_state:
        del st.session_state.cached_modules_data

def get_cached_user_progress():
    """Get user progress from cache or fetch if not available.

    For the render path only. The cache has no expiry and is only cleared by
    writes this session makes, so anything that *decides* what the student is
    taught next must use get_fresh_user_progress instead.
    """
    if "cached_user_progress" not in st.session_state:
        st.session_state.cached_user_progress = get_user_progress(st.session_state.user_id)
    return st.session_state.cached_user_progress

def get_fresh_user_progress():
    """Read the student's progress straight from the database.

    Used at decision points - which topic to teach next, whether a topic has been
    started - where acting on a stale snapshot changes what the student sees. It
    is a single indexed find_one, and correctness there is worth far more than the
    round trip; the session cache exists so the render path isn't re-reading on
    every widget interaction. The cache is refreshed here too, so the rest of the
    run agrees with the decision that was just made.
    """
    progress = get_user_progress(st.session_state.user_id)
    st.session_state.cached_user_progress = progress
    return progress

def load_tutor_prompt() -> str:
    """Load the tutor prompt from the tutor.md file"""
    try:
        with open("prompts/tutor.md", "r", encoding="utf-8") as file:
            return file.read()
    except UnicodeDecodeError:
        try:
            with open("prompts/tutor.md", "r", encoding="latin-1") as file:
                return file.read()
        except Exception as e:
            st.error(f"Error loading tutor prompt with alternate encoding: {str(e)}")
            return "Error loading tutor prompt. Please check file encoding."
    except Exception as e:
        st.error(f"Error loading tutor prompt: {str(e)}")
        return "Error loading tutor prompt. Please check if the file exists."

def load_logged_conversation_messages(user_id: str, module_id: Union[str, int], topic_name: str) -> List[Dict[str, Any]]:
    """Rehydrate a topic's chat history from the persisted conversation log.

    Chat history otherwise lives only in st.session_state (see TutorState),
    which is empty on every fresh login - nothing previously read it back from
    mongodb/logger.py's UserLogger, even though every turn is logged there via
    log_conversation. If the student already has a logged conversation for this
    exact module/topic pair, replay it here instead of starting the topic over
    and generating a new opening question.
    """
    if not user_id:
        return []
    messages = []
    for pair in logger.get_conversation(user_id, str(module_id), topic_name):
        user_msg, assistant_msg = (list(pair) + ["", ""])[:2]
        if user_msg:
            messages.append(ChatMessage(role="user", content=user_msg, topic_name=topic_name).to_dict())
        if assistant_msg:
            messages.append(ChatMessage(role="assistant", content=assistant_msg, topic_name=topic_name).to_dict())
    return messages

def format_topic_learning_outcomes(topic: Dict[str, Any]) -> str:
    """Format a topic's `learning_outcomes` for injection into a prompt.

    `learning_outcomes` used to live as a static "Competency Areas" block inside
    prompts/tutor.md (every lecture's outcomes, sent on every single turn
    regardless of the active topic). It now comes from the module data
    (scripts/load_week_json.py merges it in from knowledge/learning_outcomes.json)
    so only the current topic's outcomes are sent, and only while that topic is
    active - this is the bulk of the tutor prompt's token reduction.
    """
    topic_learning_outcomes = topic.get("learning_outcomes", "")
    if isinstance(topic_learning_outcomes, list):
        topic_learning_outcomes = "\n".join(f"- {outcome}" for outcome in topic_learning_outcomes)
    if not topic_learning_outcomes:
        return ""
    return (
        f"Learning outcomes for this topic:\n{topic_learning_outcomes}\n"
        "Use these learning outcomes to guide the conversation."
    )

def build_initial_topic_prompt(topic: Dict[str, Any]) -> str:
    """Build the prompt used to generate a topic's opening Socratic question.

    Lecturer-supplied topics may or may not include an explicit diagnostic
    `question` field. The PRQ week_*.json modules only carry `name` +
    `description`, so this must not assume `question` exists (a direct
    `topic['question']` access crashes the whole topic flow).

    When a `question` is present we steer the tutor to open with it; when it is
    absent we ask the tutor to craft an opening question from the topic name and
    description instead.
    """
    topic_name = topic.get("name", "")
    topic_description = topic.get("description", "")
    given_question = topic.get("question", "")

    learning_outcomes = format_topic_learning_outcomes(topic)

    description_line = f"Topic description: {topic_description}" if topic_description else ""

    if given_question:
        return f"""You are starting a new topic: {topic_name}
{description_line}

Your task is to:
1. Begin with the given direct, engaging question that immediately focuses on the core concept of the topic
2. Avoid generic introductions or small talk - get straight to the given question

Given question: {given_question}

Generate your response as a single, focused Socratic question that will start the discussion. Do not include any introductory text or explanations - just the given question itself.

{learning_outcomes}"""

    return f"""You are starting a new topic: {topic_name}
{description_line}

Your task is to:
1. Craft a single direct, engaging question that immediately focuses on the core concept of this topic, grounded in the topic description above
2. Avoid generic introductions or small talk - get straight to a substantive diagnostic question

Generate your response as a single, focused Socratic question that will start the discussion. Do not include any introductory text or explanations - just the question itself.

{learning_outcomes}"""

def setup_openai_client() -> openai.OpenAI:
    """Set up and return the OpenAI client"""
    if "openai_client" not in st.session_state:
        client = openai.OpenAI()
        st.session_state["openai_client"] = client
    return st.session_state["openai_client"]

def handle_function_call(tool_call: Dict[str, Any], user_id: str,
                         module_id: Union[str, int]) -> Optional[ToolCallResult]:
    """Handle function calls from the AI response"""
    func_name = tool_call["name"]
    func_args = tool_call["arguments"]  # Already parsed JSON from streaming
    print(f"[Function Call] Received function call: {func_name} with arguments: {func_args}")
    if func_name == "update_topic_competency":
        return handle_competency_update(func_args, user_id, module_id)
    elif func_name == "switch_topic":
        return handle_topic_switch(func_args, module_id)
    elif func_name == "get_topic_competency":
        return ToolCallResult(handle_competency_check(func_args, user_id))
    return None

def handle_topic_transition() -> Optional[str]:
    """Handle topic transition state and return a message if in transition"""
    if st.session_state.get("in_topic_transition", False):
        transition_time = st.session_state.get("topic_transition_time", 0)
        current_time = datetime.now().timestamp()
        if current_time - transition_time < 5:
            print("[Topic Transition] Recent transition detected, skipping processing")
            return "Processing topic transition, please wait..."
        else:
            print("[Topic Transition] Old transition detected, clearing state")
            st.session_state["in_topic_transition"] = False
            if "topic_transition_time" in st.session_state:
                del st.session_state["topic_transition_time"]
    return None

def prepare_tools_configuration(vector_store_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Prepare the tools configuration for the AI response"""
    # No `topic_name` parameter by design. The tutor teaches exactly one topic at a
    # time and the app already knows which one; when the model supplied the name it
    # was matched exactly against the canonical topic strings, and every paraphrase
    # ("Definition of reliability.", "Fundamental reliability functions (...)")
    # matched nothing and silently discarded the update.
    tools = [
        {
            "type": "function",
            "name": "update_topic_competency",
            "description": (
                "Record the student's competency for the topic currently being taught. "
                "The topic is determined by the application - do not name it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "level": {
                        "type": "integer",
                        "description": "Competency level (0=not started, 1=in progress, 2=completed)",
                        "enum": [0, 1, 2]
                    },
                    "reason": {
                        "type": "string",
                        "description": "Brief explanation for the competency update"
                    }
                },
                "required": ["level", "reason"]
            }
        },
        # Students don't work through a module in order. This is the only way the
        # app learns that they have moved: without it the tutor would answer about
        # the topic they asked for while every competency write, the per-topic
        # prompt and the conversation log stayed on the topic they had left. The
        # name is resolved against this module's topic list app-side, so a
        # paraphrase is matched rather than silently dropped.
        {
            "type": "function",
            "name": "switch_topic",
            "description": (
                "Move this module on to a different topic, when the student explicitly asks to "
                "work on one ('can we jump to X', 'I'd rather do Y first'). Pass the topic name "
                "exactly as it appears in the topic list in these instructions. Never call this "
                "on your own initiative, and do not write an opening question for the new topic "
                "- the application asks it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic_name": {
                        "type": "string",
                        "description": "The topic to switch to, named exactly as in the module's topic list"
                    },
                    "reason": {
                        "type": "string",
                        "description": "Brief explanation of what the student asked for"
                    }
                },
                "required": ["topic_name", "reason"]
            }
        }
    ]

    print(f"[Vector Store ID] Vector store ID: {vector_store_id}")
    if vector_store_id:
        print(f"[Vector Store] Adding vector store {vector_store_id} to tools configuration")
        tools.append({
            "type": "file_search",
            "vector_store_ids": [vector_store_id]
        })

    return tools

def prepare_conversation_context(module: Union[str, int], topic_name: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Prepare the conversation context and find the previous response ID"""
    # Get conversation context from state
    conversation_context = TutorState.get_conversation_context(str(module), topic_name)
    
    # Log the conversation context for debugging
    print(f"[Debug] Conversation context for module {module}, topic {topic_name}: {len(conversation_context)} messages")
    
    # Find the previous response ID
    previous_response_id = None
    if conversation_context:
        for message in reversed(conversation_context):
            if message.get("role") == "assistant" and message.get("response_id"):
                previous_response_id = message.get("response_id")
                break
    
    return conversation_context, previous_response_id

def format_input_content(conversation_context: List[Dict[str, Any]], user_input: str,
                         previous_response_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Format the input content for the AI response.

    When the turn is chained with `previous_response_id`, only the new user message
    is sent: the server already holds everything up to that response. Sending the
    message window as well - which is what used to happen, on every single turn -
    delivered the last exchanges twice, paying for them twice and giving the model
    a conversation in which the student appears to repeat themselves.

    Without a response to chain from (a fresh topic, or history replayed after a
    login) the window is still sent, because it is the only context there is.
    """
    if previous_response_id:
        print(f"[Debug] Chaining from {previous_response_id}; sending only the new user message")
        return [{"role": "user", "content": user_input}]

    input_content = []

    # Add conversation history with topic context
    for message in conversation_context:
        msg_content = message.get("content", "")
        msg_role = message.get("role", "")
        
        if msg_role in ["user", "assistant"]:
            # Create a new message without the topic_name field for API compatibility
            formatted_message = {
                "role": msg_role,
                "content": msg_content
            }
            input_content.append(formatted_message)
        elif message.get("type") == "function_call":
            arguments = message.get("arguments", "")
            if isinstance(arguments, dict):
                arguments = json.dumps(arguments)
            
            function_call = {
                "type": "function_call",
                "id": message.get("id"),
                "call_id": message.get("call_id"),
                "name": message.get("name"),
                "arguments": arguments
            }
            input_content.append(function_call)
        elif message.get("type") == "function_call_output":
            input_content.append({
                "type": "function_call_output",
                "call_id": message.get("call_id"),
                "output": message.get("output")
            })
    
    # Add current user input without topic_name field
    input_content.append({
        "role": "user",
        "content": user_input
    })
    
    return input_content

def process_streaming_response(response, text_placeholder) -> Tuple[str, str, Dict[str, Any]]:
    """Process the streaming response from the AI"""
    response_text = ""
    response_id = None
    final_tool_calls = {}
    current_tool_call = None
    
    for event in response:
        if event.type == "response.created":
            response_id = event.response.id
        elif event.type == "response.output_text.delta":
            response_text += event.delta
            text_placeholder.markdown(response_text)
        elif event.type == "response.output_item.added" and event.item.type == "function_call":
            current_tool_call = event.item
            final_tool_calls[event.output_index] = {
                "type": "function_call",
                "id": event.item.id,
                "call_id": event.item.call_id,
                "name": event.item.name,
                "arguments": ""
            }
        elif event.type == "response.function_call_arguments.delta":
            if event.output_index in final_tool_calls:
                final_tool_calls[event.output_index]["arguments"] += event.delta
        elif event.type == "response.function_call_arguments.done":
            if event.output_index in final_tool_calls:
                try:
                    final_tool_calls[event.output_index]["arguments"] = json.loads(event.arguments)
                except json.JSONDecodeError:
                    print(f"[Error] Failed to parse function call arguments: {event.arguments}")
        elif event.type == "error":
            raise Exception(f"Streaming error: {event.error}")
    
    return response_text, response_id, final_tool_calls

def handle_function_calls(final_tool_calls: Dict[str, Any], module: Union[str, int]) -> Tuple[Optional[Any], List[Dict[str, Any]]]:
    """Execute function calls from the AI response.

    Returns (transition_message, tool_output_messages). transition_message is
    the payload for a topic change, of which there are exactly two kinds: a
    level-2 update that has been *confirmed written* (a failed or rejected update
    returns its message to the model but must never move the student on - see
    ToolCallResult), or a `switch_topic` call the student explicitly asked for
    whose topic resolved to one of this module's own.
    tool_output_messages are the function_call_output entries the caller must
    feed back to the model - gpt-5-mini sometimes ends its turn on the bare
    function call with no accompanying text, and the model needs its own tool
    result back (via previous_response_id chaining) to produce the reply it
    still owes the student. See get_bot_response's follow-up call.
    """
    if not final_tool_calls:
        return None, []

    print(f"[Function Call] Processing function calls: {final_tool_calls}")
    tool_output_messages = []
    completed_topic = None
    switch_to = None

    for tool_call in final_tool_calls.values():
        arguments = tool_call["arguments"]
        if isinstance(arguments, dict):
            arguments = json.dumps(arguments)

        parsed_args = json.loads(arguments) if isinstance(arguments, str) else arguments
        result = handle_function_call(
            {"name": tool_call["name"], "arguments": parsed_args},
            st.session_state.user_id,
            module
        )

        if result is not None:
            tool_output_messages.append({
                "type": "function_call_output",
                "call_id": tool_call["call_id"],
                "output": result.output
            })

            if result.topic_completed and not completed_topic:
                completed_topic = result.topic_completed
            if result.topic_switched:
                switch_to = result.topic_switched

    # Every call in the response is executed before the topic is allowed to move.
    # A model that marks the current topic competent *and* honours "can we jump to
    # X" in one turn produces both calls, and moving the topic mid-loop would make
    # the later call land somewhere its arguments were never meant for - a
    # competency write attributed to the topic the student has only just arrived at.
    #
    # An explicit request wins over an automatic advance: if the student asked to
    # go somewhere, that is where they go.
    if switch_to:
        switch_message = handle_topic_switch_transition(switch_to, module)
        if switch_message:
            return switch_message, tool_output_messages

    if completed_topic:
        transition_message = handle_competency_update_transition(completed_topic, module)
        if transition_message:
            return transition_message, tool_output_messages

    return None, tool_output_messages


def generate_initial_question(topic: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Generate the opening Socratic question for a topic the student is starting.

    A standalone, unchained call on purpose: the new topic starts the model with no
    prior turns, so nothing from the previous topic bleeds into its opener. The
    response id is kept on the returned message so the student's first reply chains
    from the question they were actually asked.

    Returns the chat-history entry for the question, or None if generation failed -
    the caller still has a topic change to announce either way.
    """
    try:
        client = setup_openai_client()
        initial_prompt = build_initial_topic_prompt(topic)

        print(f"Given question: {topic.get('question', '(none - generated from topic description)')}")
        print(f"[Topic Change] Generating initial question for topic: {topic.get('name')}")
        response = client.responses.create(
            model=TutorConfig.MODEL_NAME,
            instructions=initial_prompt,
            input=[{"role": "system", "content": initial_prompt}],
            tools=[],
            reasoning={"effort": TutorConfig.REASONING_EFFORT},
            max_output_tokens=TutorConfig.MAX_OUTPUT_TOKENS
        )
        print(f"[Topic Change] Generated initial question: {response.output_text}")
        return ChatMessage(
            role="assistant",
            content=response.output_text,
            response_id=response.id,
            topic_name=topic.get("name", "")
        ).to_dict()
    except Exception as e:
        print(f"[Topic Change Error] Failed to generate initial question: {str(e)}")
        return None


def open_topic(module: Union[str, int], topic: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], bool]:
    """The messages that put the student into `topic`, and whether they are a replay.

    A topic is not always new to the student: they may have worked on it earlier
    and moved away - by asking to jump elsewhere, or by finishing a different
    topic and being wrapped back around to fill a gap - and reopening it with a
    brand new diagnostic question would throw that work away and ask them to prove
    themselves twice. So a topic that already has a logged conversation resumes
    from it, and only a topic with no history gets a fresh opening question.

    The flag matters to the caller: replayed messages are already in the
    conversation log and must not be written back to it, and they include the
    student's own turns, so they can't be drawn inside an assistant chat bubble.
    """
    topic_name = topic.get("name", "")
    resumed = load_logged_conversation_messages(
        st.session_state.get("user_id", ""), module, topic_name
    )
    if resumed:
        print(f"[Open Topic] Resuming {len(resumed)} logged message(s) for topic: {topic_name}")
        return resumed, True

    question = generate_initial_question(topic)
    return ([question] if question else []), False


def handle_topic_switch_transition(topic_name: str, module: Union[str, int]) -> Optional[Dict[str, Any]]:
    """Move the module to a topic the student asked for, and open it.

    Deliberately does *not* set the in-transition flag the completion path uses:
    nothing was written to the database here, so there is no progress panel racing
    to catch up, and the five-second guard that flag arms would swallow the
    student's next message for no reason.
    """
    previous_topic = (TutorState.get_current_topic(str(module)) or {}).get("name", "")

    next_topic = build_topic_payload(module, topic_name)
    if not next_topic:
        print(f"[Topic Switch] {topic_name!r} is not a topic of module {module} - not switching")
        return None

    TutorState.clear_topic_context(str(module), previous_topic)

    # Everything from here belongs to the new topic, so cut the model's context
    # over before the announcement and opening messages are added to the history.
    TutorState.set_topic_cutoff_index(str(module))
    set_active_topic(module, next_topic)

    opening_messages, opening_is_resumed = open_topic(module, next_topic)
    lead_message = (
        f"Sure - let's pick up where we left off on: {next_topic['name']}"
        if opening_is_resumed
        else f"Sure - let's switch to: {next_topic['name']}"
    )

    return {
        "type": "topic_switch",
        "lead_message": lead_message,
        # "Can we jump to X?" and the answer to it are about arriving, not about
        # the topic being left, so they are filed under the topic the student
        # asked for. Filed under the previous topic instead - which is right for
        # a completed topic's congratulation, and how this started out - they
        # became its final exchange, so coming back to it replayed a transcript
        # that ended by announcing a move to somewhere else, and handed that to
        # the model as the most recent thing said.
        "lead_topic": next_topic["name"],
        "opening_messages": opening_messages,
        "opening_is_resumed": opening_is_resumed,
        "previous_topic": previous_topic,
        "next_topic": next_topic["name"]
    }

def handle_competency_update_transition(completed_topic_name: str, module: Union[str, int]) -> Optional[Dict[str, Any]]:
    """Move the student on after a confirmed level-2 write for `completed_topic_name`.

    Callers must only reach here once the completion has actually been persisted;
    this function no longer inspects the model's function-call arguments to decide
    whether the topic was finished.
    """
    if TutorState.get_transition_state(str(module)):
        print(f"[Topic Transition] Lock already held for module {module}, skipping")
        return None

    try:
        # Acquire lock
        TutorState.set_transition_state(str(module), True)

        if TutorState.get_in_transition():
            print(f"[Topic Transition] Already in transition, skipping")
            return None

        # Advance from the topic just completed, so a topic can never hand back to
        # itself, and only mark the session "in transition" once there is somewhere
        # to go - the flag used to stick on when the module was finished, blocking
        # the student's next message for 5 seconds.
        next_topic = get_next_non_competent_topic(module, after_topic_name=completed_topic_name)
        if not next_topic:
            print(f"[Topic Transition] No topics left in module {module} after {completed_topic_name}")
            return None

        TutorState.set_in_transition(True)
        st.session_state["topic_transition_time"] = datetime.now().timestamp()

        TutorState.clear_topic_context(str(module), completed_topic_name)

        # Set the cutoff index for the new topic
        TutorState.set_topic_cutoff_index(str(module))

        set_active_topic(module, next_topic)

        # May be empty: generating the opening question can fail, and there is
        # still a completed topic to congratulate the student for.
        opening_messages, opening_is_resumed = open_topic(module, next_topic)

        return {
            "type": "topic_transition",
            "lead_message": f"Great! You've completed {completed_topic_name}. Let's move on to: {next_topic['name']}",
            "style": "success",
            # The congratulation closes out the topic it names, so it belongs to
            # that topic's transcript.
            "lead_topic": completed_topic_name,
            "opening_messages": opening_messages,
            "opening_is_resumed": opening_is_resumed,
            "previous_topic": completed_topic_name,
            "next_topic": next_topic["name"]
        }
    finally:
        # Release locks
        TutorState.set_transition_state(str(module), False)
        # Don't release the global transition state here - it will be released after the UI is refreshed

def get_bot_response(user_input: str, module: Union[str, int], stream: bool = True, vector_store_id: Optional[str] = None) -> str:
    """Get a response from the tutor bot and track competencies using function calling"""
    
    if st.session_state.get('debug_mode', False):
        st.write(f"Debug: Finding response to user input: {user_input}")
        st.write(f"Debug: Using model: {TutorConfig.MODEL_NAME}")

    # Created up front, before anything that can fail, so the except block
    # below always has somewhere to show a reply - previously an exception
    # anywhere in this function meant nothing was displayed, nothing was
    # logged, and current_prompt still reset, so a retry looked identical
    # and could fail the same silent way again with no visible trace.
    text_placeholder = st.empty()
    topic_name = ""

    try:
        # Check for topic transition
        transition_message = handle_topic_transition()
        if transition_message:
            # Add transition message to chat history
            TutorState.add_message(str(module), {
                "role": "assistant",
                "content": transition_message
            })
            return transition_message

        # Setup client and load prompt
        client = setup_openai_client()
        system_prompt = load_tutor_prompt()
        
        # Prepare tools configuration
        tools = prepare_tools_configuration(vector_store_id)
        
        # Get current topic and prepare conversation context. Resolved against this
        # module rather than read straight from session state: `current_topic` is a
        # single key shared by every module page, so it can be holding another
        # module's topic (see ensure_current_topic_for_module). Doing it here, once,
        # before the system prompt, the competency write and the conversation log
        # are built, keeps the whole turn consistent.
        current_topic = ensure_current_topic_for_module(module)
        if not current_topic or not current_topic.get("name"):
            print("[Error] No current topic found for module", module)
            return "I apologize, but I've lost track of our current topic. Could you please let me know what topic we were discussing?"

        topic_name = current_topic["name"]
        print(f"[Debug] Current topic: {topic_name}")

        # Deterministically mark the topic "in progress" (level 1) on the
        # student's first reply, rather than relying on the model to remember a
        # level-1 function call. Whether the student has attempted anything yet
        # is a plain fact, not a judgement call - only the 1->2 "competent"
        # transition needs the model's evaluation, via update_topic_competency.
        # Read fresh: on a stale snapshot a topic the student has already been
        # marked competent on reads as 0 here, and this write drops it back to 1.
        user_progress = get_fresh_user_progress()
        module_progress = user_progress.get("modules", {}).get(str(module), {})
        topic_progress = module_progress.get("topics", {}).get(topic_name, {})
        if topic_progress.get("progress", 0) == 0:
            update_competency(
                user_id=st.session_state.get("user_id", ""),
                topic_name=topic_name,
                level=1
            )
            invalidate_caches()

        # Get conversation context with the current topic
        conversation_context, previous_response_id = prepare_conversation_context(module, topic_name)
        print(f"[Debug] Conversation context length: {len(conversation_context)}")
        
        # Format input content without topic_name field for API compatibility
        input_content = format_input_content(conversation_context, user_input, previous_response_id)
        
        # Add topic context to system prompt instead of in the input messages.
        # The static tutor.md content goes first and the per-topic bits are
        # appended after: OpenAI's prompt caching matches the identical leading
        # prefix of `instructions`+`input` across calls, so putting the part
        # that changes every turn (topic name) at the front would defeat
        # caching for the ~1-2k token static block behind it.
        topic_description = current_topic.get('description', '')
        learning_outcomes = format_topic_learning_outcomes(current_topic)
        topic_overview = format_module_topic_overview(module, topic_name)
        system_prompt = f"""{system_prompt}

## Current Topic: {topic_name}
{topic_description if topic_description else ''}

{learning_outcomes}

{topic_overview}"""

        # Process the initial response
        response = client.responses.create(
            model=TutorConfig.MODEL_NAME,
            instructions=system_prompt,
            input=input_content,
            tools=tools,
            previous_response_id=previous_response_id,
            stream=stream,
            reasoning={"effort": TutorConfig.REASONING_EFFORT},
            max_output_tokens=TutorConfig.MAX_OUTPUT_TOKENS
        )
        
        # Process streaming response
        response_text, response_id, final_tool_calls = process_streaming_response(response, text_placeholder)
        
        # Handle function calls
        transition_message, tool_output_messages = handle_function_calls(final_tool_calls, module)
        if transition_message:
            # Both ways of leaving a topic - finishing it, or the student asking to
            # move - produce the same payload and are rendered the same way here.
            if isinstance(transition_message, dict) and transition_message.get("type") in (
                "topic_transition", "topic_switch"
            ):
                # A topic change spans two topics, and which one each message
                # belongs to is the payload's call, not this function's: a
                # congratulation closes out the topic it names, while "can we jump
                # to X" and its answer belong to X. The opening question always
                # belongs to the topic being started. All of it used to be filed
                # under whatever topic was current when the turn began, so the new
                # topic's opening question ended up inside the previous topic's
                # transcript - and load_logged_conversation_messages, which
                # replays history by (module, topic), then couldn't find it.
                previous_topic = transition_message.get("previous_topic") or topic_name
                next_topic_name = transition_message.get("next_topic", "")
                lead_topic = transition_message.get("lead_topic") or previous_topic
                lead_message = transition_message["lead_message"]
                opening_messages = transition_message.get("opening_messages") or []
                opening_is_resumed = transition_message.get("opening_is_resumed", False)
                is_success = transition_message.get("style") == "success"

                lead_entry = {
                    "role": "assistant",
                    "content": lead_message,
                    "topic_name": lead_topic
                }
                if is_success:
                    lead_entry["style"] = "success"
                TutorState.add_message(str(module), lead_entry)

                # The new topic's messages: either its freshly generated opening
                # question, or its earlier conversation replayed.
                for message in opening_messages:
                    TutorState.add_message(str(module), message)

                # Both messages go inside one container: text_placeholder is a
                # single st.empty(), so writing to it twice replaced the
                # announcement with the opening question and the student saw only
                # half the handover until the next rerun repainted the history.
                # Replayed history is left out - it contains the student's own
                # turns, and this is drawn inside an assistant chat bubble - and
                # the rerun below repaints it in full with the right roles.
                with text_placeholder.container():
                    if is_success:
                        st.success(lead_message)
                    else:
                        st.markdown(lead_message)
                    if not opening_is_resumed:
                        for message in opening_messages:
                            st.markdown(message["content"])

                st.session_state["tutor_topic_changed"] = True

                # Log the conversation before returning. Replayed messages are
                # already in the log - writing them back would duplicate the
                # topic's history every time the student returns to it.
                if "user_id" in st.session_state:
                    logger.log_conversation(
                        st.session_state.user_id,
                        str(module),
                        lead_topic,
                        [[user_input, lead_message]]
                    )
                    if not opening_is_resumed:
                        for message in opening_messages:
                            logger.log_conversation(
                                st.session_state.user_id,
                                str(module),
                                next_topic_name,
                                [["", message["content"]]]
                            )

                # Return combined message for backward compatibility
                if opening_is_resumed:
                    return lead_message
                return "\n\n".join([lead_message] + [m["content"] for m in opening_messages])
            else:
                # Handle legacy string format
                TutorState.add_message(str(module), {
                    "role": "assistant",
                    "content": transition_message
                })
                # Display the transition message in the UI
                text_placeholder.markdown(transition_message)
                
                # Log the conversation before returning
                if "user_id" in st.session_state:
                    logger.log_conversation(
                        st.session_state.user_id,
                        str(module),
                        topic_name,
                        [[user_input, transition_message]]
                    )
                
                return transition_message

        # The model sometimes ends its turn with no visible text at all - either
        # a bare function call (all its output budget went to internal
        # reasoning) or, occasionally, nothing whatsoever, no function call
        # either. Either way the student is owed a reply, so request a
        # follow-up rather than showing a blank bubble. Chained via
        # previous_response_id: when there were tool calls, only their outputs
        # go in as input (the function_call item is already part of that
        # response server-side); otherwise a minimal nudge is enough since the
        # full conversation is already attached via the chain.
        if not response_text.strip():
            print("[Function Call] No text in the reply - requesting a follow-up")
            followup_input = tool_output_messages if tool_output_messages else [
                {"role": "user", "content": "(Continue - please give your reply for this turn.)"}
            ]
            followup_response = client.responses.create(
                model=TutorConfig.MODEL_NAME,
                instructions=system_prompt,
                input=followup_input,
                tools=tools,
                previous_response_id=response_id,
                stream=stream,
                reasoning={"effort": TutorConfig.REASONING_EFFORT},
                max_output_tokens=TutorConfig.MAX_OUTPUT_TOKENS
            )
            response_text, response_id, more_tool_calls = process_streaming_response(followup_response, text_placeholder)
            if more_tool_calls:
                print(f"[Function Call] Unexpected additional function call(s) in follow-up reply, ignoring: {more_tool_calls}")
            if not response_text.strip():
                # Last resort: don't persist/show a blank bubble if the model
                # still didn't produce text on the follow-up.
                print("[Function Call] Follow-up reply was also empty - using fallback text")
                response_text = "Sorry, I didn't quite catch that - could you try rephrasing or asking again?"
                text_placeholder.markdown(response_text)

        # Create new message with topic information for our internal state
        new_message = ChatMessage(
            role="assistant",
            content=response_text,
            response_id=response_id,
            topic_name=topic_name
        )
        
        # Add to chat history using TutorState
        TutorState.add_message(str(module), new_message.to_dict())
        
        # Log the conversation
        if "user_id" in st.session_state:
            logger.log_conversation(
                st.session_state.user_id,
                str(module),
                topic_name,
                [[user_input, response_text]]
            )
        
        return response_text
        
    except Exception as e:
        # Never let a failure here be invisible: show something, store it in
        # chat history, and log it, so the turn isn't silently dropped and a
        # retry doesn't look identical to an untried message. This is what was
        # missing before - the exception was caught, but the returned message
        # was never displayed, stored, or logged, and current_prompt still
        # reset, so a student's retry could fail the exact same silent way
        # with no trace anywhere.
        # The traceback, not just the message: this block covers the whole turn -
        # two API calls, the competency write, the topic change and the logging -
        # and `str(e)` alone ("'typing.Union' object has no attribute
        # '__discriminator__'") names none of them.
        print(f"[Error] Error in get_bot_response: {str(e)}")
        traceback.print_exc()
        error_text = "Sorry, something went wrong on my end - please try sending your message again."
        text_placeholder.error(error_text)
        TutorState.add_message(str(module), {
            "role": "assistant",
            "content": error_text,
            "topic_name": topic_name
        })
        if "user_id" in st.session_state:
            logger.log_conversation(
                st.session_state.user_id,
                str(module),
                topic_name,
                [[user_input, f"[error] {str(e)}"]]
            )
        return error_text

def render_tutor_interface(module_id: Union[str, int], module_title: str, module_description: str, topics: List[Any], vector_store_id: Optional[str] = None) -> None:
    """Render the tutor interface for a specific module"""
    try:
        st.title(f"Module {module_id}: {module_title}")
        print(f"[Tutor Interface] Rendering interface for module {module_id}")
        
        # Initialize vector store ID in session state if not exists
        vector_store_key = f"vector_store_id_{module_id}"
        if vector_store_id and vector_store_key not in st.session_state:
            st.session_state[vector_store_key] = vector_store_id
        
        with st.expander("ℹ️ About the AI Tutor", expanded=False):
            st.write("""
            **Welcome to your Socratic AI Tutor**
            
            The AI Tutor will help you learn engineering concepts through guided questioning rather than giving direct answers.
            This approach helps develop critical thinking and deeper understanding of the subject.
            
            **Competency Levels:**
            - 🔴 Not started
            - 🟠 In Progress
            - ✅ Completed
            
            **How to Use:**
            1. The AI Tutor will focus on one topic at a time
            2. Answer the AI Tutor's questions to demonstrate understanding
            3. Once you show mastery of a topic, we'll move to the next one
            """)
        
        # Render sidebar
        render_sidebar(module_title)

        if st.session_state.get('debug_mode', False):
            st.write(f"Debug: Using model: {TutorConfig.MODEL_NAME}")
        
        # Get user's progress from cache
        progress_key = f"progress_summary_{module_id}"
        if progress_key not in st.session_state:
            st.session_state[progress_key] = get_module_progress_summary(module_id)
        progress_summary = st.session_state[progress_key]
        print(f"[Tutor Interface] Progress summary for module {module_id}")
        
        # Initialize chat history for this module if not exists
        chat_history_key = TutorState._get_message_key(str(module_id))
        print(f"[Tutor Interface] Chat history key: {chat_history_key}")
        print(f"[Tutor Interface] Chat history exists: {chat_history_key in st.session_state}")
        
        if chat_history_key not in st.session_state:
            # Where the student left off, or the first topic they haven't finished
            next_topic = get_resume_topic(module_id)
            print(f"[Tutor Interface] Resuming module {module_id} at: {next_topic}")

            if next_topic:
                # Store current topic in session state, scoped to this module
                set_active_topic(module_id, next_topic)
                print(f"[Tutor Interface] Stored current topic in session state: {next_topic}")

                # Initialize empty chat history - either replayed from a logged
                # conversation below, or the first message generated fresh.
                st.session_state[chat_history_key] = []
                print(f"[Tutor Interface] Initialized empty chat history for module {module_id}")

                # Set the cutoff index for the new topic
                TutorState.set_topic_cutoff_index(str(module_id))

                # A topic the student has already worked on (they logged out
                # mid-topic, or moved away and came back) resumes from its logged
                # conversation rather than starting over with a new question.
                opening_messages, opening_is_resumed = open_topic(module_id, next_topic)
                for message in opening_messages:
                    TutorState.add_message(str(module_id), message)

                # Replayed messages are already in the conversation log; only a
                # newly generated opening question needs writing to it.
                if opening_messages and not opening_is_resumed and "user_id" in st.session_state:
                    for message in opening_messages:
                        logger.log_conversation(
                            st.session_state.user_id,
                            str(module_id),
                            next_topic["name"],
                            [["", message["content"]]]  # Empty user message since this is the initial question
                        )

                print(f"[Tutor Interface] Chat history length for module {module_id}: {len(st.session_state[chat_history_key])}")
            else:
                print(f"[Tutor Interface] No next topic found for module {module_id}")

        # Whether the module is finished is checked on every render, not only while
        # initialising the chat history - a student who completes the final topic
        # mid-session already has a history, so that branch never ran for them and
        # they were left with a live chat box and no topic behind it.
        module_complete = is_module_complete(module_id)
        if module_complete:
            st.success("🎉 Congratulations! You've completed all topics in this module!")

        # Display module information
        st.markdown(module_description)
        
        # Create containers for different sections
        progress_container = st.container()
        chat_container = st.container()
        tutorial_container = st.container()
        
        # Render progress summary in its container
        with progress_container:
            render_progress_summary(progress_summary)
        
        # Render chat interface in its container
        with chat_container:
            # Add a divider before the chat
            st.markdown("---")
            st.subheader("Chat with the AI Tutor")
            
            # Initialize session state for current prompt if not exists
            if "current_prompt" not in st.session_state:
                st.session_state.current_prompt = None
            
            # Create a container for the chat history
            history_container = st.container()
            
            # Display chat history in the container
            with history_container:
                if chat_history_key in st.session_state:
                    print(f"[Tutor Interface] Displaying chat history for module {module_id}. Chat history length: {len(st.session_state[chat_history_key])}")
                    # Use the new method to get complete chat history for UI
                    full_chat_history = TutorState.get_chat_history_for_ui(str(module_id))
                    render_chat_history(full_chat_history)
                else:
                    print(f"[Tutor Interface] No chat history found for module {module_id}")
            
            # Check if we need to process a new message
            if st.session_state.current_prompt:
                prompt = st.session_state.current_prompt
                try:
                    # Get and display assistant response
                    with st.chat_message("assistant"):
                        response = get_bot_response(prompt, module_id, stream=True, vector_store_id=vector_store_id)
                        # The response is already displayed via the placeholder in get_bot_response
                    
                    # Reset the current prompt
                    st.session_state.current_prompt = None

                    # Popped before the checks below, not inside them: short-circuit
                    # evaluation would leave the flag set and fire a stray rerun on
                    # some later turn.
                    topic_changed = st.session_state.pop("tutor_topic_changed", False)

                    # The progress panel above was already rendered this run from
                    # the pre-turn cached summary (see progress_key above). A
                    # competency update - even a plain 0->1 "in progress" tick with
                    # no topic transition - calls invalidate_caches(), which drops
                    # progress_key from session_state; that alone doesn't repaint
                    # what's already on screen; only a rerun does, which is why the
                    # status used to appear stuck until the next unrelated refresh.
                    # A topic change repaints too: replayed history has to be drawn
                    # by render_chat_history to get the student's own turns right.
                    if topic_changed or TutorState.get_in_transition() or progress_key not in st.session_state:
                        # Force a rerun to refresh the UI with the new topic/progress
                        st.rerun()
                
                except Exception as e:
                    print(f"[Error] Failed to process message: {str(e)}")
                    st.error(f"Error processing your message: {str(e)}")
                    if st.session_state.get("debug_mode", False):
                        st.exception(e)
                    st.info("Please try rephrasing your question or try again later.")
            
            # Add a small space between chat history and input
            st.markdown("<br>", unsafe_allow_html=True)
            
            # Chat input. Disabled once every topic is at level 2: there is no
            # current topic left to attribute the conversation to, so a message
            # sent here could only be answered with an apology.
            chat_placeholder = (
                "You've completed every topic in this module"
                if module_complete
                else "Display your competency by answering questions"
            )
            if prompt := st.chat_input(chat_placeholder, disabled=module_complete):
                # Display the user message immediately
                # with history_container:
                #     with st.chat_message("user"):
                #         st.markdown(prompt)
                
                # Store the prompt in session state
                st.session_state.current_prompt = prompt
                
                # Get current topic name
                current_topic = TutorState.get_current_topic(str(module_id))
                topic_name = current_topic.get("name", "")
                
                # Add user message to chat history using TutorState
                user_message = ChatMessage(
                    role="user", 
                    content=prompt,
                    topic_name=topic_name
                ).to_dict()
                TutorState.add_message(str(module_id), user_message)
                
                # Trigger rerun to process the message
                st.rerun()
        
        # Render tutorial questions in its container
        with tutorial_container:
            # Add tutorial questions section
            st.markdown("---")
            st.subheader("Tutorial Questions")
            
            # Get tutorial questions for the current module
            modules_data = get_cached_modules_data()
            if modules_data:
                # Locate the module by its index, never by title.
                module_data = find_module_by_index(modules_data, module_id)

                if module_data:
                    tutorial_questions = module_data.get("tutorial_questions", {})
                    if isinstance(tutorial_questions, list):
                        # Convert list format to dictionary format using simple index string keys
                        tutorial_questions = {str(i + 1): q for i, q in enumerate(tutorial_questions)}
                    
                    if tutorial_questions:
                        # Get user progress data from cache
                        user_progress = get_cached_user_progress()
                        # Nested structure: user -> modules -> module_id -> questions
                        module_progress = user_progress.get("modules", {}).get(str(module_id), {})
                        user_questions_progress = module_progress.get("questions", {})

                        for question_id, question_info in tutorial_questions.items():
                            if not isinstance(question_info, dict):
                                continue
                            
                            question_title = question_info.get("label", f"Question {question_id}")
                            
                            q_data = user_questions_progress.get(question_id, {})

                            # Full competency implies completion even if status lags.
                            status = q_data.get("status", "not_started")
                            competency_level = q_data.get("competency_level", 0)
                            if competency_level >= 2:
                                status = "completed"

                            status_emoji = get_status_emoji(status)

                            attempts = q_data.get("attempts", 0)
                            
                            # Create columns for status, button, and question
                            col1, col2, col3 = st.columns([1, 6, 2])
                            
                            with col1:
                                # Use the calculated status_emoji directly
                                status_color = 'green' if status == 'completed' else 'orange' if status == 'in_progress' else 'red'
                                st.markdown(f"<span style='color:{status_color}'>{status_emoji}</span>", unsafe_allow_html=True)
                            
                            with col3:
                                # Create link to assessor with query parameters
                                assessor_url = f"{BASE_URL}Assessor?module={module_id}&question={question_id}"
                                if st.button("Try Question", key=f"try_question_{question_id}", help=f"Attempts: {attempts}"):
                                    # Store the module and question IDs in session state
                                    st.session_state.selected_module_id = module_id
                                    st.session_state.selected_question_id = question_id
                                    st.switch_page("pages/8_Assessor.py")
                            
                            with col2:
                                st.markdown(question_title)
                                if attempts > 0:
                                    st.caption(f"Attempts: {attempts}")
                    else:
                        st.info("No tutorial questions available for this module.")
                else:
                    st.warning("Module data not found.")
            else:
                st.warning("Unable to load module data.")
                
    except Exception as e:
        st.error(f"Error rendering tutor interface: {str(e)}")
        if st.session_state.get("debug_mode", False):
            st.exception(e)
        st.info("Please refresh the page or try again later.") 