from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
import math

from core.wizard_state import (
    WizardState,
    GOAL_AW,
    GOAL_EN,
    GOAL_WT,
    GOAL_LG,
    ALLOWED_CURRENCIES,
    DEFAULT_CURRENCY,
    FlowStateError,
)


ALLOWED_OBJECTIVES: Set[str] = {GOAL_AW, GOAL_EN, GOAL_WT, GOAL_LG}

# Currency symbol → ISO code.  Used to auto-detect currency from budget strings like "£1,200".
CURRENCY_SYMBOL_TO_CODE: Dict[str, str] = {"£": "GBP", "$": "USD", "€": "EUR"}

# Hard ceiling on total budget. 1e9 covers any plausible single-campaign budget
# in major currencies; values above this are almost certainly a typo or unit error.
MAX_REASONABLE_BUDGET = 1e9

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
    # £ value the user assigns to one unit of each goal's KPI.
    # e.g. {"lg": 100.0, "aw": 0.001} = a lead is worth £100, an impression £0.001.
    goal_value_per_unit: Dict[str, float] = field(default_factory=dict)


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


def _parse_numeric_string(value: str) -> float:
    """Parse a budget string with EU-style decimal/thousands support.

    Examples:
        "1200"      → 1200.0
        "1,200"     → 1200.0  (comma = thousands separator, 3 digits after)
        "1,50"      → 1.5     (comma = decimal separator, 2 digits after)
        "1,200.50"  → 1200.50 (comma = thousands, period = decimal)
        "1.200,50"  → 1200.50 (period = thousands, comma = decimal)
    """
    # Standard form (no ambiguity)
    try:
        return float(value)
    except ValueError:
        pass

    # Both comma and period present
    if "," in value and "." in value:
        last_comma = value.rfind(",")
        last_period = value.rfind(".")
        if last_comma > last_period:
            # "1.234,56" — period is thousands, comma is decimal
            cleaned = value.replace(".", "").replace(",", ".")
        else:
            # "1,234.56" — comma is thousands, period is decimal
            cleaned = value.replace(",", "")
        return float(cleaned)

    # Only comma
    if "," in value:
        after = value.rsplit(",", 1)[1]
        if len(after) <= 2:
            # "1,50" or "1,5" — comma is decimal separator
            cleaned = value.replace(",", ".")
        else:
            # "1,200" or "1,200,000" — comma is thousands separator
            cleaned = value.replace(",", "")
        return float(cleaned)

    raise ValueError(f"Cannot parse numeric value: {value!r}")


def _parse_budget(raw_budget: Any) -> Tuple[float, Optional[str]]:
    """Parse budget input.  Returns (numeric_value, detected_currency_code_or_None)."""
    if isinstance(raw_budget, (int, float)):
        numeric = float(raw_budget)
        if math.isnan(numeric) or math.isinf(numeric):
            raise Module1ValidationError(
                "Your total budget must be a valid finite number."
            )
        return numeric, None

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

    # Strip leading currency symbol and remember which one
    detected_currency: Optional[str] = None
    for symbol, code in CURRENCY_SYMBOL_TO_CODE.items():
        if value.startswith(symbol):
            value = value[len(symbol):].strip()
            detected_currency = code
            break

    try:
        numeric = _parse_numeric_string(value)
    except ValueError:
        raise Module1ValidationError(
            "Please enter your total budget as a valid monetary amount "
            "(for example: 1200 or £1,200.50)."
        )

    if math.isnan(numeric) or math.isinf(numeric):
        raise Module1ValidationError(
            "Your total budget must be a valid finite number."
        )

    return numeric, detected_currency


def _parse_currency(raw_currency: Any, fallback: Optional[str] = None) -> str:
    """Resolve a currency code from user input.

    Accepts ISO codes (GBP, USD, EUR) or currency symbols (£, $, €).
    Falls back to *fallback* (e.g. auto-detected from the budget string) or
    DEFAULT_CURRENCY if both are absent or unrecognised.
    """
    if raw_currency is None:
        return fallback or DEFAULT_CURRENCY

    token = str(raw_currency).strip().upper()
    if token in ALLOWED_CURRENCIES:
        return token
    # Accept the symbol form too (£ → GBP etc.)
    for symbol, code in CURRENCY_SYMBOL_TO_CODE.items():
        if token == symbol:
            return code
    # Unknown input → fall back silently
    return fallback or DEFAULT_CURRENCY


