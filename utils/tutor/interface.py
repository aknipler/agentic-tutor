"""Main tutor interface implementation"""
import streamlit as st
import openai
import json
from typing import Optional, Dict, Any, Union, List
from datetime import datetime

from .config.settings import TutorConfig, MODULE_TITLES
from .models.chat import ChatMessage
from .handlers.competency import (
    handle_competency_update,
    handle_competency_check,
    get_module_progress_summary,
    get_next_non_competent_topic
)
from .ui.components import render_sidebar, render_chat_history, render_progress_summary
from mongodb.connectors import get_modules_data, get_user_progress

# Base URL for the application
BASE_URL = "http://localhost:8502/"

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
    func_name = tool_call.name
    func_args = json.loads(tool_call.arguments)
    
    if func_name == "update_topic_competency":
        return handle_competency_update(func_args, user_id)
    elif func_name == "get_topic_competency":
        return handle_competency_check(func_args, user_id)
    return None

def get_bot_response(user_input: str, module: Union[str, int], file_id: Optional[str] = None) -> str:
    """Get a response from the tutor bot and track competencies using function calling"""
    try:
        # Check if current topic is completed before generating response
        current_topic = st.session_state.get("current_topic")
        if current_topic:
            # Use handle_competency_check instead of direct get_topic_competency call
            competency_result = handle_competency_check(
                {"topic_name": current_topic["name"]}, 
                st.session_state.user_id
            )
            try:
                competency_data = json.loads(competency_result)
                if competency_data.get("progress", 0) >= 2:
                    # Topic is completed, get next topic and reset chat
                    next_topic = get_next_non_competent_topic(module)
                    if next_topic:
                        st.session_state["current_topic"] = next_topic
                        # Clear chat history for new topic
                        chat_history_key = f"{TutorConfig.CHAT_HISTORY_PREFIX}{module}"
                        if chat_history_key in st.session_state:
                            st.session_state[chat_history_key] = []
                        # Generate initial message for new topic
                        return f"Great! You've completed {current_topic['name']} ✅. Let's move on to: {next_topic['name']}\n\n{next_topic['description']}"
                    else:
                        return "Congratulations! You've completed all topics in this module!"
            except json.JSONDecodeError:
                # If the result isn't JSON, assume topic is not completed
                pass

        client = setup_openai_client()
        system_prompt = load_tutor_prompt()
        
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

        # Add file search tool if vector store ID exists in session state
        vector_store_key = f"vector_store_id_{module}"
        if vector_store_key in st.session_state:
            vector_store_id = st.session_state[vector_store_key]
            if vector_store_id:
                tools.append({
                    "type": "file_search",
                    "vector_store_ids": [vector_store_id]
                })
        
        chat_history_key = f"{TutorConfig.CHAT_HISTORY_PREFIX}{module}"
        previous_response_id = None
        
        if chat_history_key in st.session_state:
            for message in reversed(st.session_state[chat_history_key]):
                if message.get("role") == "assistant" and message.get("response_id"):
                    previous_response_id = message.get("response_id")
                    break
        
        input_content = []
        
        is_first_message = chat_history_key in st.session_state and len(st.session_state[chat_history_key]) <= 3
        
        if is_first_message and file_id:
            cleaned_file_id = clean_file_id(file_id)
            if cleaned_file_id:
                input_content.append({
                    "role": "system",
                    "content": [{"type": "input_file", "file_id": cleaned_file_id}]
                })
        
        input_content.append({
            "role": "user",
            "content": user_input
        })
        
        response = client.responses.create(
            model=TutorConfig.MODEL_NAME,
            instructions=system_prompt,
            input=input_content,
            tools=tools,
            previous_response_id=previous_response_id
        )
        
        if hasattr(response, 'output') and response.output and any(item.type == "function_call" for item in response.output):
            new_messages = list(input_content)
            
            for tool_call in [item for item in response.output if item.type == "function_call"]:
                new_messages.append(tool_call)
                
                result = handle_function_call(tool_call, st.session_state.user_id)
                
                if result is not None:
                    new_messages.append({
                        "type": "function_call_output",
                        "call_id": tool_call.call_id,
                        "output": result
                    })
                    
                    # Check if this was a competency update and if it completed the topic
                    if tool_call.name == "update_topic_competency":
                        args = json.loads(tool_call.arguments)
                        if args.get("level") == 2:  # Topic completed
                            next_topic = get_next_non_competent_topic(module)
                            if next_topic:
                                st.session_state["current_topic"] = next_topic
                                # Clear chat history for new topic
                                if chat_history_key in st.session_state:
                                    st.session_state[chat_history_key] = []
                                # Generate initial message for new topic
                                return f"Great! You've completed the previous topic. Let's move on to: {next_topic['name']}\n\n{next_topic['description']}"
            
            try:
                new_response = client.responses.create(
                    model=TutorConfig.MODEL_NAME,
                    instructions=system_prompt,
                    input=new_messages
                )
                
                response_text = new_response.output_text
                response = new_response
                
            except Exception as tool_error:
                st.error(f"Error handling function calls: {str(tool_error)}")
                if st.session_state.get("debug_mode", False):
                    st.exception(tool_error)
                    st.write("Debug - Messages:", new_messages)
        else:
            response_text = response.output_text
        
        if chat_history_key not in st.session_state:
            st.session_state[chat_history_key] = []
        
        new_message = ChatMessage(
            role="assistant",
            content=response_text,
            response_id=response.id
        )
        st.session_state[chat_history_key].append(new_message.to_dict())
        
        # Limit chat history size
        if len(st.session_state[chat_history_key]) > TutorConfig.MAX_CHAT_HISTORY:
            st.session_state[chat_history_key] = st.session_state[chat_history_key][-TutorConfig.MAX_CHAT_HISTORY:]
        
        return response_text
        
    except Exception as e:
        st.error(f"Error generating response: {str(e)}")
        if st.session_state.get("debug_mode", False):
            st.exception(e)
        return "I'm sorry, I encountered an error. Please try again."

