# wizard_state.py

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set


# ============================================
# 1. Canonical goal codes (shared by all modules)
# ============================================

GOAL_AW = "aw"  # Awareness
GOAL_EN = "en"  # Engagement
GOAL_WT = "wt"  # Website Traffic
GOAL_LG = "lg"  # Lead Generation

ALLOWED_OBJECTIVES: Set[str] = {GOAL_AW, GOAL_EN, GOAL_WT, GOAL_LG}


# ============================================
# 2. Optional shared platform codes (if you want
#    all modules to import them from here)
# ============================================

PLATFORM_FB = "fb"
PLATFORM_IG = "ig"
PLATFORM_LI = "li"
PLATFORM_YT = "yt"

ALLOWED_PLATFORMS: Set[str] = {
    PLATFORM_FB,
    PLATFORM_IG,
    PLATFORM_LI,
    PLATFORM_YT,
}


# ============================================
# 3. Errors
# ============================================

class FlowStateError(Exception):
    """
    Raised when the wizard is used in an invalid flow state.
    For example, trying to run Module 3 while current_step is not 3.
    """
    pass


@dataclass
class WizardState:
    """
    Global wizard state shared by Modules 1 to 6.

    All modules must use this single class.
    No separate WizardState definitions are allowed in other modules.

    Flow rules:
    - current_step starts at 1.
    - Each module can only be completed when current_step equals its step number.
    - Completing a module marks it as finalised and advances current_step by 1.
    - There is no backward navigation. To go back to earlier modules,
      you must call reset() and start the wizard from scratch.
    """

    # ----------------------------------------
    # Flow control
    # ----------------------------------------
    current_step: int = 1

    module1_finalised: bool = False
    module2_finalised: bool = False
    module3_finalised: bool = False
    module4_finalised: bool = False
    module5_finalised: bool = False
    module6_finalised: bool = False

    # ----------------------------------------
    # Module 1 outputs
    # ----------------------------------------
    valid_goals: List[str] = field(default_factory=list)
    total_budget: Optional[float] = None

    # Optional system level weights for goals, if later needed
    system_goal_weights: Dict[str, float] = field(default_factory=dict)

    # ----------------------------------------
    # Module 2 outputs
    # ----------------------------------------
    # Raw platform priority structures from Module 2
    platform_priorities: Dict[str, Any] = field(default_factory=dict)

    # priority_rank[platform][goal] = rank (1, 2, 3, ...)
    priority_rank: Dict[str, Dict[str, int]] = field(default_factory=dict)

    # platform_weights[platform][goal] = weight in [0, 1]
    platform_weights: Dict[str, Dict[str, float]] = field(default_factory=dict)

    # Active platforms and their active goals that go into Module 3
    active_platforms: List[str] = field(default_factory=list)
    goals_by_platform: Dict[str, List[str]] = field(default_factory=dict)

    # ----------------------------------------
    # Module 3 outputs
    # ----------------------------------------
    # Raw input data collected in Module 3 per platform
    # Example structure is up to Module 3 implementation.
    module3_data: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # KPI ratio per platform and KPI:
    # kpi_ratios[platform][kpi_id] = kpi_value / platform_budget
    kpi_ratios: Dict[str, Dict[str, float]] = field(default_factory=dict)

    # Historical or user entered budgets per platform
    platform_budgets: Dict[str, float] = field(default_factory=dict)

    # Historical or user entered KPI values per platform
    platform_kpis: Dict[str, Dict[str, float]] = field(default_factory=dict)

    # ----------------------------------------
    # Module 4 outputs
    # ----------------------------------------
    # Replace "Module4Result" with the actual result class name in module4
    module4_result: Optional["Module4Result"] = None

    # ----------------------------------------
    # Module 5 outputs
    # ----------------------------------------
    # Replace "Module5LPResult" with the actual result class name in module5
    module5_result: Optional["Module5LPResult"] = None

    # ----------------------------------------
    # Module 6 outputs
    # ----------------------------------------
    # Replace "Module6Result" with the actual result class name in module6
    module6_result: Optional["Module6Result"] = None

    # ==================================================================
    # Flow helper methods
    # ==================================================================

    def _ensure_step(self, expected_step: int) -> None:
        """
        Internal helper to enforce that the wizard is at a specific step.
        """
        if self.current_step != expected_step:
            raise FlowStateError(
                f"Invalid flow: current_step={self.current_step}, "
                f"expected={expected_step}."
            )

    def _ensure_no_empty_goals(self, goals: Sequence[str]) -> None:
        """
        Validate that the selected goals are non empty and valid.
        """
        if not goals:
            raise ValueError("At least one goal must be selected in Module 1.")
        invalid = [g for g in goals if g not in ALLOWED_OBJECTIVES]
        if invalid:
            raise ValueError(f"Invalid goal codes in Module 1: {invalid}")

    # ==================================================================
    # Module 1: goal selection and total budget
    # ==================================================================

    def complete_module1_and_advance(
        self,
        *,
        valid_goals: Sequence[str],
        total_budget: float,
        system_goal_weights: Optional[Dict[str, float]] = None,
    ) -> None:
        """
        Finalise Module 1 and advance the wizard to step 2.

        Rules:
        - Must be called only when current_step == 1.
        - total_budget must be greater than 1.
        - valid_goals must be a non empty subset of ALLOWED_OBJECTIVES.
        - Once called, Module 1 is locked. To change goals or budget,
          you must reset the wizard.
        """
        self._ensure_step(expected_step=1)
        self._ensure_no_empty_goals(valid_goals)

        if total_budget is None:
            raise ValueError("total_budget must not be None in Module 1.")
        if total_budget <= 1:
            raise ValueError("total_budget must be greater than 1 in Module 1.")

        self.valid_goals = list(valid_goals)
        self.total_budget = float(total_budget)

        if system_goal_weights is not None:
            self.system_goal_weights = dict(system_goal_weights)
        else:
            self.system_goal_weights = {}

        self.module1_finalised = True
        self.current_step = 2

    # ==================================================================
    # Module 2: platform selection and goal priorities per platform
    # ==================================================================

    def complete_module2_and_advance(
        self,
        *,
        active_platforms: Sequence[str],
        goals_by_platform: Dict[str, List[str]],
        priority_rank: Dict[str, Dict[str, int]],
        platform_weights: Dict[str, Dict[str, float]],
        platform_priorities: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Finalise Module 2 and advance the wizard to step 3.

        Rules:
        - Must be called only when current_step == 2 and Module 1 is finalised.
        - active_platforms must not be empty.
        - For each platform in active_platforms, there must be at least
          one goal in goals_by_platform and that goal must be in valid_goals.
        - No backward change after this method unless reset() is called.
        """
        self._ensure_step(expected_step=2)
        if not self.module1_finalised:
            raise FlowStateError("Module 1 must be finalised before Module 2.")

        if not active_platforms:
            raise ValueError("At least one platform must be selected in Module 2.")

        # Validate platforms and goals
        for p in active_platforms:
            if p not in ALLOWED_PLATFORMS:
                raise ValueError(f"Invalid platform code in Module 2: {p}")
            goals_for_p = goals_by_platform.get(p, [])
            if not goals_for_p:
                raise ValueError(
                    f"Platform {p} must have at least one goal in Module 2."
                )
            invalid_goals = [g for g in goals_for_p if g not in self.valid_goals]
            if invalid_goals:
                raise ValueError(
                    f"Platform {p} has goals not selected in Module 1: {invalid_goals}"
                )

        # Basic consistency checks for priority_rank and platform_weights
        for p in active_platforms:
            rank_map = priority_rank.get(p, {})
            weight_map = platform_weights.get(p, {})
            p_goals = goals_by_platform[p]

            missing_rank = [g for g in p_goals if g not in rank_map]
            missing_weight = [g for g in p_goals if g not in weight_map]

            if missing_rank:
                raise ValueError(
                    f"Module 2 priority_rank is missing goals for platform {p}: "
                    f"{missing_rank}"
                )
            if missing_weight:
                raise ValueError(
                    f"Module 2 platform_weights is missing goals for platform {p}: "
                    f"{missing_weight}"
                )

        self.active_platforms = list(active_platforms)
        self.goals_by_platform = {p: list(gs) for p, gs in goals_by_platform.items()}
        self.priority_rank = {
            p: dict(ranks) for p, ranks in priority_rank.items()
        }
        self.platform_weights = {
            p: dict(ws) for p, ws in platform_weights.items()
        }
        self.platform_priorities = dict(platform_priorities) if platform_priorities else {}

        self.module2_finalised = True
        self.current_step = 3

    # ==================================================================
    # Module 3: budget and KPI data collection per platform
    # ==================================================================

    def complete_module3_and_advance(
        self,
        *,
        module3_data: Dict[str, Dict[str, Any]],
        platform_budgets: Dict[str, float],
        platform_kpis: Dict[str, Dict[str, float]],
        kpi_ratios: Dict[str, Dict[str, float]],
    ) -> None:
        """
        Finalise Module 3 and advance the wizard to step 4.

        Rules:
        - Must be called only when current_step == 3 and Module 2 is finalised.
        - For each active platform, there must be a positive budget (> 1).
        - For each KPI value, the module level validation should already
          ensure positivity; here we do only minimal checks.
        - No back navigation after this method without reset().
        """
        self._ensure_step(expected_step=3)
        if not self.module2_finalised:
            raise FlowStateError("Module 2 must be finalised before Module 3.")

        if not module3_data:
            raise ValueError("module3_data must not be empty in Module 3.")

        # Validate budgets
        for p in self.active_platforms:
            if p not in platform_budgets:
                raise ValueError(
                    f"Missing budget for platform {p} in Module 3."
                )
            budget = platform_budgets[p]
            if budget is None or budget <= 1:
                raise ValueError(
                    f"Budget for platform {p} must be greater than 1 in Module 3."
                )

        self.module3_data = {p: dict(d) for p, d in module3_data.items()}
        self.platform_budgets = {p: float(b) for p, b in platform_budgets.items()}
        self.platform_kpis = {
            p: {k: float(v) for k, v in kpis.items()}
            for p, kpis in platform_kpis.items()
        }
        self.kpi_ratios = {
            p: {k: float(v) for k, v in ratios.items()}
            for p, ratios in kpi_ratios.items()
        }

        self.module3_finalised = True
        self.current_step = 4

    # ==================================================================
    # Module 4: any transformation or pre LP processing
    # ==================================================================

    def complete_module4_and_advance(
        self,
        *,
        module4_result: "Module4Result",
    ) -> None:
        """
        Finalise Module 4 and advance the wizard to step 5.

        Rules:
        - Must be called only when current_step == 4 and Module 3 is finalised.
        """
        self._ensure_step(expected_step=4)
        if not self.module3_finalised:
            raise FlowStateError("Module 3 must be finalised before Module 4.")

        self.module4_result = module4_result
        self.module4_finalised = True
        self.current_step = 5

    # ==================================================================
    # Module 5: optimisation LP and allocation result
    # ==================================================================

    def complete_module5_and_advance(
        self,
        *,
        module5_result: "Module5LPResult",
    ) -> None:
        """
        Finalise Module 5 and advance the wizard to step 6.

        Rules:
        - Must be called only when current_step == 5 and Module 4 is finalised.
        """
        self._ensure_step(expected_step=5)
        if not self.module4_finalised:
            raise FlowStateError("Module 4 must be finalised before Module 5.")

        self.module5_result = module5_result
        self.module5_finalised = True
        self.current_step = 6

    # ==================================================================
    # Module 6: final KPI forecast table, reporting, etc.
    # ==================================================================

    def complete_module6(
        self,
        *,
        module6_result: "Module6Result",
    ) -> None:
        """
        Finalise Module 6 and finish the wizard.

        Rules:
        - Must be called only when current_step == 6 and Module 5 is finalised.
        """
        self._ensure_step(expected_step=6)
        if not self.module5_finalised:
            raise FlowStateError("Module 5 must be finalised before Module 6.")

        self.module6_result = module6_result
        self.module6_finalised = True
        # current_step can stay at 6 to show the wizard is at the last step.

    # ==================================================================
    # Reset the entire wizard
    # ==================================================================

    def reset(self) -> None:
        """
        Reset the whole wizard to its initial state.

        This clears all module outputs and flow flags.
        After calling reset(), the wizard returns to step 1 as if it is new.
        """
        self.__init__()
