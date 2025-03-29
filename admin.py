import streamlit as st
import os
from pathlib import Path
from datetime import datetime
import pandas as pd
from typing import List, Dict
import json
from openai import OpenAI
from openai.types.beta.assistant import Assistant
from openai.types.vector_store import VectorStore
import tempfile

# Set page config
st.set_page_config(
    page_title="Admin Dashboard",
    page_icon="⚙️",
    layout="wide"
)

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Security check - you should implement proper authentication
def check_admin_access():
    # TODO: Implement proper authentication
    return True

def get_vector_store_info(store: VectorStore) -> Dict:
    """Get information about a vector store."""
    return {
        "id": store.id,
        "name": store.name,
        "created_at": datetime.fromtimestamp(store.created_at).strftime('%Y-%m-%d %H:%M:%S'),
        "metadata": store.metadata or {}
    }

def main():
    if not check_admin_access():
        st.error("You don't have permission to access this page.")
        return

    st.title("Admin Dashboard")
    
    # Create tabs for different sections
    tab1, tab2 = st.tabs(["Vector Store Management", "Assistant Management"])
    
    with tab1:
        st.header("Vector Store Management")
        
        # Vector store listing section
        st.subheader("Existing Vector Stores")
        try:
            vector_stores = client.vector_stores.list()
            if vector_stores.data:
                stores = [get_vector_store_info(store) for store in vector_stores.data]
                df = pd.DataFrame(stores)
                st.dataframe(df)
                
                # Vector store deletion
                store_to_delete = st.selectbox("Select vector store to delete", [s["id"] for s in stores])
                if st.button("Delete Selected Vector Store"):
                    try:
                        client.vector_stores.delete(store_to_delete)
                        st.success(f"Vector store deleted successfully!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error deleting vector store: {str(e)}")
            else:
                st.info("No vector stores found.")
        except Exception as e:
            st.error(f"Error fetching vector stores: {str(e)}")
        
        # Vector store creation section
        st.subheader("Create New Vector Store")
        new_store_name = st.text_input("Enter name for new vector store")
        if st.button("Create Vector Store"):
            if new_store_name:
                try:
                    vector_store = client.vector_stores.create(
                        name=new_store_name,
                        metadata={"created_by": "admin_dashboard"}
                    )
                    st.success(f"Vector store '{new_store_name}' created successfully!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error creating vector store: {str(e)}")
            else:
                st.warning("Please enter a name for the vector store.")

        # File upload section
        st.subheader("Add Files to Vector Store")
        if vector_stores.data:
            selected_store = st.selectbox(
                "Select vector store to add files to",
                [store.id for store in vector_stores.data],
                format_func=lambda x: next((store.name for store in vector_stores.data if store.id == x), x)
            )
            
            uploaded_files = st.file_uploader(
                "Upload files to add to the vector store",
                type=["txt", "pdf", "doc", "docx", "md"],
                accept_multiple_files=True
            )
            
            if uploaded_files and st.button("Add Files to Vector Store"):
                with st.spinner("Processing files..."):
                    for uploaded_file in uploaded_files:
                        try:
                            # Create a temporary file to store the uploaded content
                            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                                temp_file.write(uploaded_file.getvalue())
                                temp_file_path = temp_file.name
                            
                            # Add the file to the vector store
                            with open(temp_file_path, 'rb') as file:
                                client.vector_stores.files.create(
                                    vector_store_id=selected_store,
                                    file=file,
                                    metadata={
                                        "filename": uploaded_file.name,
                                        "content_type": uploaded_file.type,
                                        "uploaded_at": datetime.now().isoformat()
                                    }
                                )
                            
                            # Clean up the temporary file
                            os.unlink(temp_file_path)
                            
                        except Exception as e:
                            st.error(f"Error processing file {uploaded_file.name}: {str(e)}")
                            continue
                    
                    st.success("Files processed successfully!")
                    st.rerun()
        else:
            st.info("No vector stores available. Please create a vector store first.")
    
    with tab2:
        st.header("Assistant Management")
        
        # Assistant listing section
        st.subheader("Existing Assistants")
        try:
            assistants = client.beta.assistants.list()
            if assistants.data:
                assistant_data = []
                for assistant in assistants.data:
                    assistant_data.append({
                        "id": assistant.id,
                        "name": assistant.name,
                        "model": assistant.model,
                        "created_at": datetime.fromtimestamp(assistant.created_at).strftime('%Y-%m-%d %H:%M:%S'),
                        "tools": [tool.type for tool in assistant.tools] if assistant.tools else []
                    })
                df = pd.DataFrame(assistant_data)
                st.dataframe(df)
                
                # Assistant deletion
                assistant_to_delete = st.selectbox("Select assistant to delete", [a["id"] for a in assistant_data])
                if st.button("Delete Selected Assistant"):
                    try:
                        client.beta.assistants.delete(assistant_to_delete)
                        st.success(f"Assistant deleted successfully!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error deleting assistant: {str(e)}")
            else:
                st.info("No assistants found.")
        except Exception as e:
            st.error(f"Error fetching assistants: {str(e)}")
        
        # Assistant creation section
        st.subheader("Create New Assistant")
        col1, col2 = st.columns(2)
        with col1:
            new_assistant_name = st.text_input("Enter name for new assistant")
        with col2:
            model = st.selectbox(
                "Select model",
                ["gpt-4-turbo-preview", "gpt-3.5-turbo"],
                index=0
            )
        
        if st.button("Create Assistant"):
            if new_assistant_name:
                try:
                    assistant = client.beta.assistants.create(
                        name=new_assistant_name,
                        model=model,
                        tools=[{"type": "retrieval"}],
                        metadata={"created_by": "admin_dashboard"}
                    )
                    st.success(f"Assistant '{new_assistant_name}' created successfully!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error creating assistant: {str(e)}")
            else:
                st.warning("Please enter a name for the assistant.")

if __name__ == "__main__":
    main() 