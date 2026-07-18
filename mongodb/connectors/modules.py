import streamlit as st
from .base import get_mongo_client

def get_cached_modules_data():
    """Get modules data from cache or fetch if not available"""
    if "cached_modules_data" not in st.session_state:
        st.session_state.cached_modules_data = get_modules_data()
    return st.session_state.cached_modules_data

def get_modules_data():
    """
    Retrieve all modules data from MongoDB with efficient caching.
    
    Returns:
        dict: A dictionary containing all modules data.
    """
    # Check session state cache first
    if "cached_modules_data" in st.session_state:
        return st.session_state.cached_modules_data
        
    print("[get_modules_data] Retrieving modules data")  # Only logs on actual DB fetch
    try:
        client = get_mongo_client()
        db = client[st.secrets["MONGODB_DATABASE_NAME"]]
        modules_collection = db["modules_live"]
        
        # Get all modules
        modules_data = [x for x in modules_collection.find({})]
        
        if not modules_data:
            # An empty collection is a setup problem, not something to paper over.
            # This used to insert FunCE sample data, which silently seeded the live
            # PRQ database with chemical-engineering modules. Report instead.
            db_name = st.secrets["MONGODB_DATABASE_NAME"]
            print(
                f"[get_modules_data] No documents in {db_name}.modules_live - "
                "the collection is empty."
            )
            st.error(
                f"No modules found in the database (`{db_name}.modules_live`).\n\n"
                "This usually means the module data hasn't been loaded yet. "
                "Load it with:\n\n"
                "`python scripts/load_week_json.py --commit`\n\n"
                "If you expected data to be there, check that "
                "`MONGODB_DATABASE_NAME` in `.streamlit/secrets.toml` points at the "
                "right database."
            )
            return {"modules": []}

        # Ensure the data has the correct structure
        if isinstance(modules_data, list):
            modules_data = {"modules": modules_data}
            
        # Cache in session state
        st.session_state.cached_modules_data = modules_data
        return modules_data
        
    except Exception as e:
        if st.session_state.get('debug_mode', False):
            st.error(f"Debug: Error in get_modules_data: {str(e)}")
        else:
            st.error("Error retrieving modules data")
        return {"modules": []}

def get_module_by_id(module_id):
    """
    Retrieve a specific module by its ID from MongoDB.
    
    Args:
        module_id (str): The ID of the module.
        
    Returns:
        dict: A dictionary containing the module data.
    """
    client = get_mongo_client()
    db = client[st.secrets["MONGODB_DATABASE_NAME"]]
    modules_collection = db["modules_live"]
    
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
    db = client[st.secrets["MONGODB_DATABASE_NAME"]]
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
    db = client[st.secrets["MONGODB_DATABASE_NAME"]]
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
    db = client[st.secrets["MONGODB_DATABASE_NAME"]]
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
    
    # No modules found: report it rather than returning invented placeholder data
    # (this used to hand back a fake FunCE module).
    if not result:
        print(
            "[get_all_modules] No documents in the legacy 'modules'/'questions' "
            "collections. Note the live app reads 'modules_live' instead."
        )
        return {}

    return result 