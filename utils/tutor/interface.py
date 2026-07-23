"""Main tutor interface implementation"""
import sys
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
    handle_competency_update,
    handle_competency_check,
    get_module_progress_summary,
    get_next_non_competent_topic
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
    """Invalidate all cached data when updates occur"""
    keys_to_clear = [
        "cached_modules_data",
        "cached_user_progress",
        "progress_summary_1",
        "progress_summary_2",
        "progress_summary_3",
        "progress_summary_4",
        "progress_summary_5",
        "progress_summary_6"
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
    """Get user progress from cache or fetch if not available"""
    if "cached_user_progress" not in st.session_state:
        st.session_state.cached_user_progress = get_user_progress(st.session_state.user_id)
    return st.session_state.cached_user_progress

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
    for conv in logger.get_user_conversations(user_id):
        if conv.get("module") == str(module_id) and conv.get("topic") == topic_name:
            messages = []
            for pair in conv.get("conversation", []):
                user_msg, assistant_msg = (list(pair) + ["", ""])[:2]
                if user_msg:
                    messages.append(ChatMessage(role="user", content=user_msg, topic_name=topic_name).to_dict())
                if assistant_msg:
                    messages.append(ChatMessage(role="assistant", content=assistant_msg, topic_name=topic_name).to_dict())
            return messages
    return []

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

def handle_function_call(tool_call: Dict[str, Any], user_id: str) -> Optional[str]:
    """Handle function calls from the AI response"""
    func_name = tool_call["name"]
    func_args = tool_call["arguments"]  # Already parsed JSON from streaming
    print(f"[Function Call] Received function call: {func_name} with arguments: {func_args}")
    if func_name == "update_topic_competency":
        return handle_competency_update(func_args, user_id)
    elif func_name == "get_topic_competency":
        return handle_competency_check(func_args, user_id)
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
    tools = [
        {
            "type": "function",
            "name": "update_topic_competency",
            "description": "Update a student's competency level for a specific topic",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic_name": {
                        "type": "string",
                        "description": "The name of the topic to update"
                    },
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
                "required": ["topic_name", "level", "reason"]
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

def format_input_content(conversation_context: List[Dict[str, Any]], user_input: str) -> List[Dict[str, Any]]:
    """Format the input content for the AI response"""
    input_content = []
    
    # Get current topic for context
    current_topic = TutorState.get_current_topic()
    current_topic_name = current_topic.get("name", "") if current_topic else ""
    
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
    the topic-transition payload once a level-2 update completes the topic.
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

    for tool_call in final_tool_calls.values():
        arguments = tool_call["arguments"]
        if isinstance(arguments, dict):
            arguments = json.dumps(arguments)

        parsed_args = json.loads(arguments) if isinstance(arguments, str) else arguments
        result = handle_function_call({"name": tool_call["name"], "arguments": parsed_args}, st.session_state.user_id)

        if result is not None:
            tool_output_messages.append({
                "type": "function_call_output",
                "call_id": tool_call["call_id"],
                "output": result
            })

            if tool_call["name"] == "update_topic_competency":
                transition_message = handle_competency_update_transition(tool_call, module)
                if transition_message:
                    return transition_message, tool_output_messages

    return None, tool_output_messages

def handle_competency_update_transition(tool_call: Dict[str, Any], module: Union[str, int]) -> Optional[Dict[str, Any]]:
    """Handle transition when a topic is completed"""
    args = tool_call["arguments"]
    if args.get("level") == 2:  # Topic completed
        if TutorState.get_transition_state(str(module)):
            print(f"[Topic Transition] Lock already held for module {module}, skipping")
            return None
            
        try:
            # Acquire lock
            TutorState.set_transition_state(str(module), True)
            
            if TutorState.get_in_transition():
                print(f"[Topic Transition] Already in transition, skipping")
                return None
            
            # Set global transition state and timestamp
            TutorState.set_in_transition(True)
            st.session_state["topic_transition_time"] = datetime.now().timestamp()
            
            next_topic = get_next_non_competent_topic(module)
            if next_topic:
                old_topic = TutorState.get_current_topic()
                old_topic_name = old_topic.get("name", "")
                TutorState.clear_topic_context(str(module), old_topic_name)
                
                # Set the cutoff index for the new topic
                TutorState.set_topic_cutoff_index(str(module))
                
                TutorState.set_current_topic(next_topic)
                
                # Generate initial Socratic question for the new topic
                try:
                    client = setup_openai_client()
                    initial_prompt = build_initial_topic_prompt(next_topic)

                    print(f"Given question: {next_topic.get('question', '(none - generated from topic description)')}")
                    print(f"[Topic Transition] Generating initial question for new topic: {next_topic['name']}")
                    response = client.responses.create(
                        model=TutorConfig.MODEL_NAME,
                        instructions=initial_prompt,
                        input=[{"role": "system", "content": initial_prompt}],
                        tools=[],
                        reasoning={"effort": TutorConfig.REASONING_EFFORT},
                        max_output_tokens=TutorConfig.MAX_OUTPUT_TOKENS
                    )
                    initial_question = response.output_text
                    print(f"[Topic Transition] Generated initial question: {initial_question}")
                    
                    # Return dictionary with congratulatory text and initial question
                    return {
                        "type": "topic_transition",
                        "congratulations": f"Great! You've completed the previous topic. Let's move on to: {next_topic['name']}",
                        "initial_question": initial_question
                    }
                except Exception as e:
                    print(f"[Topic Transition Error] Failed to generate initial question: {str(e)}")
                    # Still return the congratulatory message even if question generation fails
                    return {
                        "type": "topic_transition",
                        "congratulations": f"Great! You've completed the previous topic. Let's move on to: {next_topic['name']}",
                        "initial_question": None
                    }
        finally:
            # Release locks
            TutorState.set_transition_state(str(module), False)
            # Don't release the global transition state here - it will be released after the UI is refreshed
    
    return None

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
        
        # Get current topic and prepare conversation context
        current_topic = TutorState.get_current_topic()
        if not current_topic:
            print("[Error] No current topic found in state")
            return "I apologize, but I've lost track of our current topic. Could you please let me know what topic we were discussing?"
            
        topic_name = current_topic.get("name", "")
        if not topic_name:
            print("[Error] Current topic has no name")
            return "I apologize, but I've lost track of our current topic. Could you please let me know what topic we were discussing?"
            
        print(f"[Debug] Current topic: {topic_name}")

        # Deterministically mark the topic "in progress" (level 1) on the
        # student's first reply, rather than relying on the model to remember a
        # level-1 function call. Whether the student has attempted anything yet
        # is a plain fact, not a judgement call - only the 1->2 "competent"
        # transition needs the model's evaluation, via update_topic_competency.
        user_progress = get_cached_user_progress()
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
        input_content = format_input_content(conversation_context, user_input)
        
        # Add topic context to system prompt instead of in the input messages.
        # The static tutor.md content goes first and the per-topic bits are
        # appended after: OpenAI's prompt caching matches the identical leading
        # prefix of `instructions`+`input` across calls, so putting the part
        # that changes every turn (topic name) at the front would defeat
        # caching for the ~1-2k token static block behind it.
        topic_description = current_topic.get('description', '')
        learning_outcomes = format_topic_learning_outcomes(current_topic)
        system_prompt = f"""{system_prompt}

## Current Topic: {topic_name}
{topic_description if topic_description else ''}

{learning_outcomes}"""

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
            # Check if transition_message is a dictionary with type "topic_transition"
            if isinstance(transition_message, dict) and transition_message.get("type") == "topic_transition":
                # Add congratulatory message to chat history with success styling
                TutorState.add_message(str(module), {
                    "role": "assistant",
                    "content": transition_message["congratulations"],
                    "style": "success"
                })
                
                # Add initial question as a separate message with normal styling if it exists
                if transition_message.get("initial_question"):
                    TutorState.add_message(str(module), {
                        "role": "assistant",
                        "content": transition_message["initial_question"]
                    })
                
                # Display the messages in the UI
                text_placeholder.success(transition_message["congratulations"])
                if transition_message.get("initial_question"):
                    text_placeholder.markdown(transition_message["initial_question"])
                
                # Log the conversation before returning
                if "user_id" in st.session_state:
                    logger.log_conversation(
                        st.session_state.user_id,
                        str(module),
                        topic_name,
                        [[user_input, transition_message["congratulations"]]]
                    )
                    if transition_message.get("initial_question"):
                        logger.log_conversation(
                            st.session_state.user_id,
                            str(module),
                            topic_name,
                            [["", transition_message["initial_question"]]]
                        )
                
                # Return combined message for backward compatibility
                return transition_message["congratulations"] + "\n\n" + (transition_message.get("initial_question") or "")
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
        print(f"[Error] Error in get_bot_response: {str(e)}")
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
            # Get the next non-competent topic
            next_topic = get_next_non_competent_topic(module_id)
            print(f"[Tutor Interface] Next topic for module {module_id}: {next_topic}")
            
            if next_topic:
                # Store current topic in session state
                st.session_state["current_topic"] = next_topic
                print(f"[Tutor Interface] Stored current topic in session state: {next_topic}")

                # Initialize empty chat history - either replayed from a logged
                # conversation below, or the first message generated fresh.
                st.session_state[chat_history_key] = []
                print(f"[Tutor Interface] Initialized empty chat history for module {module_id}")

                # Set the cutoff index for the new topic
                TutorState.set_topic_cutoff_index(str(module_id))

                # If this competency already has a logged conversation (e.g. the
                # student logged out mid-topic and back in), replay it instead of
                # starting the topic over and generating a new opening question.
                existing_messages = load_logged_conversation_messages(
                    st.session_state.get("user_id", ""), module_id, next_topic.get("name", "")
                )

                if existing_messages:
                    print(f"[Tutor Interface] Restoring {len(existing_messages)} logged messages for topic: {next_topic.get('name')}")
                    for message in existing_messages:
                        TutorState.add_message(str(module_id), message)
                else:
                    # Generate initial Socratic question
                    try:
                        client = setup_openai_client()
                        current_topic = st.session_state["current_topic"]
                        initial_prompt = build_initial_topic_prompt(current_topic)

                        print(f"[Tutor Interface] Generating initial question for topic: {current_topic['name']}")
                        response = client.responses.create(
                            model=TutorConfig.MODEL_NAME,
                            instructions=initial_prompt,
                            input=[{"role": "system", "content": initial_prompt}],
                            tools=[],
                            reasoning={"effort": TutorConfig.REASONING_EFFORT},
                            max_output_tokens=TutorConfig.MAX_OUTPUT_TOKENS
                        )
                        print(f"[Tutor Interface] Generated initial question: {response.output_text}")

                        # Add the initial question to chat history using TutorState
                        initial_message = ChatMessage(
                            role="assistant",
                            content=response.output_text,
                            response_id=response.id
                        ).to_dict()
                        TutorState.add_message(str(module_id), initial_message)

                        # Log the initial question
                        if "user_id" in st.session_state:
                            logger.log_conversation(
                                st.session_state.user_id,
                                str(module_id),
                                current_topic['name'],
                                [["", response.output_text]]  # Empty user message since this is the initial question
                            )

                        print(f"[Tutor Interface] Added initial question to chat history. Current chat history length: {len(st.session_state[chat_history_key])}")
                    except Exception as e:
                        print(f"[Tutor Interface Error] Failed to generate initial question: {str(e)}")
                        if st.session_state.get("debug_mode", False):
                            st.error(f"Error generating initial question: {str(e)}")
                        raise  # Re-raise the exception to be handled by the caller
            else:
                print(f"[Tutor Interface] No next topic found for module {module_id}")
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

                    # The progress panel above was already rendered this run from
                    # the pre-turn cached summary (see progress_key above). A
                    # competency update - even a plain 0->1 "in progress" tick with
                    # no topic transition - calls invalidate_caches(), which drops
                    # progress_key from session_state; that alone doesn't repaint
                    # what's already on screen; only a rerun does, which is why the
                    # status used to appear stuck until the next unrelated refresh.
                    if TutorState.get_in_transition() or progress_key not in st.session_state:
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
            
            # Chat input
            if prompt := st.chat_input("Display your competency by answering questions"):
                # Display the user message immediately
                # with history_container:
                #     with st.chat_message("user"):
                #         st.markdown(prompt)
                
                # Store the prompt in session state
                st.session_state.current_prompt = prompt
                
                # Get current topic name
                current_topic = TutorState.get_current_topic()
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