def render_tutor_interface(module_id: Union[str, int], module_title: str, module_description: str, topics: List[Any], file_id: Optional[str] = None) -> None:
    """Render the tutor interface for a specific module"""
    try:
        st.title(f"Module {module_id}: {module_title}")
        print(f"[Tutor Interface] Rendering interface for module {module_id}")
        
        # Initialize vector store ID in session state if not exists
        vector_store_key = f"vector_store_id_{module_id}"
        if vector_store_key not in st.session_state:
            modules_data = get_modules_data()
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
        
        # Get user's progress
        progress_summary = get_module_progress_summary(module_id)
        print(f"[Tutor Interface] Progress summary for module {module_id}: {progress_summary}")
        
        # Initialize chat history for this module if not exists
        chat_history_key = f"{TutorConfig.CHAT_HISTORY_PREFIX}{module_id}"
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
                
                # Generate initial Socratic question
                try:
                    client = setup_openai_client()
                    current_topic = st.session_state["current_topic"]
                    topic_description = current_topic.get('description', '')  # Get description if available, empty string if not
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

                    # Add the initial question to chat history without displaying it directly
                    st.session_state[chat_history_key].append(
                        ChatMessage(
                            role="assistant",
                            content=response.output_text,
                            response_id=response.id
                        ).to_dict()
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
                return
        
        # Display module information
        st.markdown(module_description)
        
        # Render progress summary
        render_progress_summary(progress_summary)
        
        # Add a divider before the chat
        st.markdown("---")
        st.subheader("Chat with AI-Chris")
        
        # Display chat history immediately
        if chat_history_key in st.session_state:
            print(f"[Tutor Interface] Displaying chat history for module {module_id}. Chat history length: {len(st.session_state[chat_history_key])}")
            render_chat_history(st.session_state[chat_history_key])
        else:
            print(f"[Tutor Interface] No chat history found for module {module_id}")
        
        # Chat input
        if prompt := st.chat_input("Ask the tutor a question about this topic..."):
            try:
                # Add user message to chat history
                st.session_state[chat_history_key].append(
                    ChatMessage(role="user", content=prompt).to_dict()
                )
                
                # Display user message
                with st.chat_message("user"):
                    st.markdown(prompt)
                
                # Get and display assistant response
                with st.chat_message("assistant"):
                    with st.spinner("AI-Chris is thinking..."):
                        response = get_bot_response(prompt, module_id, file_id)
                        # Only display response if it's not empty (topic not completed)
                        if response:
                            st.markdown(response)
                        
                        # Check if we should move to the next topic
                        current_topic = st.session_state.get("current_topic")
                        if current_topic:
                            # Use handle_competency_check instead of direct get_topic_competency call
                            competency_result = handle_competency_check(
                                {"topic_name": current_topic["name"]}, 
                                st.session_state.user_id
                            )
                            try:
                                competency_data = json.loads(competency_result)
                                if competency_data.get("progress", 0) >= 2:
                                    print(f"[Topic Completion] Topic: {current_topic['name']}, Final Progress: {competency_data.get('progress', 0)}")
                                    # Topic completed, get next topic
                                    next_topic = get_next_non_competent_topic(module_id)
                                    if next_topic:
                                        print(f"[Topic Transition] From: {current_topic['name']}, To: {next_topic['name']}")
                                        st.session_state["current_topic"] = next_topic
                                        # Show simple congratulatory message with tick
                                        st.success(f"✅ {current_topic['name']}")
                                        # Clear chat history for the new topic
                                        st.session_state[chat_history_key] = []
                                        
                                        # Generate initial question for the new topic
                                        try:
                                            client = setup_openai_client()
                                            topic_description = next_topic.get('description', '')  # Get description if available, empty string if not
                                            initial_prompt = f"""You are starting a new topic: {next_topic['name']}
                                            {f'Topic description: {topic_description}' if topic_description else ''}
                                            
                                            Your task is to:
                                            1. Begin with a direct, engaging question that immediately focuses on the core concept of the topic
                                            2. The question should be specific and practical, relating to real-world chemical engineering applications
                                            3. Avoid generic introductions or small talk - get straight to the topic
                                            4. Make the question challenging but approachable, encouraging critical thinking
                                            5. If possible, include a brief real-world scenario or example to make the question more concrete
                                            
                                            Generate your response as a single, focused Socratic question that will start the discussion. Do not include any introductory text or explanations - just the question itself."""
                                            
                                            response = client.responses.create(
                                                model=TutorConfig.MODEL_NAME,
                                                instructions=initial_prompt,
                                                input=[{"role": "system", "content": initial_prompt}],
                                                tools=[]
                                            )

                                            # Add the initial question to chat history without displaying it directly
                                            st.session_state[chat_history_key].append(
                                                ChatMessage(
                                                    role="assistant",
                                                    content=response.output_text,
                                                    response_id=response.id
                                                ).to_dict()
                                            )
                                            
                                            # Display the new chat history immediately
                                            render_chat_history(st.session_state[chat_history_key])
                                        except Exception as e:
                                            print(f"[Error] Failed to generate initial question for {next_topic['name']}: {str(e)}")
                                            if st.session_state.get("debug_mode", False):
                                                st.error(f"Error generating initial question: {str(e)}")
                                            raise  # Re-raise the exception to be handled by the caller
                                    else:
                                        print("[Module Completion] All topics completed in module")
                                        st.success("🎉 Congratulations! You've completed all topics in this module!")
                                        return
                            except json.JSONDecodeError:
                                # If the result isn't JSON, assume topic is not completed
                                pass
                        
            except Exception as e:
                print(f"[Error] Failed to process message: {str(e)}")
                st.error(f"Error processing your message: {str(e)}")
                if st.session_state.get("debug_mode", False):
                    st.exception(e)
                st.info("Please try rephrasing your question or try again later.")
        
        # Add tutorial questions section below chat input
        st.markdown("---")
        st.subheader("Tutorial Questions")
        
        # Get tutorial questions for the current module
        modules_data = get_modules_data()
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
                    # Convert list format to dictionary format
                    tutorial_questions = {f"q{i+1}": q for i, q in enumerate(tutorial_questions)}
                
                if tutorial_questions:
                    # Get user progress data
                    user_progress = get_user_progress(st.session_state.user_id)
                    user_questions = {q["question_id"]: q for q in user_progress.get("tutorial_questions", [])}
                    
                    for question_id, question_info in tutorial_questions.items():
                        if not isinstance(question_info, dict):
                            continue
                        
                        question_title = question_info.get("question", f"Question {question_id}")
                        
                        # Get question progress data
                        q_data = user_questions.get(question_id, {})
                        progress = q_data.get("progress", 0)
                        status = "completed" if progress >= 2 else "in_progress" if progress >= 1 else "not_started"
                        status_emoji = "✅" if status == "completed" else "🟠" if status == "in_progress" else "🔴"
                        attempts = q_data.get("attempts", 0)
                        
                        # Create columns for status, button, and question
                        col1, col2, col3 = st.columns([1, 1, 5])
                        
                        with col1:
                            st.markdown(f"<span style='color:{'green' if status == 'completed' else 'orange' if status == 'in_progress' else 'red'}'>{status_emoji}</span>", unsafe_allow_html=True)
                        
                        with col2:
                            # Create link to assessor with query parameters
                            assessor_url = f"{BASE_URL}Assessor?module={module_id}&question={question_id}"
                            st.page_link(
                                assessor_url,
                                label="Try Question",
                                help=f"Attempts: {attempts}"
                            )
                        
                        with col3:
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