import json
import pymongo
from datetime import datetime
from pathlib import Path
import streamlit as st

def connect_to_mongodb():
    """Connect to MongoDB and return the client using Streamlit secrets"""
    # Load secrets
    secrets = st.secrets
    
    # Get MongoDB credentials and connection string
    username = secrets["MONGODB_USERNAME"]
    password = secrets["MONGODB_PASSWORD"]
    connection_string = secrets["MONGODB_CONNECTION_STRING"]
    
    # Replace the password placeholder in the connection string
    connection_string = connection_string.replace("<db_password>", password)
    
    # Create MongoDB client
    client = pymongo.MongoClient(connection_string)
    return client

def load_json_file(file_path):
    """Load and parse a JSON file"""
    with open(file_path, 'r') as f:
        return json.load(f)

def transform_modules_data(modules_data):
    """Transform modules data into a format suitable for MongoDB"""
    transformed_data = []
    
    # Extract modules from the data
    modules = modules_data.get('modules', [])
    
    for module in modules:
        # Create a new document for each module
        module_doc = {
            'title': module['title'],
            'vector_store_id': module['vector_store_id'],
            'topics': module['topics'],
            'tutorial_questions': []
        }
        
        # Transform tutorial questions into a list of documents
        for q_id, q_data in module['tutorial_questions'].items():
            question_doc = {
                'question_id': q_id,
                'question': q_data['question'],
                'expected_answer': q_data['expected_answer']
            }
            module_doc['tutorial_questions'].append(question_doc)
        
        transformed_data.append(module_doc)
    
    return transformed_data

def transform_user_progress_data(progress_data):
    """Transform user progress data into a format suitable for MongoDB"""
    transformed_data = []
    
    for user_id, user_data in progress_data.items():
        user_doc = {
            'user_id': user_id,
            'last_login': datetime.strptime(user_data['last_login'], '%Y-%m-%d'),
            'total_study_time': user_data['total_study_time'],
            'modules_progress': []
        }
        
        for module_id, module_progress in user_data['modules'].items():
            module_progress_doc = {
                'module_id': module_id,
                'topics_status': module_progress['topics_status'],
                'tutorial_questions_progress': []
            }
            
            for q_id, q_progress in module_progress['tutorial_questions_progress'].items():
                question_progress_doc = {
                    'question_id': q_id,
                    'status': q_progress['status'],
                    'attempts': q_progress['attempts'],
                    'last_attempt': datetime.strptime(q_progress['last_attempt'], '%Y-%m-%d') if q_progress['last_attempt'] else None
                }
                module_progress_doc['tutorial_questions_progress'].append(question_progress_doc)
            
            user_doc['modules_progress'].append(module_progress_doc)
        
        transformed_data.append(user_doc)
    
    return transformed_data

def main():
    # Connect to MongoDB
    client = connect_to_mongodb()
    db = client['funce_db']
    
    # Load data files
    data_dir = Path(__file__).parent.parent / 'data'
    modules_data = load_json_file(data_dir / 'modules.json')
    progress_data = load_json_file(data_dir / 'user_progress.json')
    
    # Transform data
    transformed_modules = transform_modules_data(modules_data)
    transformed_progress = transform_user_progress_data(progress_data)
    
    # Clear existing collections
    db.modules.delete_many({})
    db.user_progress.delete_many({})
    
    # Insert transformed data
    if transformed_modules:
        db.modules.insert_many(transformed_modules)
        print(f"Inserted {len(transformed_modules)} modules")
    
    if transformed_progress:
        db.user_progress.insert_many(transformed_progress)
        print(f"Inserted {len(transformed_progress)} user progress records")
    
    print("Data loading completed successfully!")

if __name__ == "__main__":
    main() 