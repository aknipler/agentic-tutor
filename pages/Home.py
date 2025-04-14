import streamlit as st
from utils.cache import get_cached_modules_data

def initialize_session():
    """Initialize session state with required data"""
    if "cached_modules_data" not in st.session_state:
        # Pre-fetch modules data at session start
        get_cached_modules_data()

# Initialize session
initialize_session()

# Rest of your Home page code... 