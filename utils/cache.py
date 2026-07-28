"""Caching utilities for the application"""
from typing import Any, Dict, Optional, Union

import streamlit as st

from utils.modules import find_module_by_index

def invalidate_modules_cache():
    """Invalidate the modules cache when data needs to be refreshed"""
    if "cached_modules_data" in st.session_state:
        del st.session_state.cached_modules_data

def get_cached_modules_data():
    """Get modules data from cache or fetch if not available"""
    from mongodb.connectors import get_modules_data
    return get_modules_data()  # Now uses internal caching


@st.cache_data(ttl=10)
def get_cached_module(module_id: Union[str, int]) -> Optional[Dict[str, Any]]:
    """Return one module document, looked up by its `index`.

    Defined once, here, and keyed by `module_id` deliberately. Every module page
    used to carry its own private copy of this lookup, and `st.cache_data` keys a
    function by (`__module__`, `__qualname__`, source text): page scripts all run
    as `__main__`, the copies were textually identical, and they took no arguments
    - so all three shared a single cache entry. Whichever module page rendered
    last filled it, and the next page to load then showed *that* module's title,
    description and `vector_store_id` under its own module number until the 10s
    TTL expired. Passing the module id in gives each module its own entry.
    """
    try:
        return find_module_by_index(get_cached_modules_data(), module_id)
    except Exception as e:
        st.error(f"Error loading module data: {str(e)}")
        return None
