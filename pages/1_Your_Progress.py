import streamlit as st
from mongodb.connectors import get_user_progress, update_user_progress, get_modules_data
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
        # Use session state to cache modules data
        if "cached_modules_data" not in st.session_state:
            st.session_state.cached_modules_data = get_modules_data()
        
        data = st.session_state.cached_modules_data
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
        - Use the sidebar menu to navigate to different modules
        - Each module has its own dedicated page with the AI tutor
        
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
    
    # Display last updated time if available
    if "updated_at" in user_data:
        last_updated = user_data["updated_at"]
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
    
    # Define the correct order of modules based on micro-competencies.md
    module_order = [
        "Introduction to Chemical Engineering",
        "Schematics",
        "Small Kit: Sensors and Valves",
        "Medium Kit: Tanks, Separators, Heat Exchangers and Boilers",
        "Large Kit: Reactors and Reaction Kinetics",
        "Large Kit: Thermodynamic Cycles"
    ]
    
    # Create a mapping of module titles to their data
    module_map = {module.get("title"): module for module in modules_data["modules"]}
    
    # Sort modules according to the defined order
    sorted_modules = []
    for title in module_order:
        if title in module_map:
            sorted_modules.append(module_map[title])
        else:
            st.warning(f"Module '{title}' not found in database")
    
    # Display modules in main content area
    for module_info in sorted_modules:
        # Get module index and title
        module_index = module_info.get("index", 0)
        module_title = module_info.get("title", f"Module {module_index}")
        
        # Get topics from module_info
        topics = module_info.get("topics", [])
        
        # Get tutorial questions
        tutorial_questions = module_info.get("tutorial_questions", [])
        
        # Convert tutorial_questions to dictionary format if it's a list (new MongoDB format)
        tutorial_questions_dict = {}
        if isinstance(tutorial_questions, list):
            for i, question in enumerate(tutorial_questions):
                # Use the index+1 as a string for the question_id
                tutorial_questions_dict[str(int(i)+1)] = {
                    "question": question.get("question", ""),
                    "expected_answer": question.get("expected_answer", ""),
                    'label': question.get('label', '')
                }
        else:
            tutorial_questions_dict = tutorial_questions
        # Get module progress data from the new structure
        module_progress_data = user_data.get("modules", {}).get(str(module_index), {})
        topics_progress = module_progress_data.get("topics", {})
        questions_progress = module_progress_data.get("questions", {})
        
        # Calculate completion percentage
        total_items = len(topics) + len(tutorial_questions_dict)
        completed_items = 0
        
        # Count completed topics
        for topic in topics:
            topic_name = topic.get('name', topic) if isinstance(topic, dict) else topic
            topic_data = topics_progress.get(topic_name, {})
            if topic_data.get("progress", 0) >= 2:
                completed_items += 1
        
        # Count completed tutorial questions
        for q_id in tutorial_questions_dict.keys():
            print(f"Getting {q_id} from questions_progress")
            q_data = questions_progress.get(q_id, {})
            # Check both status and competency_level
            if q_data.get("status") == "completed" or q_data.get("competency_level", 0) >= 2:
                completed_items += 1
        
        # Calculate module progress (0-2 scale)
        module_progress = int((completed_items / total_items) * 2) if total_items > 0 else 0
        module_status = get_status_from_progress(module_progress)
        
        # Create an expander for each module (all collapsed by default)
        with st.expander(f"Module {module_index}: {module_title} {get_status_emoji(module_status)}", expanded=False):
            # Display progress bar
            st.progress(module_progress / 2)
            
            # Display topics section
            st.markdown("#### Module Topics")
            if topics:
                for topic in topics:
                    # Get topic name based on format
                    topic_name = topic.get('name', topic) if isinstance(topic, dict) else topic
                    
                    # Get topic data from the new structure
                    topic_data = topics_progress.get(topic_name, {})
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
                    question_title = question_info.get("label", f"Question {question_id}")
                    
                    # Get question progress from the new structure
                    q_data = questions_progress.get(question_id, {})
                    
                    # Determine status based on both status field and competency_level
                    status = q_data.get("status", "not_started")
                    competency_level = q_data.get("competency_level", 0)
                    
                    # If competency_level is 2 (full understanding), treat as completed
                    if competency_level >= 2:
                        status = "completed"
                        
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
                        # Display question title without link
                        st.markdown(question_title)
                    
                    with q_col3:
                        if attempts > 0:
                            st.markdown(f"({attempts})")
            else:
                st.info("No tutorial questions found for this module.")

if __name__ == "__main__":
    overview()