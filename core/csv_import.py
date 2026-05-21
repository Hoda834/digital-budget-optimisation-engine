"""CSV import helpers for Module 3 inputs.

Marketers don't want to type KPI numbers; they want to drop in the CSV
export they already have from their ad platform.  Each platform uses a
different schema, so column-matching here is deliberately heuristic:

* case-insensitive
* substring match (so "Amount Spent (GBP)" matches "amount spent")
* counts are summed across all matching rows
* rates are averaged
* percent strings ("4.5%", "0.045") both work

Coverage: Meta (FB / IG), Google Ads, LinkedIn Campaign Manager, TikTok,
YouTube.  The other platforms in the catalogue have less standardised
exports; manual entry remains the path for those.
"""
from __future__ import annotations

import csv
import io
from typing import Any, Dict, List, Optional, Tuple, Union


# Column-name patterns per platform.  Order within the list matters: the
# first match wins, so put more specific needles before generic ones.
# Keys starting with "_" are pseudo-KPIs (budget, historical_days) that
# get returned alongside the KPI values.
_CSV_PATTERNS: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "fb": {
        "FB_AW_REACH":      ("reach",),
        "FB_AW_IMPRESSION": ("impression",),
        "FB_EN_ENGAGEMENT": ("post engagement", "engagement"),
        "FB_WT_CLICKS":     ("link click", "outbound click", "click (all)"),
        "FB_LG_LEADS":      ("on-facebook lead", "leads", "lead"),
        "_budget":          ("amount spent", "spend", "cost"),
        "_days":            ("number of days", "days"),
    },
    "ig": {
        "IG_AW_REACH":       ("reach",),
        "IG_EN_ENGRATERATE": ("engagement rate", "er"),
        "IG_WT_CLICKS":      ("link click", "outbound click"),
        "IG_LG_LEADS":       ("leads", "lead"),
        "_budget":           ("amount spent", "spend", "cost"),
        "_days":             ("number of days", "days"),
    },
    "li": {
        "LI_AW_REACH":       ("impression",),  # LinkedIn reports Impressions, not Reach
        "LI_EN_ENGRATERATE": ("engagement rate", "average ctr"),
        "LI_WT_CLICKS":      ("click",),
        "LI_LG_LEADS":       ("leads", "lead"),
        "_budget":           ("total spent", "amount spent", "spend", "cost"),
        "_days":             ("number of days", "days"),
    },
    "go": {
        "GO_AW_IMPRESSION":  ("impr.", "impressions", "impression"),
        "GO_EN_CTR":         ("ctr",),
        "GO_WT_CLICKS":      ("clicks", "click"),
        "GO_LG_CONVERSIONS": ("conversions", "conv."),
        "_budget":           ("cost", "spend"),
        "_days":             ("number of days", "days"),
    },
    "tt": {
        "TT_AW_VIEWS":       ("video views", "views"),
        "TT_EN_ENGRATERATE": ("engagement rate", "er"),
        "TT_WT_CLICKS":      ("destination click", "clicks"),
        "TT_LG_LEADS":       ("leads", "lead"),
        "_budget":           ("cost", "spend"),
        "_days":             ("number of days", "days"),
    },
    "yt": {
        "YT_AW_VIEWS":       ("views",),
        "YT_EN_ENGRATERATE": ("view rate", "engagement rate"),
        "YT_WT_CLICKS":      ("clicks", "click"),
        "YT_LG_LEADS":       ("conversions", "leads"),
        "_budget":           ("cost", "spend"),
        "_days":             ("number of days", "days"),
    },
}


_RATE_KPIS = {
    "IG_EN_ENGRATERATE", "LI_EN_ENGRATERATE",
    "GO_EN_CTR", "TT_EN_ENGRATERATE", "YT_EN_ENGRATERATE",
}


SUPPORTED_PLATFORMS: Tuple[str, ...] = tuple(_CSV_PATTERNS.keys())


def _normalise(s: str) -> str:
    """Lowercase + collapse separators so 'Amount_Spent (GBP)' matches 'amount spent'."""
    return (
        str(s or "")
        .strip()
        .lower()
        .replace("_", " ")
        .replace("-", " ")
        .replace("(gbp)", "")
        .replace("(usd)", "")
        .replace("(eur)", "")
        .replace("£", "")
        .strip()
    )


