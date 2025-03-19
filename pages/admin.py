import streamlit as st
import os
from openai import OpenAI
from datetime import datetime

# Check if user is logged in
if "logged_in" not in st.session_state or not st.session_state.logged_in:
    st.warning("Please login from the Home page to access the admin page.")
    st.stop()

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

# Load tutor instructions
with open('prompts/tutor.md', 'r') as f:
    TUTOR_INSTRUCTIONS = f.read()

st.set_page_config(
    page_title="File Management Admin",
    page_icon="📁",
    layout="wide"
)

# Initialize session state for chat
if 'messages' not in st.session_state:
    st.session_state.messages = []
if 'current_file_id' not in st.session_state:
    st.session_state.current_file_id = None

st.title("📁 File Management Admin")

# File Upload Section
st.header("Upload New File")
with st.form("upload_form"):
    uploaded_file = st.file_uploader("Choose a file", type=['jsonl', 'pdf', 'txt'])
    purpose = st.selectbox(
        "Select Purpose",
        ["fine-tune", "assistants", "user_data"],
        help="Select the purpose for which this file will be used"
    )
    submit_button = st.form_submit_button("Upload File")

if submit_button and uploaded_file is not None:
    try:
        with st.spinner("Uploading file..."):
            response = client.files.create(
                file=uploaded_file,
                purpose=purpose
            )
            st.success(f"File uploaded successfully! ID: {response.id}")
    except Exception as e:
        st.error(f"Error uploading file: {str(e)}")

# List Files Section
st.header("Manage Files")
try:
    files = client.files.list()
    
    if not files.data:
        st.info("No files found. Upload a file to get started.")
    else:
        # Create a table of files
        file_data = []
        for file in files.data:
            created_at = datetime.fromtimestamp(file.created_at).strftime('%Y-%m-%d %H:%M:%S') if file.created_at else "N/A"
            expires_at = datetime.fromtimestamp(file.expires_at).strftime('%Y-%m-%d %H:%M:%S') if hasattr(file, 'expires_at') and file.expires_at else "N/A"
            
            file_data.append({
                "ID": file.id,
                "Filename": file.filename,
                "Purpose": file.purpose,
                "Size (bytes)": file.bytes,
                "Created": created_at,
                "Expires": expires_at
            })
        
        st.dataframe(file_data, use_container_width=True)
        
        # File Operations
        st.subheader("File Operations")
        selected_file_id = st.selectbox(
            "Select a file to manage",
            [file.id for file in files.data],
            format_func=lambda x: next((f.id for f in files.data if f.id == x), x)
        )
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("View File Details"):
                try:
                    file_info = client.files.retrieve(selected_file_id)
                    st.json(file_info)
                except Exception as e:
                    st.error(f"Error retrieving file details: {str(e)}")
        
        with col2:
            if st.button("Delete File", type="primary"):
                try:
                    client.files.delete(selected_file_id)
                    st.success("File deleted successfully!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error deleting file: {str(e)}")

except Exception as e:
    st.error(f"Error listing files: {str(e)}")

# Add some helpful information
with st.expander("Help"):
    st.markdown("""
    ### How to use this admin page:
    
    1. **Upload a File**:
       - Click the file uploader to select a file
       - Choose the purpose for the file
       - Click "Upload File"
    
    2. **Manage Files**:
       - View all uploaded files in the table
       - Select a file from the dropdown to perform operations
       - View file details or delete files as needed
    
    3. **File Purposes**:
       - `fine-tune`: For fine-tuning models
       - `assistants`: For use with assistants
       - `user_data`: For storing user data
    """) 