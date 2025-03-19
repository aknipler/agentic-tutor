import streamlit as st
from mongodb.connector import get_modules_data, get_user_progress, update_user_progress
from datetime import datetime

BASE_URL = "http://localhost:8501/"

# Check if user is logged in
if "logged_in" not in st.session_state or not st.session_state.logged_in:
    st.warning("Please login from the Home page to access your progress.")
    st.stop()

def get_status_emoji(status):
    """Convert status to emoji"""
    status_map = {
        "completed": "✅",
        "in_progress": "🟠",
        "not_started": "🔴"
    }
    return status_map.get(status, "🔴")

def get_status_from_progress(progress):
    """Convert numeric progress (0, 1, 2) to status string"""
    progress_map = {
        0: "not_started",
        1: "in_progress",
        2: "completed"
    }
    return progress_map.get(progress, "not_started")

# Load module data from MongoDB
@st.cache_data(ttl=10)
def load_modules_data():
    """Load module information from MongoDB"""
    try:
        data = get_modules_data()
        if st.session_state.get('debug_mode', False):
            st.write("Debug: Modules data loaded:", data)
        return data
    except Exception as e:
        st.error(f"Error loading modules data from MongoDB: {str(e)}")
        return {"modules": []}

# Load user progress data from MongoDB
@st.cache_data(ttl=5)
def load_user_progress():
    """Load user progress from MongoDB"""
    user_id = st.session_state.user_id
    try:
        data = get_user_progress(user_id)
        if st.session_state.get('debug_mode', False):
            st.write("Debug: User progress loaded:", data)
        return data
    except Exception as e:
        st.error(f"Error loading user progress from MongoDB: {str(e)}")
        return {"user_id": user_id, "modules": {}}

