import pandas as pd
import sys
import os

# Add the project root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mongodb.connectors.base import get_mongo_client

# 1. Read CSVs
module_df = pd.read_csv('module_data.csv')
question_df = pd.read_csv('question_data.csv')

# 2. Clean and normalize data (strip whitespace, fillna, etc.)
module_df = module_df.fillna('')
question_df = question_df.fillna('')

# 3. Build module documents
modules = []
for module_num, module_group in module_df.groupby('Module Number'):
    module_name = module_group['Module Name'].iloc[0]
    module_doc = {
        'title': module_name,
        'index': int(module_num),
        'topics': [],
        'tutorial_questions': []
    }
    # Add topics
    for _, row in module_group.iterrows():
        topic = {
            'name': row['Topic'],
            'description': row['Description (Answer)'],
            'question': row['Questions'],
            # Add any extra fields here if present
        }
        module_doc['topics'].append(topic)
    # Add questions from question_data.csv
    questions = question_df[question_df['Module Number'] == module_num]
    for _, qrow in questions.iterrows():
        question = {
            'label': qrow['Question label'],
            'question': qrow['Question text'],
            'expected_answer': qrow['Expected answer'],
            'success_criteria': qrow['Success criteria'],
            'agent_context': qrow['Further information required in prompt'],
            'image_url': qrow['Link to Images']
            # Add any extra fields here if present
        }
        module_doc['tutorial_questions'].append(question)
    modules.append(module_doc)

# 4. Insert into MongoDB
client = get_mongo_client()
db = client['funce_db']
db['modules_live'].delete_many({})  # Optional: clear old data
db['modules_live'].insert_many(modules)

print("Data ingested into modules_live collection successfully.")
