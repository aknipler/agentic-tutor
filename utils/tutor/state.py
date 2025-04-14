"""State management for the tutor system"""
from typing import Optional, Dict, Any, List
import streamlit as st
from datetime import datetime

class TutorState:
    """Manages the state of the tutor system"""
    
    @staticmethod
    def _get_message_key(module: str) -> str:
        """Get the standardized message key for a module"""
        return f"messages_module_{module}"
    
    @staticmethod
    def get_chat_history(module: str) -> List[Dict[str, Any]]:
        """Get chat history for a module"""
        key = TutorState._get_message_key(module)
        return st.session_state.get(key, [])
    
    @staticmethod
    def get_chat_history_for_ui(module: str) -> List[Dict[str, Any]]:
        """Get complete chat history for UI display without any cutoff"""
        key = TutorState._get_message_key(module)
        return st.session_state.get(key, [])
    
    @staticmethod
    def add_message(module: str, message: Dict[str, Any]) -> None:
        """Add a message to chat history"""
        key = TutorState._get_message_key(module)
        if key not in st.session_state:
            st.session_state[key] = []
        st.session_state[key].append(message)
        
        # Limit history size
        if len(st.session_state[key]) > 50:  # MAX_CHAT_HISTORY
            st.session_state[key] = st.session_state[key][-50:]
            
        # Synchronize with old key if it exists
        old_key = f"chat_history_{module}"
        if old_key in st.session_state:
            st.session_state[old_key] = st.session_state[key]
    
    @staticmethod
    def get_current_topic() -> Dict[str, Any]:
        """Get current topic"""
        return st.session_state.get("current_topic", {})
    
    @staticmethod
    def set_current_topic(topic: Dict[str, Any]) -> None:
        """Set current topic"""
        st.session_state["current_topic"] = topic
    
    @staticmethod
    def get_transition_state(module: str) -> bool:
        """Get transition state for a module"""
        return st.session_state.get(f"topic_transition_lock_{module}", False)
    
    @staticmethod
    def set_transition_state(module: str, state: bool) -> None:
        """Set transition state for a module"""
        st.session_state[f"topic_transition_lock_{module}"] = state
    
    @staticmethod
    def get_in_transition() -> bool:
        """Get global transition state"""
        return st.session_state.get("in_topic_transition", False)
    
    @staticmethod
    def set_in_transition(state: bool) -> None:
        """Set global transition state"""
        st.session_state["in_topic_transition"] = state
        if state:
            st.session_state["topic_transition_time"] = datetime.now().timestamp()
    
    @staticmethod
    def set_topic_cutoff_index(module: str) -> None:
        """Set the cutoff index for the new topic"""
        key = TutorState._get_message_key(module)
        topic_cutoff_key = f"topic_cutoff_index_{module}"
        # Store the current length of messages as the cutoff point
        cutoff_index = len(st.session_state.get(key, []))
        st.session_state[topic_cutoff_key] = cutoff_index
        print(f"[Topic Cutoff] Set cutoff index for module {module} to {cutoff_index}")
    
    @staticmethod
    def get_topic_cutoff_index(module: str) -> int:
        """Get the cutoff index for the current topic"""
        topic_cutoff_key = f"topic_cutoff_index_{module}"
        cutoff_index = st.session_state.get(topic_cutoff_key, 0)
        print(f"[Topic Cutoff] Retrieved cutoff index for module {module}: {cutoff_index}")
        return cutoff_index
    
    @staticmethod
    def get_conversation_context(module: str, topic: str) -> List[Dict[str, Any]]:
        """Get conversation context for API calls (with cutoff and limit)"""
        chat_history = TutorState.get_chat_history(module)
        current_topic = TutorState.get_current_topic()
        current_topic_name = current_topic.get("name", "")
        
        # If no topic is specified but we have a current topic, use that
        if not topic and current_topic_name:
            topic = current_topic_name
            
        # Get the cutoff index for the current topic
        cutoff_index = TutorState.get_topic_cutoff_index(module)
        
        # Only consider messages from the current topic (after cutoff)
        current_topic_history = chat_history[cutoff_index:]
        
        print(f"[Conversation Context] Module: {module}, Topic: {topic}")
        print(f"[Conversation Context] Total messages: {len(chat_history)}, Cutoff index: {cutoff_index}")
        print(f"[Conversation Context] Messages after cutoff: {len(current_topic_history)}")
        
        # Get the last 5 messages from current topic for API context
        context_messages = []
        for msg in current_topic_history[-5:]:
            # If message has no topic but we're in a topic context, add the current topic
            if not msg.get("topic_name") and topic:
                msg = msg.copy()  # Create a copy to avoid modifying the original
                msg["topic_name"] = topic
            context_messages.append(msg)
            
        print(f"[Conversation Context] Returning {len(context_messages)} messages for context")
        return context_messages
    
    @staticmethod
    def clear_topic_context(module: str, topic: str) -> None:
        """Clear context for a specific topic"""
        context_key = f"conversation_context_{module}_{topic}"
        if context_key in st.session_state:
            del st.session_state[context_key] 