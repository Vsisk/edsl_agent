from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class BranchWorkflowInput:
    request: Any
    generation_context: Any


SqlWorkflowInput = BranchWorkflowInput

__all__ = ["BranchWorkflowInput", "SqlWorkflowInput"]