def _parse_duration(raw_duration: Any) -> Optional[int]:
    """Parse campaign duration in days.  Returns None if input is absent or invalid."""
    if raw_duration is None:
        return None
    try:
        d = int(float(str(raw_duration).strip()))
    except (TypeError, ValueError):
        return None
    return d if d > 0 else None


def _parse_goal_values(
    raw_values: Any,
    valid_objectives: Sequence[str],
) -> Dict[str, float]:
    """Parse a {goal_code: £-value-per-unit} mapping.

    Keys not in *valid_objectives* are dropped.  Values must be positive
    finite numbers (£ per one unit of the goal's KPI — e.g. £100 per lead,
    £0.001 per impression).
    """
    if raw_values is None:
        return {}
    if not isinstance(raw_values, dict):
        raise Module1ValidationError(
            "goal_value_per_unit must be a dict like {'lg': 100.0, 'aw': 0.001}."
        )

    allowed = {str(g).strip().lower() for g in valid_objectives}
    cleaned: Dict[str, float] = {}
    for g, v in raw_values.items():
        gk = str(g).strip().lower()
        if gk not in allowed:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            raise Module1ValidationError(
                f"goal_value_per_unit[{gk!r}] must be numeric, got {v!r}."
            )
        if math.isnan(fv) or math.isinf(fv):
            raise Module1ValidationError(
                f"goal_value_per_unit[{gk!r}] must be finite."
            )
        if fv < 0:
            raise Module1ValidationError(
                f"goal_value_per_unit[{gk!r}] must be non-negative, got {fv}."
            )
        if fv > 0:
            cleaned[gk] = fv
    return cleaned


def _validate_budget(numeric_budget: float) -> None:
    if numeric_budget <= 1:
        raise Module1ValidationError(
            "Your total budget must be greater than 1 monetary unit."
        )
    if numeric_budget > MAX_REASONABLE_BUDGET:
        raise Module1ValidationError(
            f"Your total budget {numeric_budget:.0f} exceeds the sanity ceiling "
            f"({MAX_REASONABLE_BUDGET:.0f}). Please check the value — this is "
            f"likely a typo or a unit/scale error."
        )


def run_module_1(
    raw_objectives: Sequence[str],
    raw_budget: Any,
    raw_currency: Any = None,
    raw_duration_days: Any = None,
    raw_goal_values: Any = None,
) -> Module1Result:
    normalised_objectives = _normalise_objectives(raw_objectives)
    _validate_objectives(normalised_objectives)

    numeric_budget, detected_currency = _parse_budget(raw_budget)
    _validate_budget(numeric_budget)

    currency = _parse_currency(raw_currency, fallback=detected_currency)
    campaign_duration_days = _parse_duration(raw_duration_days)
    goal_values = _parse_goal_values(raw_goal_values, normalised_objectives)

    return Module1Result(
        selected_objectives=normalised_objectives,
        total_budget=numeric_budget,
        currency=currency,
        campaign_duration_days=campaign_duration_days,
        goal_value_per_unit=goal_values,
    )


def complete_module1_and_advance(
    state: WizardState,
    raw_objectives: Sequence[str],
    raw_budget: Any,
    raw_currency: Any = None,
    raw_duration_days: Any = None,
    raw_goal_values: Any = None,
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

    result = run_module_1(
        raw_objectives, raw_budget, raw_currency, raw_duration_days, raw_goal_values
    )

    state.complete_module1_and_advance(
        valid_goals=result.selected_objectives,
        total_budget=result.total_budget,
        currency=result.currency,
        campaign_duration_days=result.campaign_duration_days,
        goal_value_per_unit=result.goal_value_per_unit,
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
        "Currency code (GBP/USD/EUR, or leave blank to auto-detect from budget symbol): "
    ).strip() or None

    raw_duration = input(
        "Campaign duration in days (positive integer, or leave blank): "
    ).strip() or None

    try:
        complete_module1_and_advance(
            state, raw_objectives, raw_budget, raw_currency, raw_duration
        )
    except (Module1ValidationError, FlowStateError) as e:
        print("\nError:", str(e))
        return

    print("\nModule 1 completed and locked.")
    print("Current step:", state.current_step)
    print("Module 1 finalised:", state.module1_finalised)
    print("Snapshot valid_goals:", state.valid_goals)
    print("Snapshot total_budget:", state.total_budget)
    print("Currency:", state.currency)
    print("Campaign duration:", state.campaign_duration_days)


if __name__ == "__main__":
    _present_module_1_cli()
