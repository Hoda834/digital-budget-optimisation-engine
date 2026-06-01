# Calibration Appendix

Every quantitative model carries hand-set constants that shape its behaviour but
weren't derived from the optimisation itself. This document catalogues every
such constant in the engine, gives the source / intuition behind each value,
and describes what changes if the value is moved.

The honest position: **none of these constants are scientifically calibrated
against the engine's own back-tests.** Most are anchored in published platform
guidance, conventional industry practice, or the OR/empirical-Bayes tradition.
A few are pragmatic v1 choices that we've kept because changing them moves the
output less than the noise floor of the input data. Where that's the case, we
say so.

The audience for this doc is a reviewer who wants to ask "would a different
choice break your conclusions?" before trusting the engine's recommendations.
The answer is *no* for the structural constants (yield brackets, shrinkage
window, scenario multipliers): the qualitative ordering of platforms is
preserved across reasonable perturbations. It's *yes* for the per-platform
effective minimums when applied as hard floors — which is why they're
warnings, not constraints. Each section flags which category a constant is in.

---

## 1. LP scaling and structural constants

### `OBJECTIVE_SCALE = 1000.0`

- **Location:** `modules/module5.py:22`
- **Role:** Multiplier on the LP's reported objective value so users see a
  human-readable number (~10²–10⁴) instead of the raw 10⁻³–10⁻¹ that the
  normalised productivities would produce.
- **Source:** Cosmetic. Chosen so that a typical £10k–£20k UK B2B SaaS budget
  produces a 3- to 4-digit objective value rather than a fraction.
- **Sensitivity:** None. The LP's ranking and allocation are scale-invariant
  in the objective — multiplying by 10× or 0.1× shifts the displayed number
  but produces the same plan. We expose the raw objective alongside the
  scaled one (`objective_value_raw` in the result) so a reviewer can verify
  this.
- **When to change:** Never, unless you also want to change the units of the
  "Objective value" UI metric.

### `YIELD_BRACKETS = ((0.25, 1.00), (0.35, 0.65), (0.40, 0.35))`

