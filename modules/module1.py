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
    ALLOWED_CURRENCIES,
    DEFAULT_CURRENCY,
)


ALLOWED_OBJECTIVES: Set[str] = {GOAL_AW, GOAL_EN, GOAL_WT, GOAL_LG}

CURRENCY_SYMBOL_TO_CODE: Dict[str, str] = {"£": "GBP", "$": "USD", "€": "EUR"}

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
    currency: str = DEFAULT_CURRENCY
    campaign_duration_days: Optional[int] = None


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


def _parse_budget(raw_budget: Any) -> tuple[float, Optional[str]]:
    detected_currency: Optional[str] = None

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

        for symbol, code in CURRENCY_SYMBOL_TO_CODE.items():
            if value.startswith(symbol):
                detected_currency = code
                value = value[len(symbol):].strip()
                break

        if "," in value and "." in value:
            value = value.replace(",", "")
        elif "," in value and "." not in value:
            parts = value.split(",")
            if len(parts) == 2 and 1 <= len(parts[1]) <= 2:
                value = value.replace(",", ".")
            else:
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

    return numeric_budget, detected_currency


def _parse_currency(raw_currency: Any, fallback: Optional[str]) -> str:
    if raw_currency is None or (isinstance(raw_currency, str) and not raw_currency.strip()):
        return fallback if fallback is not None else DEFAULT_CURRENCY

    code = str(raw_currency).strip().upper()
    if code in ALLOWED_CURRENCIES:
        return code
    if code in CURRENCY_SYMBOL_TO_CODE:
        return CURRENCY_SYMBOL_TO_CODE[code]
    raise Module1ValidationError(
        f"Currency {raw_currency!r} is not supported. "
        f"Use one of: {sorted(ALLOWED_CURRENCIES)}."
    )


def _parse_duration(raw_duration: Any) -> Optional[int]:
    if raw_duration is None:
        return None
    if isinstance(raw_duration, bool):
        raise Module1ValidationError("Campaign duration must be a positive integer number of days.")
    if isinstance(raw_duration, (int, float)):
        if math.isnan(raw_duration) or math.isinf(raw_duration):
            raise Module1ValidationError("Campaign duration must be a finite positive integer.")
        d = int(raw_duration)
    else:
        value = str(raw_duration).strip()
        if not value:
            return None
        try:
            d = int(value)
        except ValueError:
            raise Module1ValidationError(
                "Campaign duration must be a positive integer number of days "
                "(for example: 30)."
            )
    if d <= 0:
        raise Module1ValidationError("Campaign duration must be greater than zero days.")
    return d


def _validate_budget(numeric_budget: float) -> None:
    if numeric_budget <= 1:
        raise Module1ValidationError(
            "Your total budget must be greater than 1 monetary unit."
        )


def run_module_1(
    raw_objectives: Sequence[str],
    raw_budget: Any,
    raw_currency: Any = None,
    raw_duration_days: Any = None,
) -> Module1Result:
    normalised_objectives = _normalise_objectives(raw_objectives)
    _validate_objectives(normalised_objectives)

    numeric_budget, detected_currency = _parse_budget(raw_budget)
    _validate_budget(numeric_budget)

    currency = _parse_currency(raw_currency, fallback=detected_currency)
    duration = _parse_duration(raw_duration_days)

    return Module1Result(
        selected_objectives=normalised_objectives,
        total_budget=numeric_budget,
        currency=currency,
        campaign_duration_days=duration,
    )


def complete_module1_and_advance(
    state: WizardState,
    raw_objectives: Sequence[str],
    raw_budget: Any,
    raw_currency: Any = None,
    raw_duration_days: Any = None,
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

    result = run_module_1(raw_objectives, raw_budget, raw_currency, raw_duration_days)

    state.complete_module1_and_advance(
        valid_goals=result.selected_objectives,
        total_budget=result.total_budget,
        currency=result.currency,
        campaign_duration_days=result.campaign_duration_days,
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

    raw_currency = input(
        f"Currency code (GBP/USD/EUR, leave blank to keep default {DEFAULT_CURRENCY}): "
    )

    raw_duration = input(
        "Campaign duration in days (leave blank if not known): "
    )

    try:
        complete_module1_and_advance(state, raw_objectives, raw_budget, raw_currency, raw_duration)
    except (Module1ValidationError, FlowStateError) as e:
        print("\nError:", str(e))
        return

    print("\nModule 1 completed and locked.")
    print("Current step:", state.current_step)
    print("Module 1 finalised:", state.module1_finalised)
    print("Snapshot valid_goals:", state.valid_goals)
    print("Snapshot total_budget:", state.total_budget)
    print("Snapshot currency:", state.currency)
    print("Snapshot campaign_duration_days:", state.campaign_duration_days)


if __name__ == "__main__":
    _present_module_1_cli()
