import pymongo
import streamlit as st
from datetime import datetime

def get_mongo_client():
    """
    Establish a connection to MongoDB using credentials from Streamlit secrets.
    
    Returns:
        pymongo.MongoClient: A MongoDB client instance.
    """
    try:
        # Get connection details from secrets
        username = st.secrets["MONGODB_USERNAME"]
        password = st.secrets["MONGODB_PASSWORD"]
        connection_string = st.secrets["MONGODB_CONNECTION_STRING"].replace("<db_password>", password)
        
        # Connect to MongoDB
        client = pymongo.MongoClient(connection_string)
        
        # Validate connection
        client.admin.command('ping')
        if st.session_state.get('debug_mode', False):
            st.write("Debug: Successfully connected to MongoDB")  # Debug log
        return client
    except Exception as e:
        if st.session_state.get('debug_mode', False):
            st.error(f"Debug: Failed to connect to MongoDB: {str(e)}")  # Debug log
        else:
            st.error("Failed to connect to MongoDB")
        raise

def get_modules_data():
    """
    Retrieve all modules data from MongoDB.
    
    Returns:
        dict: A dictionary containing all modules data.
    """
    try:
        client = get_mongo_client()
        db = client["funce_db"]
        modules_collection = db["modules"]
        
        # Get all modules
        modules_data = [x for x in modules_collection.find({})]
        
        if not modules_data:
            # Create sample modules data if none exists
            sample_modules = {
                "modules": [
                    {
                        "title": "Introduction to Chemical Engineering",
                        "vector_store_id": "module1",
                        "topics": [
                            {
                                "name": "Introduction to Chemical Engineering Principles",
                                "description": "Basic concepts of chemical engineering and their applications"
                            },
                            {
                                "name": "Material Balances",
                                "description": "Fundamental principles of material balances in chemical processes"
                            },
                            {
                                "name": "Energy Balances",
                                "description": "Understanding energy conservation and transformation in chemical systems"
                            }
                        ],
                        "tutorial_questions": {
                            "1.1": {
                                "question": "Calculate a simple material balance",
                                "difficulty": "medium"
                            },
                            "1.2": {
                                "question": "Apply energy balance to a chemical reactor",
                                "difficulty": "hard"
                            }
                        }
                    },
                    {
                        "title": "Thermodynamics",
                        "vector_store_id": "module2",
                        "topics": [
                            {
                                "name": "Laws of Thermodynamics",
                                "description": "First and second laws of thermodynamics and their applications"
                            },
                            {
                                "name": "Phase Equilibria",
                                "description": "Understanding phase behavior in chemical systems"
                            }
                        ],
                        "tutorial_questions": {
                            "2.1": {
                                "question": "Calculate entropy change in a process",
                                "difficulty": "medium"
                            }
                        }
                    }
                ]
            }
            
            # Insert sample data
            modules_collection.insert_one(sample_modules)
            st.info("Initialized modules database with sample data")
            modules_data = sample_modules
        
        # Ensure the data has the correct structure
        if "modules" not in modules_data:
            # If modules_data is a list, wrap it in a modules key
            if isinstance(modules_data, list):
                modules_data = {"modules": modules_data}
            else:
                st.error("Modules data does not have the expected structure.")
                return {"modules": []}
        
        if st.session_state.get('debug_mode', False):
            st.write("Debug: Retrieved modules data:", modules_data)  # Debug log
        return modules_data
    except Exception as e:
        if st.session_state.get('debug_mode', False):
            st.error(f"Debug: Error in get_modules_data: {str(e)}")  # Debug log
        else:
            st.error("Error retrieving modules data")
        return {"modules": []}

