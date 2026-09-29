from utils.pages import render_module_page

# The only thing this page hard-codes: which module it is, matched against the
# `index` field in modules_live. Title, topics and questions come from the data.
render_module_page(module_id="1")
