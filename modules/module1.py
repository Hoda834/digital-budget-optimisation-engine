from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Set
import math

from core.wizard_state import (
    WizardState,
    GOAL_AW,
    GOAL_EN,
    GOAL_WT,
    GOAL_LG,
    FlowStateError,
)


ALLOWED_OBJECTIVES: Set[str] = {GOAL_AW, GOAL_EN, GOAL_WT, GOAL_LG}

OBJECTIVE_DEFINITIONS: List[Dict[str, str]] = [
    {
        "code": GOAL_AW,
        "label": "Awareness",
        "description": "Reach more people and increase brand visibility.",
    },
    {
        "code": GOAL_EN,
        "label": "Engagement",
        "description": "Encourage interactions such as likes, comments, and shares.",
    },
    {
        "code": GOAL_WT,
        "label": "Website Traffic",
        "description": "Drive more visitors to your website or landing page.",
    },
    {
        "code": GOAL_LG,
        "label": "Lead Generation",
        "description": "Collect contact details or sign ups from potential customers.",
    },
]


class Module1ValidationError(Exception):
    pass


@dataclass
class Module1Result:
    selected_objectives: List[str]
    total_budget: float


def _normalise_objectives(raw_objectives: Sequence[str]) -> List[str]:
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
    if not selected_objectives:
        raise Module1ValidationError(
            "You must select at least one objective."
        )

    invalid = [obj for obj in selected_objectives if obj not in ALLOWED_OBJECTIVES]
    if invalid:
        raise Module1ValidationError(
            "One or more selected objectives are invalid."
        )


def _parse_budget(raw_budget: Any) -> float:
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

        for symbol in ("£", "$", "€"):
            if value.startswith(symbol):
                value = value[len(symbol):].strip()
                break

        value = value.replace(",", "")

        try:
            numeric_budget = float(value)
        except ValueError:
            raise Module1ValidationError(
                "Please enter your total budget as a valid monetary amount "
                "(for example: 1200 or £1,200.50)."
            )

    if math.isnan(numeric_budget) or math.isinf(numeric_budget):
        raise Module1ValidationError(
            "Your total budget must be a valid finite number."
        )

    return numeric_budget


def _validate_budget(numeric_budget: float) -> None:
    if numeric_budget <= 1:
        raise Module1ValidationError(
            "Your total budget must be greater than 1 monetary unit."
        )


def run_module_1(
    raw_objectives: Sequence[str],
    raw_budget: Any,
) -> Module1Result:
    normalised_objectives = _normalise_objectives(raw_objectives)
    _validate_objectives(normalised_objectives)

    numeric_budget = _parse_budget(raw_budget)
    _validate_budget(numeric_budget)

    return Module1Result(
        selected_objectives=normalised_objectives,
        total_budget=numeric_budget,
    )


def complete_module1_and_advance(
    state: WizardState,
    raw_objectives: Sequence[str],
    raw_budget: Any,
) -> WizardState:
    if state.module1_finalised:
        raise FlowStateError(
            "Module 1 has already been finalised. "
            "Please reset the wizard if you need to start again."
        )

    if state.current_step != 1:
        raise FlowStateError(
            "Module 1 can only be completed when the wizard is at step 1."
        )

    result = run_module_1(raw_objectives, raw_budget)

    state.complete_module1_and_advance(
        valid_goals=result.selected_objectives,
        total_budget=result.total_budget,
    )

    return state


def example_module2_entry_guard(state: WizardState) -> None:
    if not state.module1_finalised:
        raise FlowStateError(
            "You cannot enter Module 2 before completing Module 1."
        )
    if state.current_step < 2:
        raise FlowStateError(
            "The current step is not set to Module 2 yet."
        )


def _present_module_1_cli() -> None:
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
