from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Set
import math
import re

# Import WizardState and goal codes from the root-level wizard_state module.
# The previous import referenced a non-existent ``core`` package which caused
# a ModuleNotFoundError. Importing from ``wizard_state`` fixes this.
from wizard_state import WizardState, GOAL_AW, GOAL_EN, GOAL_WT, GOAL_LG


# ============================================
# 1. Canonical goal codes and definitions
# ============================================

# Ensure allowed objective codes are compared in a normalised form
_GOAL_CONSTANTS = (GOAL_AW, GOAL_EN, GOAL_WT, GOAL_LG)
ALLOWED_OBJECTIVES: Set[str] = {str(g).strip().lower() for g in _GOAL_CONSTANTS}

OBJECTIVE_DEFINITIONS: List[Dict[str, str]] = [
    {
        "code": str(GOAL_AW).strip().lower(),
        "label": "Awareness",
        "description": "Reach more people and increase brand visibility.",
    },
    {
        "code": str(GOAL_EN).strip().lower(),
        "label": "Engagement",
        "description": "Encourage interactions such as likes, comments, and shares.",
    },
    {
        "code": str(GOAL_WT).strip().lower(),
        "label": "Website Traffic",
        "description": "Drive more visitors to your website or landing page.",
    },
    {
        "code": str(GOAL_LG).strip().lower(),
        "label": "Lead Generation",
        "description": "Collect contact details or sign ups from potential customers.",
    },
]


# ============================================
# 2. Errors and result structure
# ============================================

class Module1ValidationError(Exception):
    """
    Custom exception for all validation errors in Module 1.
    Messages are written in British English.
    """
    pass


class FlowStateError(Exception):
    """
    Raised when the wizard state is used in an invalid way,
    for example attempting to rerun Module 1 after it has been finalised.
    """
    pass


@dataclass
class Module1Result:
    """
    Normalised output of Module 1.

    Attributes
    ----------
    selected_objectives : List[str]
        Objective codes chosen by the user, each from:
        - 'aw' (Awareness)
        - 'en' (Engagement)
        - 'wt' (Website Traffic)
        - 'lg' (Lead Generation)

    total_budget : float
        Validated numeric budget (float), strictly greater than 1.
    """
    selected_objectives: List[str]
    total_budget: float


# ============================================
# 3. Core normalisation and validation helpers
# ============================================

def _normalise_objectives(raw_objectives: Sequence[str]) -> List[str]:
    """
    Normalise raw objective codes:
    - strip whitespace
    - convert to lower case
    - remove duplicates while preserving order

    Returns a list of objective codes.
    """
    seen: Set[str] = set()
    normalised: List[str] = []

    for item in raw_objectives:
        if item is None:
            continue
        code = str(item).strip().lower()
        if not code:
            continue
        if code not in seen:
            seen.add(code)
            normalised.append(code)

    return normalised


def _validate_objectives(selected_objectives: Sequence[str]) -> None:
    """
    Validate that:
    - at least one objective has been selected
    - all selected objectives are within the allowed set

    Raises Module1ValidationError on any problem.
    """
    if not selected_objectives:
        raise Module1ValidationError(
            "You must select at least one objective."
        )

    invalid = [obj for obj in selected_objectives if obj not in ALLOWED_OBJECTIVES]
    if invalid:
        # This should not normally happen if the UI restricts choices
        # but it protects the back end against unexpected input.
        raise Module1ValidationError(
            "One or more selected objectives are invalid."
        )


def _parse_budget(raw_budget: Any) -> float:
    """
    Convert a raw budget value into a float.

    Accepts:
    - string values such as '1200', '£1,200.50', ' 1500 ', 'USD 1,200', '1 200'
    - numeric values (int or float)

    The string parsing removes most non-numeric characters (except '.' and '-')
    to tolerate leading/trailing currency symbols and textual labels.

    Raises Module1ValidationError if the value cannot be parsed
    as a valid monetary amount.
    """
    # Allow direct numeric input
    if isinstance(raw_budget, (int, float)):
        numeric_budget = float(raw_budget)
    else:
        if raw_budget is None:
            raise Module1ValidationError(
                "Please enter your total budget as a valid monetary amount "
                "(for example: 1200 or £1,200.50)."
            )

        value = str(raw_budget).strip()

        if not value:
            raise Module1ValidationError(
                "Please enter your total budget as a valid monetary amount "
                "(for example: 1200 or £1,200.50)."
            )

        # Remove any characters except digits, '.' and '-' to tolerate
        # currency symbols and textual labels like 'USD' or 'GBP'.
        # This will remove commas and spaces used as thousand separators.
        cleaned = re.sub(r'[^\d\.\-]', '', value)

        if not cleaned or cleaned in {"-", ".", "-.", ".-"}:
            raise Module1ValidationError(
                "Please enter your total budget as a valid monetary amount "
                "(for example: 1200 or £1,200.50)."
            )

        # Prevent inputs with multiple decimal points which would raise a generic ValueError
        if cleaned.count('.') > 1:
            raise Module1ValidationError(
                "Please enter your total budget using a single decimal separator (for example: 1200.50)."
            )

        try:
            numeric_budget = float(cleaned)
        except ValueError:
            raise Module1ValidationError(
                "Please enter your total budget as a valid monetary amount "
                "(for example: 1200 or £1,200.50)."
            )

    # Basic numeric sanity checks
    if math.isnan(numeric_budget) or math.isinf(numeric_budget):
        raise Module1ValidationError(
            "Your total budget must be a valid finite number."
        )

    return numeric_budget


