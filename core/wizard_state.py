from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set


GOAL_AW = "aw"
GOAL_EN = "en"
GOAL_WT = "wt"
GOAL_LG = "lg"

ALLOWED_OBJECTIVES: Set[str] = {GOAL_AW, GOAL_EN, GOAL_WT, GOAL_LG}

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


class FlowStateError(Exception):
    pass


@dataclass
class WizardState:
    current_step: int = 1

    module1_finalised: bool = False
    module2_finalised: bool = False
    module3_finalised: bool = False
    module4_finalised: bool = False
    module5_finalised: bool = False
    module6_finalised: bool = False

    valid_goals: List[str] = field(default_factory=list)
    total_budget: Optional[float] = None
    system_goal_weights: Dict[str, float] = field(default_factory=dict)

    platform_priorities: Dict[str, Any] = field(default_factory=dict)
    priority_rank: Dict[str, Dict[str, int]] = field(default_factory=dict)
    platform_weights: Dict[str, Dict[str, float]] = field(default_factory=dict)
    active_platforms: List[str] = field(default_factory=list)
    goals_by_platform: Dict[str, List[str]] = field(default_factory=dict)

    min_spend_per_platform: Dict[str, float] = field(default_factory=dict)
    min_budget_per_goal: Dict[str, float] = field(default_factory=dict)
    scenario_multipliers: Dict[str, float] = field(default_factory=dict)

    module3_data: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    kpi_ratios: Dict[str, Dict[str, float]] = field(default_factory=dict)
    platform_budgets: Dict[str, float] = field(default_factory=dict)
    platform_kpis: Dict[str, Dict[str, float]] = field(default_factory=dict)

    module4_result: Optional["Module4Result"] = None

    module5_result: Optional["Module5LPResult"] = None
    module5_scenario_bundle: Optional["Module5ScenarioBundle"] = None
    module5_results_by_scenario: Dict[str, "Module5LPResult"] = field(default_factory=dict)

    module6_result: Optional["Module6Result"] = None
    module6_scenario_result: Optional["Module6ScenarioResult"] = None

    def _ensure_step(self, expected_step: int) -> None:
        if self.current_step != expected_step:
            raise FlowStateError(
                f"Invalid flow: current_step={self.current_step}, expected={expected_step}."
            )

    def _ensure_no_empty_goals(self, goals: Sequence[str]) -> None:
        if not goals:
            raise ValueError("At least one goal must be selected in Module 1.")
        invalid = [g for g in goals if g not in ALLOWED_OBJECTIVES]
        if invalid:
            raise ValueError(f"Invalid goal codes in Module 1: {invalid}")

    def complete_module1_and_advance(
        self,
        *,
        valid_goals: Sequence[str],
        total_budget: float,
        system_goal_weights: Optional[Dict[str, float]] = None,
    ) -> None:
        self._ensure_step(expected_step=1)
        self._ensure_no_empty_goals(valid_goals)

        if total_budget is None:
            raise ValueError("total_budget must not be None in Module 1.")
        if float(total_budget) <= 1:
            raise ValueError("total_budget must be greater than 1 in Module 1.")

        self.valid_goals = list(valid_goals)
        self.total_budget = float(total_budget)

        if system_goal_weights is not None:
            self.system_goal_weights = dict(system_goal_weights)
        else:
            self.system_goal_weights = {}

        self.module1_finalised = True
        self.current_step = 2

    def complete_module2_and_advance(
        self,
        *,
        active_platforms: Sequence[str],
        goals_by_platform: Dict[str, List[str]],
        priority_rank: Dict[str, Dict[str, int]],
        platform_weights: Dict[str, Dict[str, float]],
        platform_priorities: Optional[Dict[str, Any]] = None,
        min_spend_per_platform: Optional[Dict[str, float]] = None,
        min_budget_per_goal: Optional[Dict[str, float]] = None,
        scenario_multipliers: Optional[Dict[str, float]] = None,
    ) -> None:
        self._ensure_step(expected_step=2)
        if not self.module1_finalised:
            raise FlowStateError("Module 1 must be finalised before Module 2.")

        if not active_platforms:
            raise ValueError("At least one platform must be selected in Module 2.")

        for p in active_platforms:
            if p not in ALLOWED_PLATFORMS:
                raise ValueError(f"Invalid platform code in Module 2: {p}")
            goals_for_p = goals_by_platform.get(p, [])
            if not goals_for_p:
                raise ValueError(f"Platform {p} must have at least one goal in Module 2.")
            invalid_goals = [g for g in goals_for_p if g not in self.valid_goals]
            if invalid_goals:
                raise ValueError(
                    f"Platform {p} has goals not selected in Module 1: {invalid_goals}"
                )

        for p in active_platforms:
            rank_map = priority_rank.get(p, {})
            weight_map = platform_weights.get(p, {})
            p_goals = goals_by_platform[p]

            missing_rank = [g for g in p_goals if g not in rank_map]
            missing_weight = [g for g in p_goals if g not in weight_map]

            if missing_rank:
                raise ValueError(
                    f"Module 2 priority_rank is missing goals for platform {p}: {missing_rank}"
                )
            if missing_weight:
                raise ValueError(
                    f"Module 2 platform_weights is missing goals for platform {p}: {missing_weight}"
                )

        self.active_platforms = list(active_platforms)
        self.goals_by_platform = {p: list(gs) for p, gs in goals_by_platform.items()}
        self.priority_rank = {p: dict(ranks) for p, ranks in priority_rank.items()}
        self.platform_weights = {p: dict(ws) for p, ws in platform_weights.items()}
        self.platform_priorities = dict(platform_priorities) if platform_priorities else {}

        self.min_spend_per_platform = dict(min_spend_per_platform) if min_spend_per_platform else {}
        self.min_budget_per_goal = dict(min_budget_per_goal) if min_budget_per_goal else {}
        self.scenario_multipliers = dict(scenario_multipliers) if scenario_multipliers else {}

        self.module2_finalised = True
        self.current_step = 3

    def complete_module3_and_advance(
        self,
        *,
        module3_data: Dict[str, Dict[str, Any]],
        platform_budgets: Dict[str, float],
        platform_kpis: Dict[str, Dict[str, float]],
        kpi_ratios: Dict[str, Dict[str, Dict[str, float]]],
    ) -> None:
        self._ensure_step(expected_step=3)
        if not self.module2_finalised:
            raise FlowStateError("Module 2 must be finalised before Module 3.")
    
        if not module3_data:
            raise ValueError("module3_data must not be empty in Module 3.")
    
        for p in self.active_platforms:
            if p not in platform_budgets:
                raise ValueError(f"Missing budget for platform {p} in Module 3.")
            budget = float(platform_budgets[p])
            if budget <= 1:
                raise ValueError(f"Budget for platform {p} must be greater than 1 in Module 3.")
    
        self.module3_data = {p: dict(d) for p, d in module3_data.items()}
        self.platform_budgets = {p: float(b) for p, b in platform_budgets.items()}
        self.platform_kpis = {
            p: {k: float(v) for k, v in (kpis or {}).items()}
            for p, kpis in (platform_kpis or {}).items()
        }
    
        cleaned: Dict[str, Dict[str, Dict[str, float]]] = {}
        for p, goals_map in (kpi_ratios or {}).items():
            if not isinstance(goals_map, dict):
                continue
            cleaned[p] = {}
            for g, ratios_map in goals_map.items():
                if not isinstance(ratios_map, dict):
                    continue
                cleaned[p][g] = {k: float(v) for k, v in ratios_map.items()}
    
        self.kpi_ratios = cleaned
    
        self.module3_finalised = True
        self.current_step = 4

    def complete_module4_and_advance(
        self,
        *,
        module4_result: "Module4Result",
    ) -> None:
        self._ensure_step(expected_step=4)
        if not self.module3_finalised:
            raise FlowStateError("Module 3 must be finalised before Module 4.")

        self.module4_result = module4_result
        self.module4_finalised = True
        self.current_step = 5

    def complete_module5_and_advance(
        self,
        *,
        module5_result: "Module5LPResult",
        module5_scenario_bundle: Optional["Module5ScenarioBundle"] = None,
        module5_results_by_scenario: Optional[Dict[str, "Module5LPResult"]] = None,
    ) -> None:
        self._ensure_step(expected_step=5)
        if not self.module4_finalised:
            raise FlowStateError("Module 4 must be finalised before Module 5.")

        self.module5_result = module5_result
        self.module5_scenario_bundle = module5_scenario_bundle
        self.module5_results_by_scenario = dict(module5_results_by_scenario) if module5_results_by_scenario else {}

        self.module5_finalised = True
        self.current_step = 6

    def complete_module6(
        self,
        *,
        module6_result: "Module6Result",
        module6_scenario_result: Optional["Module6ScenarioResult"] = None,
    ) -> None:
        self._ensure_step(expected_step=6)
        if not self.module5_finalised:
            raise FlowStateError("Module 5 must be finalised before Module 6.")

        self.module6_result = module6_result
        self.module6_scenario_result = module6_scenario_result
        self.module6_finalised = True

    def reset(self) -> None:
        self.__init__()