def get_user_progress(user_id="user123"):
    """
    Retrieve user progress data from MongoDB using the new user_module_progress collection.
    
    Args:
        user_id (str): The ID of the user.
        
    Returns:
        dict: A dictionary containing the user's progress data.
    """
    try:
        client = get_mongo_client()
        db = client["funce_db"]
        user_progress_collection = db["user_module_progress"]
        
        # Get user progress
        user_data = user_progress_collection.find_one({"user_id": user_id})
        
        if not user_data:
            # Get modules data to create appropriate default progress structure
            modules_data = get_modules_data()
            modules_list = modules_data.get("modules", [])
            
            # Create default progress structure for new user
            default_data = {
                "user_id": user_id,
                "last_updated": datetime.now(),
                "topics": [],
                "tutorial_questions": []
            }
            
            # Initialize topics and tutorial questions for each module
            for i, module in enumerate(modules_list, 1):
                module_id = str(i)
                topics = module.get("topics", [])
                tutorial_questions = module.get("tutorial_questions", [])
                
                # Add topics with default progress
                for topic in topics:
                    topic_id = f"{module_id}.{len(default_data['topics']) + 1}"
                    default_data["topics"].append({
                        "topic_id": topic_id,
                        "name": topic.get("name", str(topic)),
                        "progress": 0,
                        "status": "not_started"
                    })
                
                # Add tutorial questions with default progress
                for question in tutorial_questions:
                    question_id = f"{module_id}.{len(default_data['tutorial_questions']) + 1}"
                    default_data["tutorial_questions"].append({
                        "question_id": question_id,
                        "progress": 0,
                        "status": "not_started",
                        "attempts": 0,
                        "last_attempt": None
                    })
            
            user_progress_collection.insert_one(default_data)
            st.info(f"Created default progress data for user {user_id}")
            user_data = default_data
        
        # Only show debug output if debug_mode is True in session state
        if st.session_state.get('debug_mode', False):
            st.write("Debug: Retrieved user progress:", user_data)  # Debug log
        return user_data
    except Exception as e:
        # Only show debug output if debug_mode is True in session state
        if st.session_state.get('debug_mode', False):
            st.error(f"Debug: Error in get_user_progress: {str(e)}")  # Debug log
        else:
            st.error(f"Error retrieving user progress")
        return {"topics": [], "tutorial_questions": []}

def update_user_progress(user_id, module_id, topic_id=None, question_id=None, progress=None, status=None):
    """
    Update user progress in MongoDB using the new user_module_progress collection.
    
    Args:
        user_id (str): The ID of the user.
        module_id (str): The ID of the module.
        topic_id (str, optional): The ID of the topic to update.
        question_id (str, optional): The ID of the question to update.
        progress (int, optional): The new progress value (0-100).
        status (str, optional): The new status to set.
    """
    try:
        client = get_mongo_client()
        db = client["funce_db"]
        user_progress_collection = db["user_module_progress"]
        
        update_data = {
            "last_updated": datetime.now()
        }
        
        if topic_id is not None:
            if progress is not None:
                update_data["topics.$[topic].progress"] = progress
            if status is not None:
                update_data["topics.$[topic].status"] = status
        
        if question_id is not None:
            if progress is not None:
                update_data["tutorial_questions.$[question].progress"] = progress
            if status is not None:
                update_data["tutorial_questions.$[question].status"] = status
            update_data["tutorial_questions.$[question].last_attempt"] = datetime.now()
            update_data["tutorial_questions.$[question].attempts"] = {"$inc": 1}
        
        if update_data:
            array_filters = []
            if topic_id:
                array_filters.append({"topic.topic_id": topic_id})
            if question_id:
                array_filters.append({"question.question_id": question_id})
            
            user_progress_collection.update_one(
                {"user_id": user_id},
                {"$set": update_data},
                array_filters=array_filters
            )
            
            if st.session_state.get('debug_mode', False):
                st.write(f"Debug: Updated progress for user {user_id}")
    except Exception as e:
        if st.session_state.get('debug_mode', False):
            st.error(f"Debug: Error in update_user_progress: {str(e)}")
        else:
            st.error("Error updating user progress")

def get_module_by_id(module_id):
    """
    Retrieve a specific module by its ID from MongoDB.
    
    Args:
        module_id (str): The ID of the module.
        
    Returns:
        dict: A dictionary containing the module data.
    """
    client = get_mongo_client()
    db = client["funce_db"]
    modules_collection = db["modules"]
    
    # Get the module
    module_data = modules_collection.find_one({"modules": {"$elemMatch": {"_id": module_id}}})
    
    if not module_data:
        return None
    
    # Find the specific module in the modules array
    for module in module_data.get("modules", []):
        if module.get("_id") == module_id:
            return module
    
    return None