def _validate_budget(numeric_budget: float) -> None:
    """
    Validate that the numeric budget is strictly greater than 1.

    Raises Module1ValidationError if the budget is not acceptable.
    """
    if numeric_budget <= 1:
        raise Module1ValidationError(
            "Your total budget must be greater than 1 monetary unit."
        )


# ============================================
# 4. Public entry point for Module 1 (pure logic)
# ============================================

def run_module_1(
    raw_objectives: Sequence[str],
    raw_budget: Any,
) -> Module1Result:
    """
    Core logic of Module 1 (pure function, no state).
    """
    # 1) Normalise and validate objectives
    normalised_objectives = _normalise_objectives(raw_objectives)
    _validate_objectives(normalised_objectives)

    # 2) Parse and validate budget
    numeric_budget = _parse_budget(raw_budget)
    _validate_budget(numeric_budget)

    # 3) Return normalised, structured result
    return Module1Result(
        selected_objectives=normalised_objectives,
        total_budget=numeric_budget,
    )


# ============================================
# 5. Flow integration for transition to Module 2
# ============================================

def complete_module1_and_advance(
    state: WizardState,
    raw_objectives: Sequence[str],
    raw_budget: Any,
) -> WizardState:
    """
    Run Module 1, store a final snapshot in the global wizard state,
    and advance the flow to Module 2.

    This function is defensive about the shape of the state object and raises
    FlowStateError for flow-related issues rather than allowing AttributeError.
    """
    # Use getattr with sensible defaults to avoid AttributeError if state shape differs
    if getattr(state, "module1_finalised", False):
        raise FlowStateError(
            "Module 1 has already been finalised. "
            "Please reset the wizard if you need to start again."
        )

    current_step = getattr(state, "current_step", None)
    if current_step != 1:
        raise FlowStateError(
            "Module 1 can only be completed when the wizard is at step 1."
        )

    # Run pure Module 1 logic
    result = run_module_1(raw_objectives, raw_budget)

    # Save snapshot (mutate state in place)
    state.valid_goals = list(result.selected_objectives)
    state.total_budget = result.total_budget

    # Mark Module 1 as finalised
    state.module1_finalised = True

    # Move to step 2 (Module 2)
    state.current_step = 2

    return state


def example_module2_entry_guard(state: WizardState) -> None:
    """
    Example helper showing how Module 2 can enforce that Module 1
    has been completed before it runs.

    In real code, Module 2 main function would call this at the top.
    """
    if not getattr(state, "module1_finalised", False):
        raise FlowStateError(
            "You cannot enter Module 2 before completing Module 1."
        )
    if getattr(state, "current_step", 0) < 2:
        raise FlowStateError(
            "The current step is not set to Module 2 yet."
        )


# ============================================
# 6. Optional CLI runner for local testing only
# ============================================

def _present_module_1_cli() -> None:
    """
    Temporary CLI based interface to test Module 1 plus state transition.
    """
    state = WizardState()

    print("=== Module 1: Select Your Objectives and Total Budget ===\n")

    print("Available objectives:")
    for obj in OBJECTIVE_DEFINITIONS:
        print(f"  - {obj['code']} : {obj['label']}")
        print(f"      {obj['description']}")
    print()

    print("Please type the codes of the objectives you want, separated by commas.")
    print("For example: aw,en or aw,wt,lg\n")

    raw_codes = input("Your selected objectives: ")
    raw_objectives = [code for code in raw_codes.split(",")]

    raw_budget = input(
        "Please enter your total budget "
        "(for example: 1200 or £1,200.50): "
    )

    try:
        complete_module1_and_advance(state, raw_objectives, raw_budget)
    except (Module1ValidationError, FlowStateError) as e:
        print("\nError:", str(e))
        return

    print("\nModule 1 completed and locked.")
    print("Current step:", state.current_step)
    print("Module 1 finalised:", state.module1_finalised)
    print("Snapshot valid_goals:", state.valid_goals)
    print("Snapshot total_budget:", state.total_budget)


if __name__ == "__main__":
    _present_module_1_cli()