- **Location:** `modules/module5.py:69–73`
- **Role:** Piecewise-linear approximation of diminishing returns. The LP
  fills the first bracket (up to 25% of a cell's "natural" budget) at full
  productivity, the next bracket (next 35%) at 65% productivity, and the
  last bracket (final 40%) at 35% productivity.
- **Source:** The shape (concave, three brackets, monotonically decreasing
  yields) is the canonical OR approximation of the Hill/logistic saturation
  curves marketers actually see on ad platforms. The specific breakpoints
  and yields are **author-chosen**, not derived from data. They produce a
  plausible curve: 100% → 65% → 35% over the first three quartiles is
  consistent with typical Meta/Google "diminishing marginal CPA" charts.
- **Sensitivity:** Moderate but well-behaved. Flatter brackets (e.g.
  `(0.33, 0.9), (0.33, 0.7), (0.34, 0.5)`) produce more concentrated
  allocations — the LP pushes budget toward top platforms. Steeper brackets
  (e.g. `(0.20, 1.0), (0.30, 0.40), (0.50, 0.15)`) spread budget more
  evenly. The *ordering* of platforms is preserved under both perturbations
  because the brackets apply uniformly across cells.
- **Tested behaviour:** The smoke test
  `test_diminishing_returns_with_brackets_prevents_concentration` checks
  that allocating to a single high-productivity platform is bounded by the
  bracket structure rather than going to the budget cap.
- **When to change:** If a vertical's empirical saturation looks much
  flatter or steeper than the default (e.g. branded search, where the
  curve is nearly flat over the relevant budget range), expose this as a
  configuration. We have not yet seen a deployment where this was
  necessary; the brackets are conservative.

### Tie-breaking tolerance `0.02`

- **Location:** `modules/module5.py:916` ("Fix C")
- **Role:** When two platforms have the same goal and their normalised
  productivities differ by ≤2%, redistribute the LP's allocation
  proportionally instead of accepting the solver's arbitrary corner choice.
  Prevents two near-identical platforms from getting wildly different
  allocations purely due to floating-point order.
- **Source:** Empirical. 2% is just inside the noise floor produced by the
  shrinkage step on typical inputs.
- **Sensitivity:** Effectively zero on well-conditioned problems (no
  near-ties). Moves allocation between near-identical cells when ties
  exist — but only between cells that the solver had treated as
  interchangeable, so the objective value is unchanged.
- **When to change:** Increase to 0.05 if you see reviewers complaining
  about jitter between platforms that "look the same." Lower at your
  peril — below 0.005 you'll see solver-corner artefacts re-emerge.

### Constraint slack tolerance `max(1e-4, 1e-3 × |rhs|)`

- **Location:** `modules/module5.py:962`
- **Role:** Threshold for identifying which constraints are binding for
  sensitivity reporting. Relative to the right-hand-side magnitude so
  large constraints (whole-budget) and small ones (per-platform floors)
  are both treated consistently.
- **Source:** Standard OR practice; matches CBC's default feasibility
  tolerance order of magnitude.
- **Sensitivity:** Cosmetic — only affects which constraints get listed
  in the "binding constraints" UI, not the solver's behaviour.

### Feasibility epsilon `1e-9`

- **Location:** `modules/module5.py:586, 1117`
- **Role:** Floating-point cushion for `binding_floor ≤ budget_cap`
  checks. Prevents an LP that's mathematically feasible from being
  declared infeasible due to rounding.
- **Source:** Standard.

---

## 2. Per-platform monthly effective minimums

### `PLATFORM_EFFECTIVE_MINIMUMS_PER_MONTH`

- **Location:** `modules/module5.py:32–63`
- **Role:** Per-platform monthly spend below which the platform's auction
  / learning algorithm is unlikely to leave its learning phase. Used to
  raise warnings on the result page, **not** to constrain the LP. The
  user can ignore the warning, drop the platform, or raise their
  per-platform floor in Module 2.
- **Per-platform values and provenance:**

  | Platform | £/month | Source |
  |---|---:|---|
  | Facebook | 1,000 | Meta's "50 conversions / week / ad set" guidance, back-calculated at typical UK B2B CPAs (£20–£35) |
  | Instagram | 1,000 | Shares the Meta delivery system; same threshold |
  | LinkedIn | 2,000 | LinkedIn's auction premium + 7-day attribution window; the only platform that publishes a recommended minimum in this range |
  | YouTube | 1,500 | Google's CPV bidding stabilises at this range for non-branded campaigns |
  | TikTok | 1,500 | Mirrors Meta's learning phase but higher to fund the 7-day attribution window comfortably |
  | Pinterest | 800 | Smaller-spend market; figure is industry advice, not vendor-published |
  | X (Twitter) | 800 | Same — vendor publishes no floor; this is conventional |
  | Snapchat | 1,000 | Same — vendor publishes no floor; this is conventional |
  | Reddit | 500 | Reddit's auction is thinner; lower threshold reflects how little signal the platform's optimiser needs to act on |
  | Google Search | 1,000 | Target CPA bidding needs ~30 conversions/month to exit learning; £1k is the typical UK threshold at mid-funnel CPAs |
  | Google Display | 500 | Display Network auctions are thinner and CPMs lower; learning phase finishes on less spend (matches the Reddit threshold) |
  | Google Performance Max | 2,500 | Smart Bidding needs ~50 conversions across blended surfaces (Search / Display / YouTube / Shopping / Maps); higher floor than Search alone |

- **Scaling:** Each threshold is multiplied by `campaign_duration_days / 30`
  before being attached to the LP input. A 90-day campaign gets a 3× threshold
  per platform; a 14-day campaign gets ~0.47×.
- **Sensitivity:** Because these are warnings, not constraints, the **plan
  is unchanged** when these numbers move. Only the UI's red badge moves.
  Reviewers should know that the LinkedIn threshold (£2k) is the only one
  that's both vendor-anchored *and* commonly violated by small UK B2B
  budgets; deployments with <£15k total budgets routinely see a LinkedIn
  warning.
- **Honest caveat for a reviewer:** None of these are vendor SLAs. They
  are author-anchored guidelines mostly derived from agency practice and
  the calculation "platform-published-minimum-conversions × typical-CPA".
  A finance-review audience should treat them as "industry advice" not
  "vendor floor."

---

## 3. Productivity composition (count + rate KPIs)

### Composite productivity formula

- **Location:** `modules/module5.py:243–257`
- **Formula:**
  ```
  if count_vals:
      productivity = mean(count_vals) × (1 + mean(rate_vals))   # when both present
  elif rate_vals:
      productivity = mean(rate_vals)                            # rate-only cells
  else:
      productivity = 0.0
  ```
- **Role:** Reduce 1–2 historical KPI ratios per (platform, goal) cell to
  a single scalar productivity the LP can compare across cells.
- **Source:** Authored as a v1 heuristic. The intuition: a count KPI
  (Reach, Leads) carries the £-denominated productivity signal, while a
  rate KPI would carry a quality signal that tilts the count up or down
  without changing units. Multiplying by `(1 + rate)` rather than just
  `rate` keeps the base scale stable when the rate is small.
  **As of the uniform-units refactor, no canonical KPI is a rate — every
  social-platform engagement KPI is now a count (sum of likes / comments
  / shares / etc.).** The rate-handling branch is retained as a forward-
  compatibility shim.
- **Sensitivity:** When the branch was active, the multiplicative tilt
  was mild because typical rate values were 0.01–0.05. A platform with
  5% engagement would have got a 5% bonus
  to its count productivity — large enough to break ties, too small to
  flip ordering between cells with genuinely different counts.
- **Honest caveat for a reviewer:** This formula is not derivable from
  any optimisation principle. It is defensible as a way to incorporate
  rate signal without unit confusion, but a reviewer who wanted formal
  justification would not find one in the OR literature. The cleaner
  approach — separate count and rate into independent constraints —
  would require redesigning the LP variable structure and was deferred.
- **Test coverage:** `test_rate_kpi_accepted_and_routed_through_r_pg`
  validates that rate KPIs reach `r_pg`; `test_module6_rate_kpi_not_
  multiplied_by_budget` validates the unit invariant downstream.

### Fix A: rate-only cell rescaling

- **Location:** `modules/module5.py:272–296`
- **Role:** When a cell has *only* rate KPIs and other platforms in the
  same goal report a count, the rate-only cells are multiplied by the
  cross-platform count mean so they compete on the same numerical
  footing inside the LP.
- **Source:** Required for the LP to compare apples-to-apples. A 4.5%
  rate (0.045) competing against a 50 leads/£ count (50.0) would lose
  by three orders of magnitude without this rescale.
  **As of the uniform-units refactor every canonical KPI is a count, so
  the "rate-only cell" condition is never true in production** — this
  branch is retained as a forward-compatibility shim.
- **Sensitivity:** Structural — without Fix A, rate-only cells would
  get zero allocation regardless of their quality. The exact scaling
  factor (cross-platform mean) is the natural choice; alternatives
  (median, geomean) would move rate-only cells by ~10–20% but not
  change the qualitative ordering.

---

## 4. Data-quality shrinkage

### Shrinkage prior strength `30 days`

- **Location:** `modules/module5.py:343` (`_DATA_QUALITY_SHRINKAGE_REFERENCE_DAYS = 30.0`)
- **Role:** James-Stein-style shrinkage pulls each platform's productivity
  estimate toward the cross-platform mean for the same goal, weighted by
  how much historical data backs the estimate. The shrinkage weight is
  `w = 30 / (30 + historical_days)`.
- **Source:** Empirical Bayes in the textbook sense estimates the prior
  strength from the data; here it's fixed at 30 days because:
  1. The reference window matches the conventional "campaign month"
     baseline used in Module 6's uncertainty bands.
  2. The data needed for genuine empirical Bayes estimation
     (cross-platform variance of true productivities) isn't reliably
     available from typical Module 3 inputs.
  3. The fixed prior is conservative: it shrinks weak data more than a
     fitted prior probably would, which a reviewer should prefer over
     "garbage in, confident optimisation out."
- **Sensitivity:** The shrinkage weight `w = REF / (REF + historical_days)`
  responds non-linearly to changes in `REF`, so it's worth showing the
  numbers directly rather than quoting one figure.  At three reference
  values, with three example history lengths:

  | History | REF=15 | REF=30 (default) | REF=60 |
  |---:|---:|---:|---:|
  |  7 days | 0.68 | **0.81** | 0.90 |
  | 30 days | 0.33 | **0.50** | 0.67 |
  | 90 days | 0.14 | **0.25** | 0.40 |

  Halving the reference window changes the weight by ~16% (at 7-day
  history) up to ~33% (at 30-day history); doubling moves it the other
  way by a similar amount.  The qualitative effect (low-data platforms
  pulled toward the cross-platform mean) is preserved across all
  three settings.  A reviewer who wants empirical-Bayes rigour can
  replace this constant with a per-goal fitted value — the call site
  reads it from a module-level constant for exactly that purpose.
- **When to change:** If your typical input has much shorter history
  windows (e.g. weekly reports only), consider 14 days. If you only
  ingest 90-day reports, consider 60 days. The default is sized for
  the typical case of one month of historical data per platform.

---

## 5. Uncertainty bands on the forecast

### `DEFAULT_UNCERTAINTY_BAND = 0.30`

- **Location:** `modules/module6.py:22`
- **Role:** ±30% fallback uncertainty band on count-KPI forecasts when
  no per-KPI history is available. Used when Module 3 has neither
  multi-period observations nor a `historical_days` field.
- **Source:** Industry convention. Display ad performance week-to-week
  typically varies 20–40% under stable conditions; 30% is the median.
- **Sensitivity:** Cosmetic for the LP (the bands don't feed the
  optimiser); affects how wide the forecast intervals look on the
  results page. Doubling produces visibly less confident plans;
  halving produces overconfident ones.

### `_REFERENCE_WINDOW_DAYS = 30.0`

- **Location:** `modules/module6.py:27`
- **Role:** Reference window for scaling the default 30% band by
  observed history length: `band = 0.30 × sqrt(30 / observed_days)`.
  A 90-day history produces a ~17% band; a 7-day history a ~62%
  band.
- **Source:** Square-root scaling is the standard variance-scales-with-
  sample-size relationship for independent observations of a noisy
  process. The reference window matches the shrinkage prior so the two
  uncertainty treatments stay consistent.
- **Sensitivity:** Moderate. Other reference windows (14, 60) shift
  the entire band curve. We pin to 30 to keep the "campaign month"
  metaphor consistent across all modules.

### Band clamps `_MIN_BAND = 0.05, _MAX_BAND = 1.00`

- **Location:** `modules/module6.py:31–32`
- **Role:** Hard limits on per-KPI uncertainty bands. Floor at 5%
  prevents pathological zero-variance inputs from producing zero
  bands (false precision); cap at 100% prevents bands from rendering
  forecasts meaningless ("plan delivers between 0 and 2× the point
  estimate" is a non-statement).
- **Source:** Author-chosen sanity floor / ceiling. Lower-floor
  alternatives (1%, 2%) would let occasional noisy-but-favourable
  inputs produce 0% bands; higher-ceiling alternatives (150%+) would
  produce bands wider than the point estimate, which would mislead
  users on the results page.

---

## 6. Scenario multipliers (budget and goal)

### Budget multipliers `{conservative: 0.85, base: 1.00, optimistic: 1.15}`

- **Location:** `core/wizard_state.py:250–252` (`_default_scenario_multipliers`)
- **Role:** Total-budget scalars for the three planning scenarios. The
  LP is re-solved with each scaled budget.
- **Source:** Author-chosen. ±15% is the "round number" planning
  convention used in finance scenarios — it lines up with typical
  budget-revision cycles (mid-quarter +15%, end-of-quarter -15%).
- **Sensitivity:** Linear by construction. The conservative and
  optimistic plans differ from base by ~15% in spend; the per-platform
  allocations follow the LP's response curve over that range.
- **Honest caveat for a reviewer:** Why not ±10% or ±20%? No empirical
  reason. The values were picked to give a visually distinct three-
  scenario set without crossing the "plausibly different campaign" line.
- **Override:** Users can supply their own `scenario_multipliers` dict
  via Module 1's advanced inputs.

### Per-goal scenario multipliers

- **Location:** `core/wizard_state.py:280–291`
- **Values:**

  | Goal | Conservative | Optimistic | Funnel position |
  |---|---:|---:|---|
  | Awareness | 1.05 | 0.95 | Upper |
  | Engagement | 1.05 | 0.95 | Upper-mid |
  | Website Traffic | 0.95 | 1.10 | Mid |
  | Lead Generation | 0.85 | 1.20 | Lower |

- **Role:** Productivity multipliers applied per scenario per goal,
  separately from the budget scalar. Conservative *raises* upper-funnel
  expectations (reach is more predictable) and *lowers* lower-funnel
  expectations (conversion is more volatile); optimistic is the inverse.
- **Source:** Author-chosen, anchored in the convention that upper-funnel
  KPIs (reach, impressions) vary less than lower-funnel KPIs
  (conversion, LTV).
- **Sensitivity:** Strong effect on the cross-scenario *story*. Lead-Gen
  spans ±20% between conservative and optimistic; Awareness only ±5%.
  This widens the per-platform allocation gap between scenarios in
  funnel-heavy plans (LinkedIn-heavy) more than in awareness-heavy
  plans (Facebook-heavy).
- **Honest caveat for a reviewer:** These multipliers are the
  qualitatively-loaded constant in the engine. A reviewer with strong
  priors about funnel volatility may disagree — the test
  `test_scenarios_produce_distinct_allocations` only verifies that
  three scenarios produce different plans, not that the *direction* of
  the difference matches any particular industry data.
- **Override:** Module 2's `scenario_goal_multipliers` accepts a custom
  dict.

---

## 7. Monte Carlo robustness

### `DEFAULT_MC_TRIALS = 200`

- **Location:** `modules/module5.py:1237`
- **Role:** Number of LP re-solves with productivities perturbed by
  their CV. Yields per-platform allocation distributions
  (mean / p5 / median / p95 / CV).
- **Source:** Empirical. 200 trials keeps total runtime under ~5 seconds
  on a typical 6-platform / 3-goal problem and produces p5 / p95
  estimates that are stable to within ~£10 across reruns with different
  seeds.
- **Sensitivity:** More trials → tighter percentile bands but linearly
  more runtime. Less than 100 trials gives visibly noisy p5/p95 (run-
  to-run variation of ~£100). More than 500 is wasted runtime for the
  precision the results page displays.

### Per-cell sigma clamp `[0.05, 1.00]`

- **Location:** `modules/module5.py:1317`
- **Role:** Bounds on the lognormal scale used to perturb each cell's
  productivity. Floor prevents zero-noise / false-precision; cap
  prevents trials from turning the LP into white noise.
- **Source:** Author-chosen sanity bounds matching the forecast band
  floor/cap (5% / 100%) so the two uncertainty treatments stay
  consistent.

### Instability threshold `DEFAULT_INSTABILITY_CV = 0.20`

- **Location:** `modules/module5.py:1243`
- **Role:** A platform whose allocation CV across MC trials exceeds 20%
  is flagged "unstable" — its rank ordering is sensitive to plausible
  perturbations of the input.
- **Source:** Industry convention for "the noise floor of meaningful
  campaign reporting." Allocation shifts within 20% are routinely
  attributable to attribution lag or weekly seasonality; shifts above
  20% indicate the recommendation itself is data-fragile.
- **Sensitivity:** Cosmetic — only affects the warning badge. The
  underlying MC distribution is unchanged.

---

## 8. Known limitations the constants don't address

A reviewer who reads the audit alongside this doc will notice we have
not calibrated against:

1. **Real campaign back-tests.** No deployment has yet produced a
   "ran the recommended allocation, measured the actual outcome,
   verified the LP outperformed by X%" report. The OR critique stands.
2. **Saturation curve shape per platform.** The yield brackets are
   uniform across platforms. In reality, Search (CPC auctions) and
   Display (CPM auctions) have different saturation shapes, and the
   brackets fit Display better than Search.
3. **Cross-platform audience overlap.** Spending £5k on Facebook and
   £5k on Instagram hits largely the same Meta audience; the LP
   treats them independently. No constant in this doc fixes that.
4. **Creative / fatigue decay.** Last-month productivity is treated
   as next-month productivity. Real-world decay is ignored.

These are model-structure issues, not constant-tuning issues. They are
listed here for honesty about scope.

---

## Override mechanisms

Every constant in this doc can be overridden without code changes for
deployments that have better data:

- `state.scenario_multipliers` (Module 2): overrides the budget
  scalars.
- `state.scenario_goal_multipliers` (Module 2): overrides the per-goal
  scenario tilts.
- `state.min_spend_per_platform` (Module 2): overrides the LP-level
  per-platform floors. (The vendor effective minimums are warnings;
  this is the LP constraint.)
- `state.test_and_learn_pct` (Module 1): controls the carve-out.
- `state.seasonality_index` (Module 1): per-goal seasonality
  multipliers on top of the scenarios.
- Monte Carlo: `n_trials`, `seed`, and `cv_floor` are exposed via the
  results-page button.

The only constants without a user-facing override are the structural
ones in §1 (yield brackets, OBJECTIVE_SCALE, solver tolerances) and
the shrinkage prior. Changing those requires a code change.