def overview():
    st.title("Your Learning Progress")
    
    # Show user ID
    st.sidebar.info(f"Logged in as: {st.session_state.user_id}")
    
    # Debug toggle in sidebar
    with st.sidebar:
        st.session_state['debug_mode'] = st.checkbox("Debug Mode", value=False)  # Set to False by default
    
    # Add a help section at the top
    with st.expander("ℹ️ How to Use FunCE Learning Assistant"):
        st.markdown("""
        ### How to Use This Learning Assistant
        
        **For General Learning:**
        - Click on "Go to Module X Tutor" to interact with the AI tutor for that module
        - Use the tutor to explore concepts and ask questions about the module topics
        
        **For Topic Assessment:**
        - Click on any specific topic to test your knowledge with the assessor
        - The assessor will evaluate your understanding and provide feedback
        
        **Tutorial Questions:**
        - Each module includes tutorial questions to test your understanding
        - Complete these to solidify your knowledge
        
        **Progress Tracking:**
        - ✅ = Completed
        - 🟠 = In Progress
        - 🔴 = Not Started
        """)
    
    # Get the modules data from MongoDB
    modules_data = load_modules_data()
    
    # Get user progress data
    user_data = load_user_progress()
    user_topics = {topic["topic_id"]: topic for topic in user_data.get("topics", [])}
    user_questions = {q["question_id"]: q for q in user_data.get("tutorial_questions", [])}
    
    # Show modules data in debug mode
    if st.session_state.get('debug_mode', False):
        with st.expander("Debug: Modules Data"):
            st.write("Raw modules data:", modules_data)
            if "modules" in modules_data:
                st.write(f"Found {len(modules_data['modules'])} modules")
                for i, module in enumerate(modules_data['modules'], 1):
                    tutorial_questions = module.get("tutorial_questions", [])
                    tutorial_count = len(tutorial_questions) if isinstance(tutorial_questions, list) else len(tutorial_questions.keys())
                    st.write(f"Module {i}: {module.get('title')} - {len(module.get('topics', []))} topics, {tutorial_count} questions")
            else:
                st.error("No 'modules' key found in modules_data")
    
    # Show user progress in debug mode
    if st.session_state.get('debug_mode', False):
        with st.expander("Debug: User Progress"):
            st.write("Raw user data:", user_data)
            st.write("User topics:", user_topics)
            st.write("User questions:", user_questions)

    # Display last updated time if available
    if "last_updated" in user_data:
        last_updated = user_data["last_updated"]
        if isinstance(last_updated, dict) and "$date" in last_updated:
            last_updated = datetime.fromtimestamp(last_updated["$date"]["$numberLong"] / 1000)
        st.info(f"Last updated: {last_updated.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Display user info if available
    if "last_login" in user_data:
        st.info(f"Last login: {user_data['last_login']} | Total study time: {user_data.get('total_study_time', 0)} hours")
    
    # Check if modules_data is empty or doesn't have the expected structure
    if not modules_data or "modules" not in modules_data or not modules_data["modules"]:
        st.warning("No modules data available. Please make sure the modules are properly set up in MongoDB.")
        return
    
    # Process and display modules
    module_list = modules_data["modules"]
    
    for module_index, module_info in enumerate(module_list, 1):
        module_id = str(module_index)
        module_title = module_info.get("title", f"Module {module_id}")
        
        # Get topics from module_info
        topics = module_info.get("topics", [])
        
        # Get tutorial questions
        tutorial_questions = module_info.get("tutorial_questions", [])
        
        # Convert tutorial_questions to dictionary format if it's a list (new MongoDB format)
        tutorial_questions_dict = {}
        if isinstance(tutorial_questions, list):
            for question in tutorial_questions:
                question_id = question.get("question_id", f"q{len(tutorial_questions_dict) + 1}")
                tutorial_questions_dict[question_id] = {
                    "question": question.get("question", ""),
                    "expected_answer": question.get("expected_answer", "")
                }
        else:
            tutorial_questions_dict = tutorial_questions
            
        # Get user progress data for this module (or create default)
        user_module_data = user_topics.get(module_id, {})
        user_topics_status = user_module_data.get("topics_status", ["🔴"] * len(topics))
        user_tutorial_progress = user_questions.get(module_id, {})
        
        # Ensure user_topics_status is at least as long as topics list
        while len(user_topics_status) < len(topics):
            user_topics_status.append("🔴")
        
        # Calculate completion percentage
        total_items = len(topics) + len(tutorial_questions_dict)
        completed_topics = sum(1 for topic in topics if user_topics.get(f"{module_id}.{topics.index(topic) + 1}", {}).get("status") == "completed")
        completed_tutorials = sum(1 for q_id in tutorial_questions_dict.keys() if user_questions.get(q_id, {}).get("status") == "completed")
        completed_items = completed_topics + completed_tutorials
        
        module_progress = int((completed_items / total_items) * 2) if total_items > 0 else 0
        module_status = get_status_from_progress(module_progress)
        
        # Create an expander for each module
        with st.expander(f"Module {module_index}: {module_title} {get_status_emoji(module_status)}", expanded=module_index == 1):
            # Create columns for the progress display
            col1, col2 = st.columns([3, 1])
            
            # Display module link in the first column
            with col1:
                if st.button(f"Go to Module {module_index} Tutor"):
                    # Store the file ID in session state
                    st.session_state[f"module_{module_index}_file_id"] = module_info.get("file_id")
                    # Store the module number in session state
                    st.session_state["current_module"] = module_index
                    # Navigate to the tutor page using relative path
                    st.switch_page("pages/2_Tutor.py")
            
            # Display progress bar in the second column
            with col2:
                st.progress(module_progress / 2)
            
            # Display topics section
            st.markdown("#### Module Topics")
            if topics:
                for i, topic in enumerate(topics):
                    topic_id = f"{module_id}.{i + 1}"
                    topic_data = user_topics.get(topic_id, {})
                    progress = topic_data.get("progress", 0)
                    status = get_status_from_progress(progress)
                    status_emoji = get_status_emoji(status)
                    
                    status_color = {
                        '✅': 'green',
                        '🟠': 'orange',
                        '🔴': 'red'
                    }.get(status_emoji, 'gray')
                    
                    # Create columns for status and topic name
                    t_col1, t_col2 = st.columns([1, 5])
                    
                    with t_col1:
                        st.markdown(f"<span style='color:{status_color}'>{status_emoji}</span>", unsafe_allow_html=True)
                    
                    with t_col2:
                        # Handle both string and dictionary topic formats
                        topic_name = topic.get('name', topic) if isinstance(topic, dict) else topic
                        topic_description = topic.get('description', f"Assess your knowledge of {topic_name}") if isinstance(topic, dict) else f"Assess your knowledge of {topic}"
                        
                        # Display topic name with hover description
                        st.markdown(f"{topic_name}", help=topic_description)
            else:
                st.info("No topics found for this module.")
            
            # Display tutorial questions section
            st.markdown("#### Tutorial Questions")
            if tutorial_questions_dict:
                for question_id, question_info in tutorial_questions_dict.items():
                    if not isinstance(question_info, dict):
                        continue
                    
                    # Get question title
                    question_title = question_info.get("question", f"Question {question_id}")
                    
                    # Get progress data
                    q_data = user_questions.get(question_id, {})
                    progress = q_data.get("progress", 0)
                    status = get_status_from_progress(progress)
                    status_emoji = get_status_emoji(status)
                    attempts = q_data.get("attempts", 0)
                    
                    status_color = {
                        '✅': 'green',
                        '🟠': 'orange',
                        '🔴': 'red'
                    }.get(status_emoji, 'gray')
                    
                    # Create columns for status and link
                    q_col1, q_col2, q_col3 = st.columns([1, 5, 1])
                    
                    with q_col1:
                        st.markdown(f"<span style='color:{status_color}'>{status_emoji}</span>", unsafe_allow_html=True)
                    
                    with q_col2:
                        # Create link to assessor with query parameters for the question
                        assessor_url = f"{BASE_URL}Assessor?module={module_index}&question={question_id}"
                        st.page_link(
                            assessor_url, 
                            label=question_title,
                            help=f"Attempts: {attempts}"
                        )
                    
                    with q_col3:
                        if attempts > 0:
                            st.markdown(f"({attempts})")
            else:
                st.info("No tutorial questions found for this module.")

if __name__ == "__main__":
    overview()