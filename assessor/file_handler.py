import os
from datetime import datetime
import streamlit as st
from typing import Optional, Any

def save_uploaded_file(uploaded_file: Any, user_id: str, question_id: str) -> Optional[str]:
    """Save an uploaded file and return the file path"""
    if not uploaded_file:
        return None
        
    # Create uploads directory if it doesn't exist
    upload_dir = "uploads"
    if not os.path.exists(upload_dir):
        os.makedirs(upload_dir)
    
    # Generate unique filename
    file_extension = os.path.splitext(uploaded_file.name)[1]
    file_name = f"{user_id}_{question_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{file_extension}"
    file_path = os.path.join(upload_dir, file_name)
    
    # Save the file
    try:
        with open(file_path, "wb") as f:
            f.write(uploaded_file.getvalue())
        return file_path
    except Exception as e:
        st.error(f"Error saving file: {str(e)}")
        return None

def get_file_url(file_path: str) -> Optional[str]:
    """Convert a local file path to a data URL for the OpenAI API
    
    This function reads a file and converts it to a data URL format
    that can be used with the OpenAI API.
    """
    if not file_path or not os.path.exists(file_path):
        return None
        
    try:
        with open(file_path, "rb") as f:
            file_data = f.read()
        
        import base64
        file_extension = os.path.splitext(file_path)[1].lower()[1:]  # Remove the dot
        mime_type = f"image/{file_extension}"
        encoded_data = base64.b64encode(file_data).decode('utf-8')
        
        return f"data:{mime_type};base64,{encoded_data}"
    except Exception as e:
        st.error(f"Error converting file to URL: {str(e)}")
        return None 