def get_topic_by_name(module_id, topic_name):
    """
    Retrieve a specific topic by its name from a module.
    
    Args:
        module_id (str): The ID of the module.
        topic_name (str): The name of the topic.
        
    Returns:
        dict: A dictionary containing the topic data.
    """
    module = get_module_by_id(module_id)
    if not module:
        return None
    
    for topic in module.get("topics", []):
        if topic.get("name") == topic_name:
            return topic
    
    return None

def get_question_by_id(module_id, question_id):
    """
    Retrieve a specific question by its ID from a module.
    
    Args:
        module_id (str): The ID of the module.
        question_id (str): The ID of the question.
        
    Returns:
        dict: A dictionary containing the question data.
    """
    module = get_module_by_id(module_id)
    if not module:
        return None
    
    return module.get("tutorial_questions", {}).get(question_id)

def get_question_details(module_num, question_num):
    """
    Retrieve details for a specific question from MongoDB.
    
    Args:
        module_num (int or str): The module number.
        question_num (int or str): The question number within the module.
        
    Returns:
        dict: A dictionary containing question details.
    """
    # Convert to integers in case they're strings
    module_num = int(module_num)
    question_num = int(question_num)
    
    # Connect to MongoDB
    client = get_mongo_client()
    db = client["FunCE"]
    questions_collection = db["questions"]
    
    # Query the database
    question_data = questions_collection.find_one({
        "module": module_num, 
        "question_number": question_num
    })
    
    # If question not found, return placeholder data
    if not question_data:
        return {
            "title": f"Module {module_num} - Question {question_num}",
            "description": "This question hasn't been added to the database yet.",
            "hints": ["No hints available for this question yet."],
            "module": module_num,
            "question_number": question_num
        }
    
    # Return the question data
    return question_data

def get_module_topics(module_num):
    """
    Retrieve all topics for a specific module from MongoDB.
    
    Args:
        module_num (int or str): The module number.
        
    Returns:
        list: A list of dictionaries containing topic information.
    """
    # Convert to integer in case it's a string
    module_num = int(module_num)
    
    # Connect to MongoDB
    client = get_mongo_client()
    db = client["FunCE"]
    questions_collection = db["questions"]
    
    # Query the database for all questions in the module
    topics = list(questions_collection.find({"module": module_num}, {"title": 1, "description": 1, "question_number": 1, "status": 1}))
    
    # Sort by question number
    topics.sort(key=lambda x: x.get("question_number", 0))
    
    return topics

def get_all_modules():
    """
    Retrieve all modules with their questions from MongoDB.
    
    Returns:
        dict: A dictionary where keys are module titles and values are 
              dictionaries of topics and their status.
    """
    # Connect to MongoDB
    client = get_mongo_client()
    db = client["FunCE"]
    modules_collection = db["modules"]
    questions_collection = db["questions"]
    
    # Get all modules
    modules = list(modules_collection.find({}, {"module_number": 1, "title": 1}))
    
    # Initialize the result dictionary
    result = {}
    
    # For each module, get its topics
    for module in modules:
        module_num = module.get("module_number")
        module_title = module.get("title")
        
        # Get all questions for this module
        questions = list(questions_collection.find({"module": module_num}, {"title": 1, "status": 1}))
        
        # Add to result with default status of "🔴" if not specified
        module_topics = {}
        for question in questions:
            module_topics[question.get("title")] = question.get("status", "🔴")
        
        result[module_title] = module_topics
    
    # If no modules were found, return placeholder data
    if not result:
        return {
            "Introduction": {
                "Introduction to Chemical Engineering Fundamentals": '✅',
                "Principles of Material Balances": '✅',
                "Thermodynamics in Chemical Processes": '🟠',
                "Fluid Flow Operations": '🟠',
                "Process Safety & Ethics": '🔴',
            },
            # ... other placeholder modules ...
        }
    
    return result