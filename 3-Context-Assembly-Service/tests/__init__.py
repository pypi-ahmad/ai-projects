# Marks `tests` as a regular package. Not required for pytest discovery itself
# (pythonpath = ["."] in pyproject.toml handles that); present so test files can
# be imported as `tests.*` if another module ever needs to reference one directly.
