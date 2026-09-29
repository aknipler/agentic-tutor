from datetime import datetime

from utils.pages import render_module_page

# The only things this page hard-codes: which module it is, matched against the
# `index` field in modules_live, and when it unlocks. Everything else is data.
render_module_page(module_id="9", release_date=datetime(2026, 9, 19, 23, 59))
