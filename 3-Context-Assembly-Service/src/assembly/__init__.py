# Public exports for the assembly package. Implementation lives in packer.py;
# __main__.py provides the `python -m src.assembly` CLI (not re-exported here).
from src.assembly.packer import BudgetReport, FamilyStat, PackResult, pack

__all__ = ["BudgetReport", "FamilyStat", "PackResult", "pack"]
