import streamlit as st
import time
import os
import openai
import json
from mongodb.connector import get_user_progress as get_mongo_user_progress, update_competency, get_topic_competency

# Check if user is logged in
if "logged_in" not in st.session_state or not st.session_state.logged_in:
    st.warning("Please login from the Home page to access the tutor.")
    st.stop()

# Load the tutor prompt
@st.cache_data
def load_tutor_prompt():
    """Load the tutor prompt from the tutor.md file"""
    try:
        with open("prompts/tutor.md", "r", encoding="utf-8") as file:
            return file.read()
    except UnicodeDecodeError:
        # Try with a different encoding if UTF-8 fails
        try:
            with open("prompts/tutor.md", "r", encoding="latin-1") as file:
                return file.read()
        except Exception as e:
            st.error(f"Error loading tutor prompt with alternate encoding: {str(e)}")
            return "Error loading tutor prompt. Please check file encoding."
    except Exception as e:
        st.error(f"Error loading tutor prompt: {str(e)}")
        return "Error loading tutor prompt. Please check if the file exists."

# Load module data from JSON
@st.cache_data
def load_modules_data():
    """Load module information from the modules.json file"""
    try:
        with open("data/modules.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except UnicodeDecodeError:
        # Try with a different encoding if UTF-8 fails
        try:
            with open("data/modules.json", "r", encoding="latin-1") as f:
                return json.load(f)
        except Exception as e:
            st.error(f"Error loading modules data with alternate encoding: {str(e)}")
            return {}
    except Exception as e:
        st.error(f"Error loading modules data: {str(e)}")
        # Return default data if file not found or error
        return {}

# Get relevant content for a module
@st.cache_data
def get_module_content(module):
    """
    Retrieve relevant context for a specific module from the modules.json file.
    """
    # Load modules data from JSON
    modules_data = load_modules_data()
    
    # Get module info
    module_id = str(module)
    
    # Check for new format
    if "modules" in modules_data and isinstance(modules_data["modules"], list):
        # New format - modules is a list
        module_list = modules_data["modules"]
        
        try:
            # Convert module_id to index (1-based to 0-based)
            module_index = int(module_id) - 1
            if 0 <= module_index < len(module_list):
                module_info = module_list[module_index]
                module_title = module_info.get("title", f"Module {module_id}")
                topics = module_info.get("topics", [])
                
                # Format topics list
                topic_names = []
                for topic in topics:
                    if isinstance(topic, dict):
                        topic_names.append(topic.get('name', 'Unnamed Topic'))
                    else:
                        topic_names.append(str(topic))
                
                # Build context string
                context = f"""
                Module: {module_title}
                
                Key Topics:
                {', '.join(topic_names)}
                """
                
                return context, module_title
        except (ValueError, IndexError):
            pass  # Fall through to default if index is invalid
    else:
        # Old format - direct lookup by key
        if module_id in modules_data:
            module_content = modules_data[module_id]
            
            # Format topics list
            topics = module_content.get("topics", [])
            topic_names = []
            for topic in topics:
                if isinstance(topic, dict):
                    topic_names.append(topic.get('name', 'Unnamed Topic'))
                else:
                    topic_names.append(str(topic))
            
            # Build formatted context string
            context = f"""
            Module: {module_content['name']}
            Description: {module_content.get('description', '')}
            Content: {module_content.get('content', '')}
            
            Key Topics:
            {', '.join(topic_names)}
            """
            
            return context, module_content["name"]
    
    # Default fallback if module not found in either format
    default_title = f"Module {module}"
    default_context = f"""
    Module: {default_title}
    Description: Chemical Engineering Principles
    Content: This module covers various chemical engineering principles relevant to the CHEN20012 course.
    
    Key Topics:
    Topic 1, Topic 2, Topic 3
    """
    
    return default_context, default_title

def setup_openai_client():
    """Set up and return the OpenAI client"""
    # Use API key from Streamlit secrets
    if "openai_client" not in st.session_state:
        # The API key should come from Streamlit secrets
        client = openai.OpenAI()
        st.session_state["openai_client"] = client
    
    return st.session_state["openai_client"]

def clean_file_id(file_id):
    """
    Clean the file ID by removing any non-printable characters and extra whitespace.
    """
    if not file_id:
        return None
    # Remove non-printable characters and extra whitespace
    cleaned_id = ''.join(char for char in file_id if char.isprintable()).strip()
    return cleaned_id

def get_user_progress(module):
    """
    Get the user's progress for topics in the current module.
    """
    try:
        # Use the authenticated user ID instead of default 'user123'
        user_id = st.session_state.user_id
        progress_data = get_mongo_user_progress(user_id)
        
        if not progress_data:
            return None
            
        # Get module topics from modules data
        modules_data = load_modules_data()
        module_id = str(module)
        
        # Handle both old and new module data formats
        if "modules" in modules_data and isinstance(modules_data["modules"], list):
            # New format - modules is a list
            try:
                module_index = int(module_id) - 1
                if 0 <= module_index < len(modules_data["modules"]):
                    module_data = modules_data["modules"][module_index]
                    topics = module_data.get("topics", [])
                else:
                    return None
            except (ValueError, IndexError):
                return None
        else:
            # Old format - direct lookup
            module_data = modules_data.get(module_id, {})
            topics = module_data.get("topics", [])
        
        # Create a progress summary
        progress_summary = []
        
        # Get topics from progress data
        progress_topics = progress_data.get("topics", [])
        
        # Create a mapping of topic names to progress
        progress_map = {}
        for topic in progress_topics:
            topic_name = topic.get("name", "")
            # Handle both MongoDB format and direct number format
            progress = topic.get("progress", {})
            if isinstance(progress, dict):
                progress = int(progress.get("$numberInt", "0"))
            else:
                progress = int(progress)
            progress_map[topic_name] = progress
        
        # Build progress summary using both topic lists
        for topic in topics:
            if isinstance(topic, dict):
                topic_name = topic.get('name', 'Unnamed Topic')
            else:
                topic_name = str(topic)
            
            progress = progress_map.get(topic_name, 0)
            status = "✅" if progress == 2 else "🟠" if progress == 1 else "🔴"
            progress_summary.append(f"{status} {topic_name}")
        
        return "\n\n".join(progress_summary)
    except Exception as e:
        if st.session_state.get("debug_mode", False):
            st.error(f"Error getting user progress: {str(e)}")
        return None

def get_bot_response(user_input, module):
    """Get a response from the tutor bot and track competencies using function calling"""
    try:
        client = setup_openai_client()
        module_context, module_name = get_module_content(module)
        
        # Get system prompt
        system_prompt = load_tutor_prompt()
        
        # Define the competency management tools
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
            },
            {
                "type": "function",
                "name": "get_topic_competency",
                "description": "Get a student's current competency level for a specific topic",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topic_name": {
                            "type": "string",
                            "description": "The name of the topic to check"
                        }
                    },
                    "required": ["topic_name"]
                }
            }
        ]
        
        # Get previous response ID from session state for this module
        chat_history_key = f"messages_module_{module}"
        previous_response_id = None
        
        # Get the last response ID from the chat history
        if chat_history_key in st.session_state:
            for message in reversed(st.session_state[chat_history_key]):
                if message.get("role") == "assistant" and message.get("response_id"):
                    previous_response_id = message.get("response_id")
                    break
        
        # Prepare input content
        input_content = []
        
        # Check if this is the first user message
        is_first_message = chat_history_key in st.session_state and len(st.session_state[chat_history_key]) <= 3
        
        # If this is the first message and there's a file, include it first
        if is_first_message:
            file_id = st.session_state.get(f"module_{module}_file_id")
            if file_id:
                cleaned_file_id = clean_file_id(file_id)
                if cleaned_file_id:
                    input_content.append({
                        "role": "system",
                        "content": [{"type": "input_file", "file_id": cleaned_file_id}]
                    })
        
        # Add the current user message
        input_content.append({
            "role": "user",
            "content": user_input
        })
        
        # Call the OpenAI API with function definitions
        response = client.responses.create(
            model="gpt-4o",
            instructions=system_prompt,
            input=input_content,
            tools=tools,
            previous_response_id=previous_response_id
        )
        
        # Handle function calls if any
        if hasattr(response, 'output') and response.output and any(item.type == "function_call" for item in response.output):
            # Process function calls
            new_messages = list(input_content)  # Create a copy of input_content
            
            # For each function call in the output
            for tool_call in [item for item in response.output if item.type == "function_call"]:
                # Add the function call to messages
                new_messages.append(tool_call)
                
                # Process the function call
                func_name = tool_call.name
                func_args = json.loads(tool_call.arguments)
                
                # Handle different function types
                result = None
                if func_name == "update_topic_competency":
                    topic_name = func_args.get("topic_name")
                    level = func_args.get("level")
                    reason = func_args.get("reason")
                    
                    if topic_name is not None and level is not None:
                        # Update the competency in MongoDB
                        update_competency(
                            st.session_state.user_id,
                            topic_name,
                            level
                        )
                        
                        result = f"Successfully updated competency for {topic_name} to level {level}"
                        
                        if st.session_state.get("debug_mode", False):
                            st.write(f"Debug: Updated competency for topic {topic_name} to level {level}")
                            st.write(f"Debug: Reason: {reason}")
                
                elif func_name == "get_topic_competency":
                    topic_name = func_args.get("topic_name")
                    
                    if topic_name is not None:
                        # Get the competency from MongoDB
                        competency_data = get_topic_competency(
                            st.session_state.user_id,
                            topic_name
                        )
                        
                        if competency_data:
                            progress = competency_data.get("progress", 0)
                            # Progress is now directly the level (0, 1, 2)
                            result = json.dumps({
                                "topic_name": topic_name,
                                "progress": progress,
                                "level": progress
                            })
                        else:
                            result = f"No competency data found for {topic_name}"
                        
                        if st.session_state.get("debug_mode", False):
                            st.write(f"Debug: Retrieved competency for topic {topic_name}:", competency_data)
                
                # Add the function result to messages
                if result is not None:
                    new_messages.append({
                        "type": "function_call_output",
                        "call_id": tool_call.call_id,
                        "output": result
                    })
            
            try:
                # Generate a new response with the function results
                new_response = client.responses.create(
                    model="gpt-4o",
                    instructions=system_prompt,
                    input=new_messages
                )
                
                # Update the response
                response_text = new_response.output_text
                response = new_response
                
            except Exception as tool_error:
                # Log the error but continue with the original response
                st.error(f"Error handling function calls: {str(tool_error)}")
                if st.session_state.get("debug_mode", False):
                    st.exception(tool_error)
                    st.write("Debug - Messages:", new_messages)
        else:
            response_text = response.output_text
        
        # Store the response in chat history
        if chat_history_key not in st.session_state:
            st.session_state[chat_history_key] = []
        
        new_message = {
            "role": "assistant",
            "content": response_text,
            "response_id": response.id
        }
        st.session_state[chat_history_key].append(new_message)
        
        return response_text
        
    except Exception as e:
        st.error(f"Error generating response: {str(e)}")
        if st.session_state.get("debug_mode", False):
            st.exception(e)
        return "I'm sorry, I encountered an error. Please try again."

