import streamlit as st
from datetime import datetime
from .base import get_mongo_client

def verify_user_login(login_code):
    """
    Verify if a user login code exists in the database.
    
    Args:
        login_code (str): The login code to verify.
        
    Returns:
        bool: True if the login code is valid, False otherwise.
    """
    try:
        client = get_mongo_client()
        db = client["funce_db"]
        users_collection = db["users"]
        
        # Check if user exists
        user = users_collection.find_one({"login_code": login_code})
        
        if user:
            return True
        else:
            return False
            
    except Exception as e:
        if st.session_state.get('debug_mode', False):
            st.error(f"Debug: Error in verify_user_login: {str(e)}")
        return False

def create_user(login_code, name=""):
    """
    Create a new user with the given login code.
    
    Args:
        login_code (str): The login code for the new user.
        name (str): Optional name for the user.
        
    Returns:
        bool: True if user creation was successful, False otherwise.
    """
    try:
        client = get_mongo_client()
        db = client["funce_db"]
        users_collection = db["users"]
        
        # Check if user already exists
        existing_user = users_collection.find_one({"login_code": login_code})
        if existing_user:
            if st.session_state.get('debug_mode', False):
                st.error(f"Debug: User with login code {login_code} already exists")
            return False
        
        # Create new user
        new_user = {
            "login_code": login_code,
            "name": name,
            "created_at": datetime.now()
        }
        
        result = users_collection.insert_one(new_user)
        
        if result.inserted_id:
            return True
        else:
            return False
            
    except Exception as e:
        if st.session_state.get('debug_mode', False):
            st.error(f"Debug: Error in create_user: {str(e)}")
        return False

def get_or_create_default_users():
    """
    Ensures that default users exist in the database.
    
    Returns:
        list: A list of default login codes.
    """
    try:
        client = get_mongo_client()
        db = client["funce_db"]
        users_collection = db["users"]
        
        # Default login codes
        default_login_codes = ["FUNCE001", "FUNCE002", "FUNCE003"]
        
        # Check if users collection is empty
        if users_collection.count_documents({}) == 0:
            # Create default users
            for code in default_login_codes:
                users_collection.insert_one({
                    "login_code": code,
                    "name": f"Default User {code[-3:]}",
                    "created_at": datetime.now()
                })
            
            if st.session_state.get('debug_mode', False):
                st.info("Debug: Created default users")
        
        return default_login_codes
    
    except Exception as e:
        if st.session_state.get('debug_mode', False):
            st.error(f"Debug: Error in get_or_create_default_users: {str(e)}")
        return [] 