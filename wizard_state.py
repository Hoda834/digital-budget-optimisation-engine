"""
Compatibility wrapper so that `import wizard_state` works
both locally and on Streamlit Cloud.

The real implementation lives in core/wizard_state.py
"""

from core.wizard_state import (
    WizardState,
    FlowStateError,
    GOAL_AW,
    GOAL_EN,
    GOAL_WT,
    GOAL_LG,
    ALLOWED_OBJECTIVES,
    ALLOWED_PLATFORMS,
)

__all__ = [
    "WizardState",
    "FlowStateError",
    "GOAL_AW",
    "GOAL_EN",
    "GOAL_WT",
    "GOAL_LG",
    "ALLOWED_OBJECTIVES",
    "ALLOWED_PLATFORMS",
]
