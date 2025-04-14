"""Caching utilities for the application"""
import streamlit as st

def invalidate_modules_cache():
    """Invalidate the modules cache when data needs to be refreshed"""
    if "cached_modules_data" in st.session_state:
        del st.session_state.cached_modules_data 

def get_cached_modules_data():
    """Get modules data from cache or fetch if not available"""
    from mongodb.connectors import get_modules_data
    return get_modules_data()  # Now uses internal caching 