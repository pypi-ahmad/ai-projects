"""Concrete LLM provider implementations behind the shared Provider protocol in base.py.
Each module here exposes a module-level SPEC (a ProviderSpec); registry.py collects them
into the PROVIDERS mapping callers actually use -- start there, not with an individual
provider module.
"""
