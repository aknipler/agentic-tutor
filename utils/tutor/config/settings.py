"""Configuration settings for the tutor system"""

# Competency level indicators
COMPETENCY_LEVELS = {
    0: "🔴",  # Not started
    1: "🟠",  # In progress
    2: "✅"   # Completed
}

# Module titles mapping
MODULE_TITLES = {
    "1": "Introduction to Chemical Engineering",
    "2": "Schematics",
    "3": "Small Kit: Sensors and Valves",
    "4": "Medium Kit: Tanks, Separators, Heat Exchangers and Boilers",
    "5": "Large Kit: Reactors and Reaction Kinetics",
    "6": "Large Kit: Thermodynamic Cycles"
}

class TutorConfig:
    """Configuration class for the tutor system"""
    MODEL_NAME = "gpt-4o"
    CHAT_HISTORY_PREFIX = "messages_module_"
    MAX_CHAT_HISTORY = 50 