"""Helpers for locating module documents in the modules_live data.

Modules are identified by their `index` field — a 1-based integer set on import
by `scripts/load_week_json.py`. Titles are *data*, not keys: they come from the
lecturers' source files and change with the subject, so nothing in the code
should match on them. Keying on `index` is also what `user_progress` already
does (it stores progress under `str(module["index"])`).

These are pure functions: no Streamlit, no database, so they can be unit-tested
directly and reused by both pages and handlers without circular imports.
"""
from typing import Any, Dict, List, Optional, Union


def get_modules_list(modules_data: Any) -> List[Dict[str, Any]]:
    """Normalise the modules payload to a plain list of module documents.

    `get_modules_data()` returns {"modules": [...]}, but callers sometimes hold a
    bare list. Accept either, and drop anything that isn't a dict.
    """
    if not modules_data:
        return []

    modules = modules_data.get("modules", []) if isinstance(modules_data, dict) else modules_data
    if not isinstance(modules, list):
        return []

    return [module for module in modules if isinstance(module, dict)]


def module_index(module: Dict[str, Any]) -> Optional[int]:
    """Return a module's `index` as an int, or None if it is missing/malformed."""
    try:
        return int(module.get("index"))
    except (TypeError, ValueError):
        return None


def find_module_by_index(modules_data: Any, module_id: Union[str, int]) -> Optional[Dict[str, Any]]:
    """Find the module whose `index` matches `module_id`, or None if absent.

    Returning None is a normal outcome, not an error: during the staged rollout
    only the loaded weeks exist, so a page for a not-yet-released module will
    legitimately find nothing and should say so.
    """
    try:
        target = int(module_id)
    except (TypeError, ValueError):
        return None

    for module in get_modules_list(modules_data):
        if module_index(module) == target:
            return module
    return None


def sort_modules_by_index(modules_data: Any) -> List[Dict[str, Any]]:
    """Return the modules ordered by `index`, with malformed ones last."""
    modules = get_modules_list(modules_data)
    return sorted(
        modules,
        # (1, 0) sorts entries with no usable index after everything else.
        key=lambda module: (0, module_index(module)) if module_index(module) is not None else (1, 0),
    )
