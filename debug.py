import streamlit as st
import json
import os

# Check if user is logged in
if "logged_in" not in st.session_state or not st.session_state.logged_in:
    st.warning("Please login from the Home page to access this page.")
    st.stop()

st.set_page_config(page_title="FunCE - Debug", layout="wide")

def load_file(file_path):
    """Load and display contents of a file"""
    try:
        if file_path.endswith('.json'):
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
    except UnicodeDecodeError:
        try:
            with open(file_path, 'r', encoding='latin-1') as f:
                if file_path.endswith('.json'):
                    return json.load(f)
                else:
                    return f.read()
        except Exception as e:
            return f"Error reading file with latin-1 encoding: {str(e)}"
    except Exception as e:
        return f"Error: {str(e)}"

st.title("FunCE Debug Page")

# Check for specific files
data_files = {
    "modules.json": os.path.exists("data/modules.json"),
    "user_progress.json": os.path.exists("data/user_progress.json"),
    "tutor.md": os.path.exists("prompts/tutor.md"),
    "assessor.md": os.path.exists("prompts/assessor.md")
}

st.subheader("File Status")
for file_name, exists in data_files.items():
    if exists:
        st.success(f"✅ {file_name} exists")
    else:
        st.error(f"❌ {file_name} not found")

# File content viewers
file_options = [f for f, exists in data_files.items() if exists]
selected_file = st.selectbox("Select a file to view", file_options)

if selected_file:
    file_path = f"data/{selected_file}" if selected_file.endswith(".json") else f"prompts/{selected_file}"
    
    st.subheader(f"Contents of {selected_file}")
    file_content = load_file(file_path)
    
    if isinstance(file_content, dict):
        # Pretty-print JSON with proper indentation
        st.json(file_content)
        
        # For modules.json, show additional analysis
        if selected_file == "modules.json":
            st.subheader("Modules Analysis")
            if "modules" in file_content and isinstance(file_content["modules"], list):
                st.write(f"Format: List-based, contains {len(file_content['modules'])} modules")
                for i, module in enumerate(file_content["modules"], 1):
                    st.write(f"Module {i}: {module.get('title', 'Untitled')}")
                    st.write(f"- Topics: {len(module.get('topics', []))}")
                    st.write(f"- Tutorial Questions: {len(module.get('tutorial_questions', {}))}")
            else:
                st.write(f"Format: Dictionary-based, contains {len(file_content)} modules")
                for module_id, module in file_content.items():
                    st.write(f"Module {module_id}: {module.get('name', 'Untitled')}")
                    st.write(f"- Topics: {len(module.get('topics', []))}")
    else:
        # Display text content
        st.text(file_content)

# Fix Options
st.subheader("Fix Options")

col1, col2 = st.columns(2)

with col1:
    if st.button("Rebuild user_progress.json (Empty)"):
        # Create a minimal user_progress.json file with the new structure
        try:
            # Load modules data to get structure
            modules_data = {}
            if os.path.exists("data/modules.json"):
                with open("data/modules.json", 'r', encoding='utf-8') as f:
                    modules_data = json.load(f)
            
            user_progress = {"user123": {"modules": {}}}
            
            # If modules exist in the new format
            if "modules" in modules_data and isinstance(modules_data["modules"], list):
                for i, module in enumerate(modules_data["modules"], 1):
                    module_id = str(i)
                    topics = module.get("topics", [])
                    tutorial_questions = module.get("tutorial_questions", {})
                    
                    # Create empty progress for this module using the new format
                    user_progress["user123"]["modules"][module_id] = {
                        # Array of statuses matching the order of topics in modules.json
                        "topics_status": ["🔴" for _ in topics],
                        
                        # Dictionary of question progress without duplicating question details
                        "tutorial_questions_progress": {}
                    }
                    
                    # Add tutorial questions progress
                    for q_id in tutorial_questions.keys():
                        user_progress["user123"]["modules"][module_id]["tutorial_questions_progress"][q_id] = {
                            "status": "🔴",
                            "attempts": 0,
                            "last_attempt": None
                        }
            else:
                # Old format or empty
                for i in range(1, 7):  # Create 6 modules
                    module_id = str(i)
                    user_progress["user123"]["modules"][module_id] = {
                        "topics_status": ["🔴", "🔴", "🔴", "🔴"],
                        "tutorial_questions_progress": {
                            f"{module_id}.1": {
                                "status": "🔴",
                                "attempts": 0,
                                "last_attempt": None
                            }
                        }
                    }
            
            # Add some metadata
            user_progress["user123"]["last_login"] = "2025-03-10"
            user_progress["user123"]["total_study_time"] = 0
            
            # Write the file
            with open("data/user_progress.json", 'w', encoding='utf-8') as f:
                json.dump(user_progress, f, indent=2, ensure_ascii=False)
            
            st.success("Successfully rebuilt user_progress.json with empty progress")
        except Exception as e:
            st.error(f"Error rebuilding user_progress.json: {str(e)}")

