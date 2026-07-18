"""Configuration settings for the tutor system"""

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
    MODEL_NAME = "gpt-4o"
    CHAT_HISTORY_PREFIX = "messages_module_"
    MAX_CHAT_HISTORY = 50 