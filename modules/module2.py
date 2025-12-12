from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from core.wizard_state import WizardState, ALLOWED_PLATFORMS


PLATFORMS = ("fb", "ig", "li", "yt")


@dataclass
class PlatformPriority:
    selected: bool = False
    priority_1: Optional[str] = None
    priority_2: Optional[str] = None


def initialise_module2_state(state: WizardState) -> None:
    if not state.module1_finalised:
        raise ValueError("Module 1 has not been finalised, cannot enter Module 2.")
    for p in PLATFORMS:
        if p not in state.platform_priorities:
            state.platform_priorities[p] = PlatformPriority()


def set_module2_inputs(
    state: WizardState,
    selected_platforms: List[str],
    priorities_input: Dict[str, Dict[str, Optional[str]]],
) -> None:
    if not state.module1_finalised:
        raise ValueError("Module 1 must be finalised before setting Module 2 inputs.")

    initialise_module2_state(state)

    selected_set = set(selected_platforms)

    unknown_platforms = selected_set - set(PLATFORMS)
    if unknown_platforms:
        raise ValueError(f"Unknown platform codes in selection: {unknown_platforms}")

    invalid_platforms = selected_set - ALLOWED_PLATFORMS
    if invalid_platforms:
        raise ValueError(
            f"Invalid platform codes according to WizardState: {invalid_platforms}"
        )

    for p in PLATFORMS:
        platform_state: PlatformPriority = state.platform_priorities[p]
        platform_state.selected = p in selected_set

        if p not in selected_set:
            platform_state.priority_1 = None
            platform_state.priority_2 = None

    for p, prio_dict in priorities_input.items():
        if p not in PLATFORMS:
            raise ValueError(f"Unknown platform in priorities_input: {p}")

        platform_state = state.platform_priorities[p]

        if not platform_state.selected:
            continue

        p1 = prio_dict.get("priority_1")
        p2 = prio_dict.get("priority_2")

        platform_state.priority_1 = p1
        platform_state.priority_2 = p2


def validate_module2(state: WizardState) -> None:
    if not state.module1_finalised:
        raise ValueError("Module 1 must be finalised before validating Module 2.")

    if not state.valid_goals:
        raise ValueError("No valid goals from Module 1. Please restart the wizard.")

    selected_platforms = [
        p
        for p in PLATFORMS
        if isinstance(state.platform_priorities.get(p), PlatformPriority)
        and state.platform_priorities[p].selected
    ]
    if len(selected_platforms) == 0:
        raise ValueError("At least one platform must be selected in Module 2.")

    valid_goals_set = set(state.valid_goals)

    for p in selected_platforms:
        prio: PlatformPriority = state.platform_priorities[p]
        p1 = prio.priority_1
        p2 = prio.priority_2

        if p1 is None and p2 is not None:
            raise ValueError(
                f"On platform '{p}', you cannot set Priority 2 without Priority 1."
            )

        if p1 is not None and p2 is not None and p1 == p2:
            raise ValueError(
                f"On platform '{p}', Priority 1 and Priority 2 must be different."
            )

        if p1 is not None and p1 not in valid_goals_set:
            raise ValueError(
                f"On platform '{p}', Priority 1 goal '{p1}' is not in valid goals "
                f"from Module 1: {state.valid_goals!r}"
            )

        if p2 is not None and p2 not in valid_goals_set:
            raise ValueError(
                f"On platform '{p}', Priority 2 goal '{p2}' is not in valid goals "
                f"from Module 1: {state.valid_goals!r}"
            )

        if len(valid_goals_set) == 1 and p2 is not None:
            raise ValueError(
                f"On platform '{p}', you cannot set Priority 2 when there is only "
                f"one valid goal in Module 1."
            )


def compute_priority_ranks(state: WizardState) -> None:
    if not state.valid_goals:
        raise ValueError("Cannot compute ranks, no valid goals in state.")

    valid_goals = list(state.valid_goals)
    state.priority_rank = {}

    for p in PLATFORMS:
        prio = state.platform_priorities.get(p)
        if not isinstance(prio, PlatformPriority) or not prio.selected:
            state.priority_rank[p] = {}
            continue

        p1 = prio.priority_1
        p2 = prio.priority_2

        ranks_for_p: Dict[str, int] = {}

        if p1 is None and p2 is None:
            for g in valid_goals:
                ranks_for_p[g] = 1
        else:
            for g in valid_goals:
                if g == p1:
                    ranks_for_p[g] = 1
                elif p2 is not None and g == p2:
                    ranks_for_p[g] = 2
                else:
                    ranks_for_p[g] = 3

        state.priority_rank[p] = ranks_for_p


def compute_platform_weights(state: WizardState) -> None:
    if not state.valid_goals:
        raise ValueError("Cannot compute weights, no valid goals in state.")

    valid_goals = list(state.valid_goals)
    state.platform_weights = {}

    for p in PLATFORMS:
        ranks_for_p = state.priority_rank.get(p, {})

        prio = state.platform_priorities.get(p)
        if not isinstance(prio, PlatformPriority) or not prio.selected or not ranks_for_p:
            state.platform_weights[p] = {}
            continue

        scores: Dict[str, float] = {}
        for g in valid_goals:
            rank = ranks_for_p.get(g)
            if rank is None:
                raise ValueError(
                    f"Missing rank for goal '{g}' on platform '{p}'. "
                    f"Check rank computation."
                )
            scores[g] = float(4 - rank)

        total_score = sum(scores.values())
        if total_score <= 0:
            raise ValueError(
                f"Total score is non positive for platform '{p}'. "
                f"This indicates an internal logic error."
            )

        weights_for_p: Dict[str, float] = {g: scores[g] / total_score for g in valid_goals}

        state.platform_weights[p] = weights_for_p


def derive_platform_goals_from_weights(state: WizardState) -> None:
    valid_goals = list(state.valid_goals)
    active_platforms: List[str] = []
    goals_by_platform: Dict[str, List[str]] = {}

    for p, weights in state.platform_weights.items():
        if not weights:
            continue
        active_goals = [g for g in valid_goals if weights.get(g, 0.0) > 0.0]
        if active_goals:
            active_platforms.append(p)
            goals_by_platform[p] = active_goals

    state.active_platforms = active_platforms
    state.goals_by_platform = goals_by_platform


def run_module2(
    state: WizardState,
    selected_platforms: List[str],
    priorities_input: Dict[str, Dict[str, Optional[str]]],
) -> WizardState:
    set_module2_inputs(state, selected_platforms, priorities_input)
    validate_module2(state)
    compute_priority_ranks(state)
    compute_platform_weights(state)
    derive_platform_goals_from_weights(state)

    state.complete_module2_and_advance(
        active_platforms=state.active_platforms,
        goals_by_platform=state.goals_by_platform,
        priority_rank=state.priority_rank,
        platform_weights=state.platform_weights,
        platform_priorities=state.platform_priorities,
    )

    return state