# Main app function
def main():
    st.title("FunCE Tutor Bot")
    
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
        1. Ask questions about the module content
        2. Attempt to answer AI-Chris's questions
        3. AI-Chris will guide you toward understanding and track your progress
        """)
    
    # Get module from session state
    module = st.session_state.get("current_module", "1")
    
    # Store the current module in session state
    if "module" not in st.session_state:
        st.session_state.module = module
    
    # Get module content
    module_context, module_name = get_module_content(st.session_state.module)
    
    # Get user's progress
    progress_summary = get_user_progress(module)
    
    # Initialize chat history for this module if not exists
    chat_history_key = f"messages_module_{module}"
    if chat_history_key not in st.session_state:
        # Create initial messages including progress
        initial_messages = [
            {
                "role": "assistant",
                "content": f"Hi, I'm AI-Chris, your tutor for {module_name}. What would you like to learn about?"
            }
        ]
        
        # Add progress message if available
        if progress_summary:
            progress_message = f"""
**Your Current Progress:**
            
**Competency Levels:**
🔴 Not started
🟠 In Progress
✅ Completed
            
**Topics:**
{progress_summary}
            
Let's continue building your understanding!
            """
            initial_messages.insert(0, {
                "role": "assistant",
                "content": progress_message
            })
        
        st.session_state[chat_history_key] = initial_messages
    
    # Create a sidebar for navigation
    with st.sidebar:
        st.header("Navigation")
        st.page_link("pages/1_Your_Progress.py", label="Back to Progress")
        
        st.header("Current Module")
        st.write(f"Module: {module_name}")
        
        # Display current progress in sidebar
        if progress_summary:
            st.header("Your Progress")
            st.markdown("""
            **Competency Levels:**
            - 🔴 Not started
            - 🟠 In Progress
            - ✅ Completed
            """)
            st.markdown(progress_summary)
        
        # Add debug mode toggle
        st.markdown("---")
        st.header("Debug Settings")
        debug_mode = st.toggle("Enable Debug Mode", key="debug_mode")
        if debug_mode:
            st.info("Debug mode is enabled. You'll see detailed information about the chat history and API calls.")
        
        # Add some tips in the sidebar
        st.markdown("---")
        st.header("Tips for Learning")
        st.info("""
        **Socratic Method Tips:**
        - Try to explain concepts in your own words
        - When stuck, ask specific questions
        - Connect new concepts to what you already know
        - Don't be afraid to make mistakes - they're part of learning!
        """)
    
    # Get full module data
    modules_data = load_modules_data()
    module_id = str(st.session_state.module)
    module_data = modules_data.get(module_id, {})
    
    # Display module information
    st.header(f"Module {module_id}: {module_name}")
    st.subheader(module_data.get("description", ""))
    st.write(module_data.get("content", ""))
    
    # Display key topics with progress
    if "topics" in module_data and module_data["topics"]:
        with st.expander("Module Topics", expanded=True):
            for i, topic in enumerate(module_data["topics"], 1):
                topic_name = topic.get("name", str(topic))
                # Get progress for this topic from progress_summary
                progress_line = next(
                    (line for line in progress_summary.split("\n") if topic_name in line),
                    f"🔴 {topic_name}"
                ) if progress_summary else f"🔴 {topic_name}"
                st.markdown(f"{progress_line}")
    
    # Add a divider before the chat
    st.markdown("---")
    st.subheader("Chat with AI-Chris")
    
    # Display chat history
    for message in st.session_state[chat_history_key]:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
    
    # Chat input
    if prompt := st.chat_input("Ask the tutor a question about this topic..."):
        # Add user message to chat history
        st.session_state[chat_history_key].append({"role": "user", "content": prompt})
        
        # Display user message
        with st.chat_message("user"):
            st.markdown(prompt)
        
        # Get and display assistant response
        with st.chat_message("assistant"):
            with st.spinner("AI-Chris is thinking..."):
                response = get_bot_response(prompt, st.session_state.module)
                st.markdown(response)

if __name__ == "__main__":
    main()