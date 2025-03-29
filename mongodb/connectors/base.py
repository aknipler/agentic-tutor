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