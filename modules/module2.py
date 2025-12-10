from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from wizard_state import WizardState, ALLOWED_PLATFORMS


# ============================================
# 1. Platforms
# ============================================

PLATFORMS = ("fb", "ig", "li", "yt")  # Facebook, Instagram, LinkedIn, YouTube


# ============================================
# 2. Data structures (local to Module 2)
# ============================================

@dataclass
class PlatformPriority:
    """
    Selection and goal priorities for a single platform.

    Attributes
    ----------
    selected : bool
        Whether this platform is active.
    priority_1 : Optional[str]
        Code of the first priority goal on this platform (for example "aw").
    priority_2 : Optional[str]
        Code of the second priority goal on this platform (for example "en").
    """
    selected: bool = False
    priority_1: Optional[str] = None
    priority_2: Optional[str] = None


# ============================================
# 3. Helpers: initialisation and basic guards
# ============================================

def initialise_module2_state(state: WizardState) -> None:
    """
    Ensure platform_priorities is initialised for all platforms.

    Must be called only after Module 1 has been finalised.
    """
    if not state.module1_finalised:
        raise ValueError("Module 1 has not been finalised, cannot enter Module 2.")

    # Create default entries if missing
    for p in PLATFORMS:
        if p not in state.platform_priorities:
            state.platform_priorities[p] = PlatformPriority()


# ============================================
# 4. Input setting for Module 2
# ============================================

def set_module2_inputs(
    state: WizardState,
    selected_platforms: List[str],
    priorities_input: Dict[str, Dict[str, Optional[str]]],
) -> None:
    """
    Apply user choices for Module 2 into the state.

    Parameters
    ----------
    state : WizardState
        Global wizard state. Must have module1_finalised = True.

    selected_platforms : List[str]
        List of platform codes that the user has ticked, for example ["fb", "ig"].

    priorities_input : Dict[str, Dict[str, Optional[str]]]
        For each platform, a dict with keys "priority_1" and "priority_2".
        Example:
            {
                "fb": {"priority_1": "aw", "priority_2": "en"},
                "ig": {"priority_1": "wt", "priority_2": None},
            }
        Platforms not present in this dict are assumed to have no priorities.
    """
    if not state.module1_finalised:
        raise ValueError("Module 1 must be finalised before setting Module 2 inputs.")

    initialise_module2_state(state)

    selected_set = set(selected_platforms)

    # Basic guard: all selected platforms must be known and allowed
    unknown_platforms = selected_set - set(PLATFORMS)
    if unknown_platforms:
        raise ValueError(f"Unknown platform codes in selection: {unknown_platforms}")

    invalid_platforms = selected_set - ALLOWED_PLATFORMS
    if invalid_platforms:
        raise ValueError(f"Invalid platform codes according to WizardState: {invalid_platforms}")

    # Reset all platform selections first
    for p in PLATFORMS:
        platform_state: PlatformPriority = state.platform_priorities[p]
        platform_state.selected = p in selected_set

        # If a platform is deselected, we can safely clear its priorities
        if p not in selected_set:
            platform_state.priority_1 = None
            platform_state.priority_2 = None

    # Apply priorities for selected platforms
    for p, prio_dict in priorities_input.items():
        if p not in PLATFORMS:
            raise ValueError(f"Unknown platform in priorities_input: {p}")

        platform_state = state.platform_priorities[p]

        # If the platform is not selected, ignore any priority input
        if not platform_state.selected:
            continue

        p1 = prio_dict.get("priority_1")
        p2 = prio_dict.get("priority_2")

        platform_state.priority_1 = p1
        platform_state.priority_2 = p2


# ============================================
# 5. Validation for Module 2
# ============================================

def validate_module2(state: WizardState) -> None:
    """
    Validate all Module 2 constraints.

    Raises ValueError with a descriptive message if anything is invalid.
    """
    if not state.module1_finalised:
        raise ValueError("Module 1 must be finalised before validating Module 2.")

    if not state.valid_goals:
        # In normal flow this should never happen, as Module 1 enforces it.
        raise ValueError("No valid goals from Module 1. Please restart the wizard.")

    # 1) At least one platform must be selected
    selected_platforms = [
        p for p in PLATFORMS
        if isinstance(state.platform_priorities.get(p), PlatformPriority)
        and state.platform_priorities[p].selected
    ]
    if len(selected_platforms) == 0:
        raise ValueError("At least one platform must be selected in Module 2.")

    valid_goals_set = set(state.valid_goals)

    # 2) Per platform priority rules
    for p in selected_platforms:
        prio: PlatformPriority = state.platform_priorities[p]
        p1 = prio.priority_1
        p2 = prio.priority_2

        # 2a) Priority 2 cannot exist without Priority 1
        if p1 is None and p2 is not None:
            raise ValueError(
                f"On platform '{p}', you cannot set Priority 2 without Priority 1."
            )

        # 2b) Priority 1 and Priority 2 cannot be the same
        if p1 is not None and p2 is not None and p1 == p2:
            raise ValueError(
                f"On platform '{p}', Priority 1 and Priority 2 must be different."
            )

        # 2c) Priority goals must be among valid_goals from Module 1
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

        # 2d) If there is only one valid goal overall, Priority 2 makes no sense
        if len(valid_goals_set) == 1 and p2 is not None:
            raise ValueError(
                f"On platform '{p}', you cannot set Priority 2 when there is only "
                f"one valid goal in Module 1."
            )


