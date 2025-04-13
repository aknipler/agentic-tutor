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
from mongodb.connectors import get_modules_data, get_mongo_client

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

def update_module_vector_store(module_title: str, vector_store_id: str) -> bool:
    """Update a module's vector store ID in MongoDB."""
    try:
        client = get_mongo_client()
        db = client["funce_db"]
        modules_collection = db["modules"]
        
        # Print the module title and vector store ID
        print(f"Updating module '{module_title}' with vector store ID '{vector_store_id}'")
        
        # Correct query for the given structure
        query = {"title": module_title}
        update = {"$set": {"vector_store_id": vector_store_id}}
        
        # Print the query and update
        print(f"Query - {query}")
        print(f"Update - {update}")
        
        # Execute the update
        result = modules_collection.update_one(query, update)
        
        # Print the result of the update operation
        print(f"Update result - matched: {result.matched_count}, modified: {result.modified_count}")
        
        return result.modified_count > 0
    except Exception as e:
        print(f"Error updating module vector store: {str(e)}")
        return False

def main():
    if not check_admin_access():
        st.error("You don't have permission to access this page.")
        return

    st.title("Admin Dashboard")
    
    # Create tabs for different sections
    tab1, tab2, tab3 = st.tabs(["Vector Store Management", "Module-Vector Store Management", "Assistant Management"])
    
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
                accept_multiple_files=True,
                key="add_files_to_vector_store"
            )
            
            if uploaded_files and st.button("Add Files to Vector Store"):
                with st.spinner("Processing files..."):
                    for uploaded_file in uploaded_files:
                        try:
                            # Create a temporary file to store the uploaded content
                            with tempfile.NamedTemporaryFile(delete=False, suffix=f".{uploaded_file.name.split('.')[-1]}") as temp_file:
                                temp_file.write(uploaded_file.getvalue())
                                temp_file_path = temp_file.name
                            
                            # Upload the file to get a file_id with purpose
                            file_id = client.files.create(
                                file=open(temp_file_path, 'rb'),
                                purpose='user_data'
                            ).id
                            
                            # Add the file_id to the vector store
                            client.vector_stores.files.create(
                                vector_store_id=selected_store,
                                file_id=file_id,
                                attributes={
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
        st.header("Module-Vector Store Management")
        
        # Get modules data from MongoDB
        modules_data = get_modules_data()
        modules = modules_data.get("modules", [])
        
        if not modules:
            st.warning("No modules found in the database.")
            return
        
        # Get vector stores from OpenAI
        try:
            vector_stores = client.vector_stores.list()
            if not vector_stores.data:
                st.warning("No vector stores found. Please create a vector store first.")
                return
            
            # Create a mapping of module titles to their current vector store IDs
            module_vector_store_map = {}
            for module in modules:
                module_vector_store_map[module.get("title")] = module.get("vector_store_id", "")
            
            # Display current module-vector store mappings
            st.subheader("Current Module-Vector Store Mappings")
            
            # Create a DataFrame for better visualization
            mapping_data = []
            for module in modules:
                module_title = module.get("title", "Unknown")
                current_vector_store_id = module.get("vector_store_id", "")
                
                # Find the vector store name if it exists
                vector_store_name = "Not linked"
                for store in vector_stores.data:
                    if store.id == current_vector_store_id:
                        vector_store_name = store.name
                        break
                
                mapping_data.append({
                    "Module Title": module_title,
                    "Current Vector Store ID": current_vector_store_id,
                    "Vector Store Name": vector_store_name
                })
            
            df = pd.DataFrame(mapping_data)
            st.dataframe(df)
            
            # Module-Vector Store linking section
            st.subheader("Link Vector Store to Module")
            
            # Select module
            module_titles = [module.get("title", "Unknown") for module in modules]
            selected_module = st.selectbox("Select module", module_titles)
            
            # Select vector store
            vector_store_options = [{"id": store.id, "name": store.name} for store in vector_stores.data]
            vector_store_names = [store["name"] for store in vector_store_options]
            
            # Find the current vector store index
            current_vector_store_id = module_vector_store_map.get(selected_module, "")
            current_index = 0
            for i, store in enumerate(vector_store_options):
                if store["id"] == current_vector_store_id:
                    current_index = i
                    break
            
            selected_vector_store_index = st.selectbox(
                "Select vector store to link",
                range(len(vector_store_options)),
                index=current_index,
                format_func=lambda x: vector_store_names[x]
            )
            
            if st.button("Update Module-Vector Store Link"):
                selected_vector_store_id = vector_store_options[selected_vector_store_index]["id"]
                
                if update_module_vector_store(selected_module, selected_vector_store_id):
                    st.success(f"Successfully linked '{selected_module}' to vector store '{vector_store_names[selected_vector_store_index]}'")
                    st.rerun()
                else:
                    st.error(f"Failed to update module-vector store link")
            
            # Vector store file management section
            st.subheader("Manage Vector Store Files")
            
            # Select vector store to manage files
            selected_store_for_files = st.selectbox(
                "Select vector store to manage files",
                [store.id for store in vector_stores.data],
                format_func=lambda x: next((store.name for store in vector_stores.data if store.id == x), x)
            )
            
            # Display files in the selected vector store
            try:
                files = client.vector_stores.files.list(vector_store_id=selected_store_for_files)
                if files.data:
                    file_data = []
                    for file in files.data:
                        file_data.append({
                            "File ID": file.id,
                            "Filename": file.attributes.get("filename", "Unknown"),
                            "Content Type": file.attributes.get("content_type", "Unknown"),
                            "Uploaded At": file.attributes.get("uploaded_at", "Unknown")
                        })
                    
                    files_df = pd.DataFrame(file_data)
                    st.dataframe(files_df)
                    
                    # File deletion
                    file_to_delete = st.selectbox("Select file to delete", [f["File ID"] for f in file_data])
                    if st.button("Delete Selected File"):
                        try:
                            client.vector_stores.files.delete(
                                vector_store_id=selected_store_for_files,
                                file_id=file_to_delete
                            )
                            st.success(f"File deleted successfully!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error deleting file: {str(e)}")
                else:
                    st.info("No files found in this vector store.")
            except Exception as e:
                st.error(f"Error fetching vector store files: {str(e)}")
            
            # File upload section
            st.subheader("Add Files to Vector Store")
            uploaded_files = st.file_uploader(
                "Upload files to add to the vector store",
                type=["txt", "pdf", "doc", "docx", "md"],
                accept_multiple_files=True,
                key="manage_vector_store_files"
            )
            
            if uploaded_files and st.button("Add Files to Vector Store"):
                with st.spinner("Processing files..."):
                    for uploaded_file in uploaded_files:
                        try:
                            # Create a temporary file to store the uploaded content
                            with tempfile.NamedTemporaryFile(delete=False, suffix=f".{uploaded_file.name.split('.')[-1]}") as temp_file:
                                temp_file.write(uploaded_file.getvalue())
                                temp_file_path = temp_file.name
                            
                            # Upload the file to get a file_id with purpose
                            file_id = client.files.create(
                                file=open(temp_file_path, 'rb'),
                                purpose='user_data'
                            ).id
                            
                            # Add the file_id to the vector store
                            client.vector_stores.files.create(
                                vector_store_id=selected_store_for_files,
                                file_id=file_id,
                                attributes={
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
        
        except Exception as e:
            st.error(f"Error fetching vector stores: {str(e)}")
    
    with tab3:
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