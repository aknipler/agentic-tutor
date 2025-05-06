import pandas as pd
import random
import string
import os
import sys
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from mongodb.connectors.user_progress import create_user_progress

def generate_random_code(length=6):
    """Generate a random alphanumeric code of specified length."""
    characters = string.ascii_uppercase + string.digits
    return ''.join(random.choice(characters) for _ in range(length))

def create_users_from_classlist():
    # Read the classlist
    df = pd.read_csv('data/classlist.csv')
    
    # Create a mapping of email to random code
    email_to_code = {}
    used_codes = set()
    
    # Generate codes for all students
    for email in df['Email']:
        while True:
            code = generate_random_code()
            if code not in used_codes:
                used_codes.add(code)
                email_to_code[email] = code
                break
    
    # Generate 15 spare codes
    spare_codes = []
    for _ in range(15):
        while True:
            code = generate_random_code()
            if code not in used_codes:
                used_codes.add(code)
                spare_codes.append(code)
                break
    
    # Create users for each student
    created_users = []
    failed_users = []
    
    for email, code in email_to_code.items():
        try:
            if create_user_progress(code):
                created_users.append((email, code))
            else:
                failed_users.append((email, code))
        except Exception as e:
            failed_users.append((email, code))
            print(f"Error creating user for {email}: {str(e)}")
    
    # Save the mapping to a CSV file
    mapping_df = pd.DataFrame([
        {'Email': email, 'Code': code} for email, code in email_to_code.items()
    ])
    mapping_df.to_csv('data/user_codes.csv', index=False)
    
    # Save spare codes to a separate file
    spare_df = pd.DataFrame({'Spare Codes': spare_codes})
    spare_df.to_csv('data/spare_codes.csv', index=False)
    
    # Print summary
    print(f"\nSummary:")
    print(f"Total students processed: {len(df)}")
    print(f"Successfully created users: {len(created_users)}")
    print(f"Failed to create users: {len(failed_users)}")
    print(f"Spare codes generated: {len(spare_codes)}")
    
    if failed_users:
        print("\nFailed users:")
        for email, code in failed_users:
            print(f"Email: {email}, Code: {code}")
    
    print("\nUser codes have been saved to 'data/user_codes.csv'")
    print("Spare codes have been saved to 'data/spare_codes.csv'")

if __name__ == "__main__":
    create_users_from_classlist() 