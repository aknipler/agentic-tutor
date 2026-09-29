"""Shared page plumbing: the body of every module page, and finding the assessor page.

Module pages are all the same page with a different module number and unlock
date, so the page files under pages/ only call `render_module_page`. Adding a
module is copying one of them and changing those two values.
"""
from datetime import datetime
from pathlib import Path
from typing import Optional

import streamlit as st

from utils.cache import get_cached_module

_PAGES_DIR = Path(__file__).resolve().parent.parent / "pages"


def render_module_page(module_id: str, release_date: Optional[datetime] = None) -> None:
    """Render the tutor page for one module, keyed by its `index`.

    `release_date`, if given, keeps the module locked until that local date/time.
    """
    # Imported here, not at the top: utils.tutor imports this module for
    # `assessor_page`, so a top-level import would be circular.
    from utils.tutor import render_tutor_interface

    if not st.session_state.get("logged_in"):
        st.warning("Please login from the Home page to access the module.")
        st.stop()

    # Cached in utils/cache.py and keyed by module_id - a per-page copy of this
    # lookup collides with the other module pages' copies in Streamlit's cache
    # and serves them each other's module document.
    module_data = get_cached_module(module_id)
    if not module_data:
        st.info(
            f"Module {module_id} isn't available yet. It will appear here once the "
            "module has been loaded into the database with "
            "`scripts/load_week_json.py --commit`."
        )
        return

    st.sidebar.info(f"Logged in as: {st.session_state.user_id}")

    if release_date and datetime.now() <= release_date:
        st.info(f"Module {module_id} will unlock on {release_date:%B %d, %Y at %I:%M%p}.")
        return

    render_tutor_interface(
        module_id=module_id,
        module_title=module_data.get("title", f"Module {module_id}"),
        module_description=module_data.get("description", ""),
        topics=module_data.get("topics", []),
        vector_store_id=module_data.get("vector_store_id"),
    )


def assessor_page() -> str:
    """Path of the assessor page, for `st.switch_page`.

    Looked up rather than written out: the file's numeric prefix changes every
    time a module page is added ahead of it in the sidebar, and a hard-coded
    "pages/8_Assessor.py" outlived exactly such a rename.
    """
    matches = sorted(_PAGES_DIR.glob("*_Assessor.py"))
    if not matches:
        raise FileNotFoundError(f"No *_Assessor.py page in {_PAGES_DIR}")
    return f"pages/{matches[0].name}"
