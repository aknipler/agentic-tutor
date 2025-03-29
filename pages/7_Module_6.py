# Load module data
@st.cache_data(ttl=10)
def load_module_data():
    """Load module information from MongoDB"""
    try:
        data = get_modules_data()
        if "modules" in data and isinstance(data["modules"], list):
            # Find the module with the specific title
            target_title = "Thermodynamic Cycles"
            for module in data["modules"]:
                if module.get("title") == target_title:
                    return module
        return None
    except Exception as e:
        st.error(f"Error loading module data: {str(e)}")
        return None 