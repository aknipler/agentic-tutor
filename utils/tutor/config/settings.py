"""Configuration settings for the tutor system"""

import streamlit as st

# Competency level indicators
COMPETENCY_LEVELS = {
    0: "🔴",  # Not started
    1: "🟠",  # In progress
    2: "✅"   # Completed
}

# NOTE: there is deliberately no MODULE_TITLES mapping here. Modules are looked
# up by their `index` field (see utils/modules.py) and their titles are read from
# the module documents themselves, so changing the subject or adding a week needs
# no code change.

class TutorConfig:
    """Configuration class for the tutor system"""
    MODEL_NAME = st.secrets.get("MODULE_TUTOR_MODEL", "")
    CHAT_HISTORY_PREFIX = "messages_module_"
    MAX_CHAT_HISTORY = 50
    # gpt-5-mini is a reasoning model: it spends output-token budget on hidden
    # reasoning before writing the visible reply, billed the same as visible
    # output. Left uncapped, it can spend that whole budget reasoning and
    # return no visible text at all. Effort "low" plus a generous but explicit
    # cap keeps cost predictable and guarantees room for the actual reply.
    REASONING_EFFORT = st.secrets.get("MODULE_TUTOR_REASONING_EFFORT", "low")
    # Measured against the real tutor.md prompt: a normal Socratic hint reply
    # uses ~700 output tokens, but Full Detailed Answer Mode already hit 1811
    # on a modest one-equation example - 4000 leaves real margin for a meatier
    # full worked solution (e.g. a multi-step ANOVA table) without truncating.
    MAX_OUTPUT_TOKENS = int(st.secrets.get("MODULE_TUTOR_MAX_OUTPUT_TOKENS", 4000)) 