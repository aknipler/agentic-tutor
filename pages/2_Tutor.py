import streamlit as st
import time
import os
import openai
import json
from mongodb.connector import get_user_progress as get_mongo_user_progress

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
        # Get user progress from MongoDB
        user_id = st.session_state.get("user_id", "user123")  # Default to user123 if not set
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
            status = "✅" if progress >= 100 else "🟠" if progress > 0 else "🔴"
            progress_summary.append(f"{status} {topic_name}: {progress}%")
        
        return "\n\n".join(progress_summary)
    except Exception as e:
        if st.session_state.get("debug_mode", False):
            st.error(f"Error getting user progress: {str(e)}")
        return None

def get_bot_response(user_input, module):
    """
    Get a response from the tutor bot using OpenAI for the specified module.
    """
    try:
        # Get OpenAI client
        client = setup_openai_client()
        
        # Get module content
        module_context, module_name = get_module_content(module)
        
        # Get system prompt
        system_prompt = load_tutor_prompt()
        
        # Combine system prompt and context
        instructions = f"{system_prompt}"
        
        # Get previous response ID from session state for this module
        chat_history_key = f"messages_module_{module}"
        previous_response_id = None
        
        # Debug information
        if st.session_state.get("debug_mode", False):
            st.write("Debug Info:")
            st.write(f"Chat History Key: {chat_history_key}")
            st.write(f"Session State Keys: {list(st.session_state.keys())}")
            if chat_history_key in st.session_state:
                st.write(f"Chat History Length: {len(st.session_state[chat_history_key])}")
                st.write(f"Chat History Content: {st.session_state[chat_history_key]}")
            else:
                st.write("Chat History Key not found in session state")
        
        # Get the last response ID from the chat history
        if chat_history_key in st.session_state:
            # Find the last assistant message with a response_id
            for message in reversed(st.session_state[chat_history_key]):
                if message.get("role") == "assistant" and message.get("response_id"):
                    previous_response_id = message.get("response_id")
                    if st.session_state.get("debug_mode", False):
                        st.write(f"Found Previous Response ID: {previous_response_id}")
                    break
        
        # Check if this is the first user message
        is_first_message = chat_history_key in st.session_state and len(st.session_state[chat_history_key]) <= 3  # Includes progress, greeting and first user message
        
        # Prepare input content
        input_content = []
        
        # If this is the first message and there's a file, include it first
        if is_first_message:
            # Check if there's a file associated with this module
            file_id = st.session_state.get(f"module_{module}_file_id")
            if file_id:
                # Clean the file ID
                cleaned_file_id = clean_file_id(file_id)
                if not cleaned_file_id:
                    st.error("Invalid file ID format")
                    return "I'm sorry, there was an issue with the file ID. Please try again."
                    
                # Add file content as a system message
                input_content.append({
                    "role": "system",
                    "content": [
                        {
                            "type": "input_file",
                            "file_id": cleaned_file_id,
                        }
                    ]
                })
            
            # Add all previous assistant messages (progress and welcome)
            for message in st.session_state[chat_history_key]:
                if message["role"] == "assistant" and "response_id" not in message:  # Only include initial messages
                    input_content.append({
                        "role": message["role"],
                        "content": message["content"]
                    })
                    if st.session_state.get("debug_mode", False):
                        st.write(f"Adding initial message: {message['content'][:50]}...")
        
        # Add the current user message without file
        input_content.append({
            "role": "user",
            "content": user_input
        })
        
        if st.session_state.get("debug_mode", False):
            st.write("Input Content:", input_content)
            st.write("Previous Response ID:", previous_response_id)
        
        # Call the OpenAI API with responses.create
        response = client.responses.create(
            model="gpt-4o",
            instructions=instructions,
            input=input_content,
            previous_response_id=previous_response_id
        )
        
        if st.session_state.get("debug_mode", False):
            st.write("Response:", response)
            st.write("Response ID:", response.id)
        
        # Store the response ID in session state
        if chat_history_key not in st.session_state:
            st.session_state[chat_history_key] = []
        
        # Add the response to chat history with its ID
        new_message = {
            "role": "assistant",
            "content": response.output_text,
            "response_id": response.id
        }
        st.session_state[chat_history_key].append(new_message)
        
        if st.session_state.get("debug_mode", False):
            st.write("Updated Chat History:", st.session_state[chat_history_key])
            st.write("Last Message Response ID:", st.session_state[chat_history_key][-1].get("response_id"))
        
        # Return the response text
        return response.output_text
        
    except Exception as e:
        st.error(f"Error generating response: {str(e)}")
        if st.session_state.get("debug_mode", False):
            st.exception(e)  # This will show the full traceback
        return "I'm sorry, I encountered an error. Please try again or contact support if the issue persists."

# Main app function
def main():
    st.title("FunCE Tutor Bot")
    
    with st.expander("ℹ️ About the AI Tutor", expanded=False):
        st.write("""
        **Welcome to AI-Chris, your Socratic Chemical Engineering Tutor**
        
        AI-Chris will help you learn chemical engineering concepts through guided questioning rather than giving direct answers.
        This approach helps develop critical thinking and deeper understanding of the subject.
        
        **How to Use:**
        1. Ask questions about the module content
        2. Attempt to answer AI-Chris's questions
        3. AI-Chris will guide you toward the correct understanding
        
        This tutor has access to the CHEN20012 course materials and can help with theoretical concepts.
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
            initial_messages.insert(1, {
                "role": "assistant",
                "content": f"Here's your current progress in this module:\n\n{progress_summary}\n\nLet's continue learning!"
            })
        
        st.session_state[chat_history_key] = initial_messages
        if st.session_state.get("debug_mode", False):
            st.write("Initialized new chat history for module:", module)
            st.write("Initial messages:", initial_messages)
    
    # Create a sidebar for navigation
    with st.sidebar:
        st.header("Navigation")
        st.page_link("pages/1_Your_Progress.py", label="Back to Progress")
        
        st.header("Current Module")
        st.write(f"Module: {module_name}")
        
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
    
    # Display key topics
    if "topics" in module_data and module_data["topics"]:
        with st.expander("Module Topics", expanded=True):
            for i, topic in enumerate(module_data["topics"], 1):
                st.markdown(f"**{i}.** {topic}")
                
    # Add a note about the module PDF
    pdf_path = f"knowledge/module{module_id}.pdf"
    if os.path.exists(pdf_path):
        st.info(f"📚 This module's content is based on the materials in '{pdf_path}'.")
    
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