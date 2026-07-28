from typing import List, Dict, Any, Optional
from datetime import datetime
from pymongo import MongoClient
from pymongo.collection import Collection
import streamlit as st

class UserLogger:
    def __init__(self, db_name: Optional[str] = None):
        """
        Initialize the logger with MongoDB connection details from Streamlit secrets.

        Args:
            db_name (str, optional): Database to log to. Defaults to
                MONGODB_LOGS_DATABASE_NAME from secrets. Conversation logs live in
                their own database, separate from MONGODB_DATABASE_NAME, but the
                name is still configuration - it is never hard-coded here.
        """
        # Get MongoDB connection details from Streamlit secrets
        connection_string = st.secrets["MONGODB_CONNECTION_STRING"]
        if db_name is None:
            db_name = st.secrets["MONGODB_LOGS_DATABASE_NAME"]

        self.client = MongoClient(connection_string)
        self.db = self.client[db_name]
        self.conversations: Collection = self.db["user_conversations"]
        self.submissions: Collection = self.db["user_submissions"]
    
    def log_conversation(self, user_id: str, module: str, topic: str, messages: List[List[str]]) -> None:
        """
        Log messages for a user's conversation in a specific module and topic.
        Messages are accumulated into a single conversation entry per module/topic pair.
        
        Args:
            user_id (str): Unique identifier for the user
            module (str): Name of the module
            topic (str): Topic of the conversation
            messages (List[List[str]]): A list of message pairs [user_message, assistant_message]
        """
        # Find the existing conversation for this module/topic pair
        user_doc = self.conversations.find_one({"user_id": user_id})
        if user_doc:
            # Find the conversation entry for this module/topic
            conversation_entry = None
            for conv in user_doc.get("conversations", []):
                if conv.get("module") == module and conv.get("topic") == topic:
                    conversation_entry = conv
                    break
            
            if conversation_entry:
                # Update existing conversation
                self.conversations.update_one(
                    {
                        "user_id": user_id,
                        "conversations": {
                            "$elemMatch": {
                                "module": module,
                                "topic": topic
                            }
                        }
                    },
                    {
                        "$push": {
                            "conversations.$.conversation": {"$each": messages}
                        }
                    }
                )
            else:
                # Create new conversation entry
                self.conversations.update_one(
                    {"user_id": user_id},
                    {
                        "$push": {
                            "conversations": {
                                "module": module,
                                "topic": topic,
                                "conversation": messages,
                                "timestamp": datetime.utcnow()
                            }
                        }
                    }
                )
        else:
            # Create new user document with conversation
            self.conversations.insert_one({
                "user_id": user_id,
                "conversations": [{
                    "module": module,
                    "topic": topic,
                    "conversation": messages,
                    "timestamp": datetime.utcnow()
                }]
            })
    
    def log_submission(self, user_id: str, module: str, question: str, submission: str, grade: float) -> None:
        """
        Log a submission for a user.
        
        Args:
            user_id (str): Unique identifier for the user
            module (str): Name of the module
            question (str): The question that was answered
            submission (str): The user's submission
            grade (float): The grade received
        """
        submission_entry = {
            "module": module,
            "question": question,
            "submission": submission,
            "grade": grade,
            "timestamp": datetime.utcnow()
        }
        
        self.submissions.update_one(
            {"user_id": user_id},
            {"$push": {"submissions": submission_entry}},
            upsert=True
        )
    
    def get_conversation(self, user_id: str, module: str, topic: str) -> List[List[str]]:
        """Retrieve one conversation's message pairs for a module/topic pair.

        Projected server-side rather than pulling every conversation the student
        has ever had and filtering in Python: this runs on each module page load,
        and a student's full transcript across every topic grows without bound.

        Args:
            user_id (str): Unique identifier for the user
            module (str): The module's index, as a string
            topic (str): Canonical topic name

        Returns:
            List[List[str]]: [user_message, assistant_message] pairs, oldest first.
            Empty if this module/topic pair has no logged conversation.
        """
        doc = self.conversations.find_one(
            {
                "user_id": user_id,
                "conversations": {"$elemMatch": {"module": module, "topic": topic}}
            },
            {"conversations.$": 1}
        )
        if not doc:
            return []
        conversations = doc.get("conversations", [])
        return conversations[0].get("conversation", []) if conversations else []

    def get_user_conversations(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Retrieve all conversations for a user.
        
        Args:
            user_id (str): Unique identifier for the user
            
        Returns:
            List[Dict[str, Any]]: List of conversation entries
        """
        user_doc = self.conversations.find_one({"user_id": user_id})
        return user_doc.get("conversations", []) if user_doc else []
    
    def get_user_submissions(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Retrieve all submissions for a user.
        
        Args:
            user_id (str): Unique identifier for the user
            
        Returns:
            List[Dict[str, Any]]: List of submission entries
        """
        user_doc = self.submissions.find_one({"user_id": user_id})
        return user_doc.get("submissions", []) if user_doc else []
    
    def close(self) -> None:
        """Close the MongoDB connection."""
        self.client.close() 