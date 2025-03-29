"""UI components for the tutor system"""
import streamlit as st
from typing import List, Dict, Any, Optional
from ..models.chat import ChatMessage
from ..handlers.competency import get_user_progress

def render_sidebar(module_title: str) -> None:
    """Render the sidebar with navigation and settings"""
    with st.sidebar:
        st.header("Navigation")
        st.page_link("pages/1_Your_Progress.py", label="Back to Progress")
        
        st.header("Current Module")
        st.write(f"Module: {module_title}")
        
        st.markdown("---")
        st.header("Debug Settings")
        debug_mode = st.toggle("Enable Debug Mode", key="debug_mode")
        if debug_mode:
            st.info("Debug mode is enabled. You'll see detailed information about the chat history and API calls.")
        
        st.markdown("---")
        st.header("Tips for Learning")
        st.info("""
        **Socratic Method Tips:**
        - Try to explain concepts in your own words
        - When stuck, ask specific questions
        - Connect new concepts to what you already know
        - Don't be afraid to make mistakes - they're part of learning!
        """)

def render_chat_history(chat_history: List[Dict[str, Any]]) -> None:
    """Render the chat history with proper message formatting"""
    for message in chat_history:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

def render_progress_summary(progress_summary: Optional[str]) -> None:
    """Render the progress summary with proper formatting"""
    if progress_summary:
        with st.expander("📊 Your Progress", expanded=False):
            st.markdown(progress_summary)
    else:
        st.warning("Unable to load progress data. Please try refreshing the page.") 