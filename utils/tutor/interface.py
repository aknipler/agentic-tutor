"""Main tutor interface implementation"""
import streamlit as st
import openai
import json
from typing import Optional, Dict, Any, Union, List, Tuple
from datetime import datetime

from .config.settings import TutorConfig, MODULE_TITLES
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

def setup_openai_client() -> openai.OpenAI:
    """Set up and return the OpenAI client"""
    if "openai_client" not in st.session_state:
        client = openai.OpenAI()
        st.session_state["openai_client"] = client
    return st.session_state["openai_client"]

def clean_file_id(file_id: Optional[str]) -> Optional[str]:
    """Clean the file ID by removing any non-printable characters and extra whitespace."""
    if not file_id:
        return None
    cleaned_id = ''.join(char for char in file_id if char.isprintable()).strip()
    return cleaned_id

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

def prepare_tools_configuration(module: Union[str, int]) -> List[Dict[str, Any]]:
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

    vector_store_key = f"vector_store_id_{module}"
    if vector_store_key in st.session_state:
        vector_store_id = st.session_state[vector_store_key]
        if vector_store_id:
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

def format_input_content(conversation_context: List[Dict[str, Any]], user_input: str, file_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Format the input content for the AI response"""
    input_content = []
    
    # Get current topic for context
    current_topic = TutorState.get_current_topic()
    current_topic_name = current_topic.get("name", "") if current_topic else ""
    
    # Always include file context if available
    if file_id:
        cleaned_file_id = clean_file_id(file_id)
        if cleaned_file_id:
            input_content.append({
                "role": "system",
                "content": [{"type": "input_file", "file_id": cleaned_file_id}]
            })
    
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

def handle_function_calls(final_tool_calls: Dict[str, Any], input_content: List[Dict[str, Any]], module: Union[str, int]) -> Optional[str]:
    """Handle function calls from the AI response"""
    if not final_tool_calls:
        return None
        
    print(f"[Function Call] Processing function calls: {final_tool_calls}")
    new_messages = list(input_content)
    
    for tool_call in final_tool_calls.values():
        arguments = tool_call["arguments"]
        if isinstance(arguments, dict):
            arguments = json.dumps(arguments)
        
        function_call_message = {
            "type": "function_call",
            "id": tool_call["id"],
            "call_id": tool_call["call_id"],
            "name": tool_call["name"],
            "arguments": arguments
        }
        new_messages.append(function_call_message)
        
        parsed_args = json.loads(arguments) if isinstance(arguments, str) else arguments
        result = handle_function_call({"name": tool_call["name"], "arguments": parsed_args}, st.session_state.user_id)
        
        if result is not None:
            function_output_message = {
                "type": "function_call_output",
                "call_id": tool_call["call_id"],
                "output": result
            }
            new_messages.append(function_output_message)
            
            if tool_call["name"] == "update_topic_competency":
                return handle_competency_update_transition(tool_call, module)
    
    return None

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
                    topic_description = next_topic.get('description', '')
                    initial_prompt = f"""You are starting a new topic: {next_topic['name']}
                    {f'Topic description: {topic_description}' if topic_description else ''}
                    
                    Your task is to:
                    1. Begin with a direct, engaging question that immediately focuses on the core concept of the topic
                    2. The question should be specific and practical, relating to real-world chemical engineering applications
                    3. Avoid generic introductions or small talk - get straight to the topic
                    4. Make the question challenging but approachable, encouraging critical thinking
                    5. If possible, include a brief real-world scenario or example to make the question more concrete
                    
                    Generate your response as a single, focused Socratic question that will start the discussion. Do not include any introductory text or explanations - just the question itself."""
                    
                    print(f"[Topic Transition] Generating initial question for new topic: {next_topic['name']}")
                    response = client.responses.create(
                        model=TutorConfig.MODEL_NAME,
                        instructions=initial_prompt,
                        input=[{"role": "system", "content": initial_prompt}],
                        tools=[]
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

def get_bot_response(user_input: str, module: Union[str, int], file_id: Optional[str] = None, stream: bool = True) -> str:
    """Get a response from the tutor bot and track competencies using function calling"""
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
        tools = prepare_tools_configuration(module)
        
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
        
        # Get conversation context with the current topic
        conversation_context, previous_response_id = prepare_conversation_context(module, topic_name)
        print(f"[Debug] Conversation context length: {len(conversation_context)}")
        
        # Format input content without topic_name field for API compatibility
        input_content = format_input_content(conversation_context, user_input, file_id)
        
        # Add topic context to system prompt instead of in the input messages
        topic_description = current_topic.get('description', '')
        system_prompt = f"""Current Topic: {topic_name}
{topic_description if topic_description else ''}

{system_prompt}"""
        
        # Create placeholder for streaming text
        text_placeholder = st.empty()
        
        # Process the initial response
        response = client.responses.create(
            model=TutorConfig.MODEL_NAME,
            instructions=system_prompt,
            input=input_content,
            tools=tools,
            previous_response_id=previous_response_id,
            stream=stream
        )
        
        # Process streaming response
        response_text, response_id, final_tool_calls = process_streaming_response(response, text_placeholder)
        
        # Handle function calls
        transition_message = handle_function_calls(final_tool_calls, input_content, module)
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
        print(f"[Error] Error in get_bot_response: {str(e)}")
        return f"An error occurred: {str(e)}"

def render_tutor_interface(module_id: Union[str, int], module_title: str, module_description: str, topics: List[Any], file_id: Optional[str] = None) -> None:
    """Render the tutor interface for a specific module"""
    try:
        st.title(f"Module {module_id}: {module_title}")
        print(f"[Tutor Interface] Rendering interface for module {module_id}")
        
        # Initialize vector store ID in session state if not exists
        vector_store_key = f"vector_store_id_{module_id}"
        if vector_store_key not in st.session_state:
            modules_data = get_cached_modules_data()
            module_id_str = str(module_id)
            if "modules" in modules_data and isinstance(modules_data["modules"], list):
                for m in modules_data["modules"]:
                    if m.get("title") == MODULE_TITLES.get(module_id_str):
                        vector_store_id = m.get("vector_store_id")
                        if vector_store_id:
                            st.session_state[vector_store_key] = vector_store_id
                        break
        
        with st.expander("ℹ️ About the AI Tutor", expanded=False):
            st.write("""
            **Welcome to AI-Chris, your Socratic Chemical Engineering Tutor**
            
            AI-Chris will help you learn chemical engineering concepts through guided questioning rather than giving direct answers.
            This approach helps develop critical thinking and deeper understanding of the subject.
            
            **Competency Levels:**
            - 🔴 Not started
            - 🟠 In Progress
            - ✅ Completed
            
            **How to Use:**
            1. AI-Chris will focus on one topic at a time
            2. Answer AI-Chris's questions to demonstrate understanding
            3. Once you show mastery of a topic, we'll move to the next one
            """)
        
        # Render sidebar
        render_sidebar(module_title)
        
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
                
                # Initialize empty chat history - the first message will be generated by the system prompt
                st.session_state[chat_history_key] = []
                print(f"[Tutor Interface] Initialized empty chat history for module {module_id}")
                
                # Set the cutoff index for the new topic
                TutorState.set_topic_cutoff_index(str(module_id))
                
                # Generate initial Socratic question
                try:
                    client = setup_openai_client()
                    current_topic = st.session_state["current_topic"]
                    topic_description = current_topic.get('description', '')
                    initial_prompt = f"""You are starting a new topic: {current_topic['name']}
                    {f'Topic description: {topic_description}' if topic_description else ''}
                    
                    Your task is to:
                    1. Begin with a direct, engaging question that immediately focuses on the core concept of the topic
                    2. The question should be specific and practical, relating to real-world chemical engineering applications
                    3. Avoid generic introductions or small talk - get straight to the topic
                    4. Make the question challenging but approachable, encouraging critical thinking
                    5. If possible, include a brief real-world scenario or example to make the question more concrete
                    
                    Generate your response as a single, focused Socratic question that will start the discussion. Do not include any introductory text or explanations - just the question itself."""
                    
                    print(f"[Tutor Interface] Generating initial question for topic: {current_topic['name']}")
                    response = client.responses.create(
                        model=TutorConfig.MODEL_NAME,
                        instructions=initial_prompt,
                        input=[{"role": "system", "content": initial_prompt}],
                        tools=[]
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
            st.subheader("Chat with AI-Chris")
            
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
                        response = get_bot_response(prompt, module_id, file_id, stream=True)
                        # The response is already displayed via the placeholder in get_bot_response
                    
                    # Reset the current prompt
                    st.session_state.current_prompt = None
                    
                    # Check if a topic transition occurred
                    if TutorState.get_in_transition():
                        # Force a rerun to refresh the UI with the new topic
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
            if "modules" in modules_data and isinstance(modules_data["modules"], list):
                module_data = None
                target_title = MODULE_TITLES.get(str(module_id))
                
                if target_title:
                    for m in modules_data["modules"]:
                        if m.get("title") == target_title:
                            module_data = m
                            break
                
                if module_data:
                    tutorial_questions = module_data.get("tutorial_questions", {})
                    if isinstance(tutorial_questions, list):
                        # Convert list format to dictionary format using simple index string keys
                        tutorial_questions = {str(i + 1): q for i, q in enumerate(tutorial_questions)}
                    
                    if tutorial_questions:
                        # Get user progress data from cache
                        user_progress = get_cached_user_progress()
                        # --- Corrected Access to User Question Progress ---
                        # Access the nested structure: user -> modules -> module_id -> questions
                        module_progress = user_progress.get("modules", {}).get(str(module_id), {})
                        user_questions_progress = module_progress.get("questions", {}) # This is the dict keyed by question_id
                        # --- End Corrected Access ---

                        for question_id, question_info in tutorial_questions.items():
                            if not isinstance(question_info, dict):
                                continue
                            
                            question_title = question_info.get("label", f"Question {question_id}")
                            
                            # Get question progress data using the correct dictionary
                            q_data = user_questions_progress.get(question_id, {})

                            # --- Corrected Status Logic ---
                            # Determine status based on both status field and competency_level
                            status = q_data.get("status", "not_started")
                            competency_level = q_data.get("competency_level", 0)

                            # If competency_level is 2 (full understanding), treat as completed
                            if competency_level >= 2:
                                status = "completed"

                            status_emoji = get_status_emoji(status)
                            # --- End Corrected Status Logic ---

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