def _parse_number(raw: Any) -> Optional[float]:
    """Parse a single cell into a float; handle %, thousand separators, blanks."""
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "").replace("£", "").replace("$", "").replace("€", "")
    if not s or s.lower() in ("--", "n/a", "na", "none"):
        return None
    is_percent = s.endswith("%")
    if is_percent:
        s = s[:-1].strip()
    try:
        v = float(s)
    except ValueError:
        return None
    if is_percent:
        v = v / 100.0
    return v


def _aggregate(rows: List[Dict[str, Any]], col: str, op: str) -> Optional[float]:
    """Reduce a column to a scalar.  op ∈ {'sum', 'mean', 'first', 'max'}.

    For rates that arrive as "1.23%" or 0.0123, we normalise during parsing
    so the LP receives values in [0, 1] regardless of how the platform
    decided to print them.
    """
    vals: List[float] = []
    for row in rows:
        v = _parse_number(row.get(col))
        if v is not None:
            vals.append(v)
    if not vals:
        return None
    if op == "mean":
        return sum(vals) / len(vals)
    if op == "first":
        return vals[0]
    if op == "max":
        return max(vals)
    return sum(vals)


def parse_platform_csv(
    content: Union[bytes, str],
    platform: str,
) -> Dict[str, Any]:
    """Parse a CSV export for one platform.

    Returns a dict with the shape Module 3 expects per platform:
        {
          "budget": <float>,
          "historical_days": <int or None>,
          "kpis": {VAR: value, ...},
          "matched_columns": {VAR: column_name, ...},   # for the UI to show
          "missing_kpis": [VAR, ...],                    # what we couldn't find
        }

    Returns {"error": "..."} on a parse failure so the caller can show it.
    """
    plat = (platform or "").strip().lower()
    if plat not in _CSV_PATTERNS:
        return {"error": f"CSV import is not supported for platform {plat!r}. "
                f"Supported: {', '.join(SUPPORTED_PLATFORMS)}."}

    if isinstance(content, bytes):
        for enc in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                content = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            return {"error": "Could not decode CSV — try saving as UTF-8."}

    try:
        # Sniff delimiter (Google sometimes exports with semicolons in European locales)
        sample = content[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(content), dialect=dialect)
        rows = [r for r in reader if any((v or "").strip() for v in r.values())]
    except (csv.Error, ValueError) as e:
        return {"error": f"Could not parse CSV: {e}"}

    if not rows:
        return {"error": "CSV is empty or has no data rows."}

    # Build {normalised → actual} column-name index
    column_index: Dict[str, str] = {}
    for col in rows[0].keys():
        if col is None:
            continue
        column_index.setdefault(_normalise(col), col)

    def _find(needles: Tuple[str, ...]) -> Optional[str]:
        for needle in needles:
            n = _normalise(needle)
            for norm_col, real_col in column_index.items():
                if n in norm_col:
                    return real_col
        return None

    patterns = _CSV_PATTERNS[plat]
    kpis: Dict[str, float] = {}
    matched: Dict[str, str] = {}
    missing: List[str] = []

    budget_val: Optional[float] = None
    days_val: Optional[int] = None

    for var, needles in patterns.items():
        col = _find(needles)
        if col is None:
            if not var.startswith("_"):
                missing.append(var)
            continue

        if var == "_budget":
            budget_val = _aggregate(rows, col, "sum")
            matched["budget"] = col
        elif var == "_days":
            d = _aggregate(rows, col, "first")
            if d is not None:
                days_val = int(d)
                matched["historical_days"] = col
        else:
            op = "mean" if var in _RATE_KPIS else "sum"
            v = _aggregate(rows, col, op)
            if v is not None and v > 0:
                kpis[var] = v
                matched[var] = col

    return {
        "budget": budget_val,
        "historical_days": days_val,
        "kpis": kpis,
        "matched_columns": matched,
        "missing_kpis": missing,
        "row_count": len(rows),
    }
