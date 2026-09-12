"""Web chunk record: a fetched page's text, parallel to retrieve/records.py's
RetrievalResult but tagged [W#] instead of [S#]. See docs/CITATIONS.md.
"""

from dataclasses import dataclass


@dataclass
class WebChunk:
    url: str
    title: str
    text: str
