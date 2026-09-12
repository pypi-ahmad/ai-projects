"""Package marker for `src.ui` -- the Streamlit front end. Holds no logic of
its own; must not import anything that isn't safe to run at Streamlit's
module-import time (see src/ui/app.py, which runs top-to-bottom on every
rerun).

Next: src/ui/app.py, the actual page.
"""
