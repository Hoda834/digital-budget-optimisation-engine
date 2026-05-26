# Test datasets

Five scenario folders, each with one CSV per selected platform
(columns match the per-platform import templates) and a
`SCENARIO.md` listing the wizard inputs to recreate the run.

1. `01_b2b_saas_leadgen/` — small budget, intent-led lead-gen mix.
2. `02_dtc_ecommerce_purchases/` — consumer purchases via PMax + Meta + TikTok + Pinterest.
3. `03_brand_launch_awareness/` — large upper-funnel-only video push.
4. `04_community_engagement/` — engagement-led social mix; stresses the composition layer.
5. `05_omnichannel_all_goals/` — all four objectives, eight platforms, long history.

Regenerate with:

```bash
PYTHONPATH=. python test_datasets/_generate.py
```