# ============================================
# 6. Rank computation
# ============================================

def compute_priority_ranks(state: WizardState) -> None:
    """
    For each selected platform and each valid goal, compute a rank:

        1 = highest importance
        2 = medium importance
        3 = lowest or residual importance

    Rules per platform (local, independent from others):
    - If no priority is set (p1 and p2 are None), all goals get rank 1.
    - If Priority 1 is set:
        * That goal gets rank 1.
        * If Priority 2 is set:
            - That goal gets rank 2.
        * All remaining goals get rank 3.
    """
    if not state.valid_goals:
        raise ValueError("Cannot compute ranks, no valid goals in state.")

    valid_goals = list(state.valid_goals)
    state.priority_rank = {}

    for p in PLATFORMS:
        prio = state.platform_priorities.get(p)
        if not isinstance(prio, PlatformPriority) or not prio.selected:
            # No ranks for unselected platforms
            state.priority_rank[p] = {}
            continue

        p1 = prio.priority_1
        p2 = prio.priority_2

        ranks_for_p: Dict[str, int] = {}

        if p1 is None and p2 is None:
            # No explicit priority, all goals rank 1
            for g in valid_goals:
                ranks_for_p[g] = 1
        else:
            # We have at least Priority 1
            for g in valid_goals:
                if g == p1:
                    ranks_for_p[g] = 1
                elif p2 is not None and g == p2:
                    ranks_for_p[g] = 2
                else:
                    ranks_for_p[g] = 3

        state.priority_rank[p] = ranks_for_p


# ============================================
# 7. Rank → weight conversion
# ============================================

def compute_platform_weights(state: WizardState) -> None:
    """
    Convert priority_rank into platform_weights.

    For each platform p and goal g:
        score[g] = 4 - rank[g]    # rank 1 → 3, rank 2 → 2, rank 3 → 1
        weight[g] = score[g] / sum(score[h] for all h)

    Properties:
    - For each platform, sum of weights over all valid goals = 1.
    - If all ranks are equal, all weights are equal.
    - A goal with rank 1 always has a higher weight than rank 2,
      and rank 2 higher than rank 3 in the same platform.
    """
    if not state.valid_goals:
        raise ValueError("Cannot compute weights, no valid goals in state.")

    valid_goals = list(state.valid_goals)
    state.platform_weights = {}

    for p in PLATFORMS:
        ranks_for_p = state.priority_rank.get(p, {})

        # Only compute weights for selected platforms with ranks
        prio = state.platform_priorities.get(p)
        if not isinstance(prio, PlatformPriority) or not prio.selected or not ranks_for_p:
            state.platform_weights[p] = {}
            continue

        # Compute scores
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

        # Normalise to weights
        weights_for_p: Dict[str, float] = {
            g: scores[g] / total_score for g in valid_goals
        }

        state.platform_weights[p] = weights_for_p


# ============================================
# 8. Derive active platforms and goals (bridge to Module 3)
# ============================================

def derive_platform_goals_from_weights(state: WizardState) -> None:
    """
    Based on platform_weights and valid_goals, derive:
      - active_platforms
      - goals_by_platform

    This ensures that:
        set(state.platform_weights.keys())
      ⊇ set(state.active_platforms)
      == set(state.goals_by_platform.keys())
    """
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


# ============================================
# 9. Orchestrator for Module 2 that delegates to WizardState
# ============================================

def run_module2(
    state: WizardState,
    selected_platforms: List[str],
    priorities_input: Dict[str, Dict[str, Optional[str]]],
) -> WizardState:
    """
    High level function to run the entire Module 2 logic.

    It only fills the data structures in WizardState and then calls
    WizardState.complete_module2_and_advance to lock the module and
    advance the flow. It does not touch current_step or the finalised flag
    directly.
    """
    # 1) Apply inputs
    set_module2_inputs(state, selected_platforms, priorities_input)

    # 2) Validate
    validate_module2(state)

    # 3) Compute ranks
    compute_priority_ranks(state)

    # 4) Compute weights
    compute_platform_weights(state)

    # 5) Derive active platforms and goals for Module 3
    derive_platform_goals_from_weights(state)

    # 6) Let WizardState handle flow and locking
    state.complete_module2_and_advance(
        active_platforms=state.active_platforms,
        goals_by_platform=state.goals_by_platform,
        priority_rank=state.priority_rank,
        platform_weights=state.platform_weights,
        platform_priorities=state.platform_priorities,
    )

    return state
