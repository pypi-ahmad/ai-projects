# route() decides *what* to call (tier, target, fallback order) without making
# any network calls; execute() then performs the calls in that order. Keeping
# decision and execution separate is what lets tests inject fake availability
# and provider functions without touching real providers.
from .router import route, load_tiers, AvailabilityFn
from .executor import execute, ProviderFn

__all__ = ["route", "load_tiers", "AvailabilityFn", "execute", "ProviderFn"]