with col2:
    if st.button("Rebuild user_progress.json (Sample Progress)"):
        # Create a user_progress.json file with sample progress
        try:
            # Load modules data to get structure
            modules_data = {}
            if os.path.exists("data/modules.json"):
                with open("data/modules.json", 'r', encoding='utf-8') as f:
                    modules_data = json.load(f)
            
            user_progress = {"user123": {"modules": {}}}
            
            # If modules exist in the new format
            if "modules" in modules_data and isinstance(modules_data["modules"], list):
                for i, module in enumerate(modules_data["modules"], 1):
                    module_id = str(i)
                    topics = module.get("topics", [])
                    tutorial_questions = module.get("tutorial_questions", {})
                    
                    # Create sample progress for this module
                    if i == 1:  # First module has mixed progress
                        # Module 1: First few topics completed/in progress
                        topics_status = []
                        for j in range(len(topics)):
                            if j < 2:
                                topics_status.append("✅")  # First 2 completed
                            elif j < 4:
                                topics_status.append("🟠")  # Next 2 in progress
                            else:
                                topics_status.append("🔴")  # Rest not started
                        
                        # Add module with sample progress
                        user_progress["user123"]["modules"][module_id] = {
                            "topics_status": topics_status,
                            "tutorial_questions_progress": {}
                        }
                        
                        # Add tutorial questions with sample progress
                        question_keys = list(tutorial_questions.keys())
                        for idx, q_id in enumerate(question_keys):
                            if idx < 2:  # First 2 questions completed
                                status = "✅"
                                attempts = 2
                                last_attempt = "2025-03-01"
                            elif idx < 3:  # Next question in progress
                                status = "🟠"
                                attempts = 1
                                last_attempt = "2025-03-05"
                            else:  # Rest not started
                                status = "🔴"
                                attempts = 0
                                last_attempt = None
                                
                            user_progress["user123"]["modules"][module_id]["tutorial_questions_progress"][q_id] = {
                                "status": status,
                                "attempts": attempts,
                                "last_attempt": last_attempt
                            }
                    else:
                        # Other modules: All topics not started
                        user_progress["user123"]["modules"][module_id] = {
                            "topics_status": ["🔴" for _ in topics],
                            "tutorial_questions_progress": {}
                        }
                        
                        # All questions not started
                        for q_id in tutorial_questions.keys():
                            user_progress["user123"]["modules"][module_id]["tutorial_questions_progress"][q_id] = {
                                "status": "🔴",
                                "attempts": 0,
                                "last_attempt": None
                            }
            
            # Add some metadata
            user_progress["user123"]["last_login"] = "2025-03-12"
            user_progress["user123"]["total_study_time"] = 12.5
            
            # Write the file
            with open("data/user_progress.json", 'w', encoding='utf-8') as f:
                json.dump(user_progress, f, indent=2, ensure_ascii=False)
            
            st.success("Successfully rebuilt user_progress.json with sample progress data")
        except Exception as e:
            st.error(f"Error rebuilding user_progress.json: {str(e)}")

# Add validation tool for user_progress.json
st.subheader("Validate User Progress")

if st.button("Check Progress Data Against Modules"):
    try:
        # Load both files
        with open("data/modules.json", 'r', encoding='utf-8') as f:
            modules_data = json.load(f)
        
        with open("data/user_progress.json", 'r', encoding='utf-8') as f:
            user_progress = json.load(f)
        
        # Check if we have the expected structure
        if "modules" in modules_data and isinstance(modules_data["modules"], list):
            module_list = modules_data["modules"]
            
            # Check for each user
            for user_id, user_data in user_progress.items():
                st.write(f"Checking user: {user_id}")
                
                user_modules = user_data.get("modules", {})
                issues = []
                
                # Check each module
                for i, module_info in enumerate(module_list, 1):
                    module_id = str(i)
                    module_title = module_info.get("title", f"Module {module_id}")
                    
                    # Check if module exists in user data
                    if module_id not in user_modules:
                        issues.append(f"Module {module_id} ({module_title}) missing from user progress")
                        continue
                    
                    # Get module data
                    user_module = user_modules[module_id]
                    topics = module_info.get("topics", [])
                    tutorial_questions = module_info.get("tutorial_questions", {})
                    
                    # Check topics_status length
                    topics_status = user_module.get("topics_status", [])
                    if len(topics_status) < len(topics):
                        issues.append(f"Module {module_id}: topics_status array too short ({len(topics_status)} vs {len(topics)} topics)")
                    
                    # Check tutorial questions
                    user_questions = user_module.get("tutorial_questions_progress", {})
                    for q_id in tutorial_questions.keys():
                        if q_id not in user_questions:
                            issues.append(f"Module {module_id}: question {q_id} missing from user progress")
                
                # Report results
                if issues:
                    st.error(f"Found {len(issues)} issues:")
                    for issue in issues:
                        st.write(f"- {issue}")
                else:
                    st.success("User progress data is valid and matches the modules structure")
        else:
            st.error("modules.json does not have the expected format with 'modules' array")
    except Exception as e:
        st.error(f"Error validating progress data: {str(e)}")

# Display session state for debugging
if st.checkbox("Show Session State"):
    st.subheader("Session State")
    st.write(st.session_state)