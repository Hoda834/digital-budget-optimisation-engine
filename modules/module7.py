# app.py (minimal integration patch)
# 1) Add this import near the other imports
from modules.module7 import Module7BundleInsight, run_module7

# 2) Inside results_ui(state), after you build:
#    lp_by_scenario, fc_by_scenario, scenario_keys
#    add this block:

bundle = getattr(state, "module5_scenario_bundle", None)
module7_bundle: Optional[Module7BundleInsight] = None
if bundle is not None:
    try:
        module7_bundle = run_module7(state, bundle, fc_by_scenario)
    except Exception:
        module7_bundle = None

# 3) Still inside results_ui(state), before tabs are rendered (or right after Scenario comparison),
#    show a compact "Decision insights" section:

if module7_bundle is not None and module7_bundle.scenario_insights:
    st.subheader("Decision insights")
    st.caption(module7_bundle.global_stability_explanation)

    for sk in scenario_keys:
        ins = module7_bundle.scenario_insights.get(sk)
        if ins is None:
            continue
        st.markdown(f"**{_human_scenario_name(sk)}**")
        st.write(ins.executive_summary)

        if ins.risks:
            st.markdown("Risks")
            for r in ins.risks:
                st.write(f"- {r}")

        if ins.recommendations:
            st.markdown("Recommendations")
            for r in ins.recommendations:
                st.write(f"- {r}")

        st.divider()

# 4) Add Module 7 text into the PDF export
#    Update create_pdf_bytes signature to accept module7_bundle:

def create_pdf_bytes(
    state: WizardState,
    scenario_payload: List[Tuple[str, Module5LPResult, Optional[Module6Result]]],
    module7_bundle: Optional[Module7BundleInsight] = None,
) -> bytes:
    ...

# 5) In create_pdf_bytes, after "Policy Summary" tables and before the loop over scenarios, add:

if module7_bundle is not None and module7_bundle.scenario_insights:
    story.append(Paragraph("Decision Insights (Interpretation Layer)", styles["Heading2"]))
    story.append(Spacer(1, 6))
    story.append(Paragraph(module7_bundle.global_stability_explanation, styles["BodyText"]))
    story.append(Spacer(1, 10))

# 6) In the per scenario loop in create_pdf_bytes, right after "Scenario: X" heading,
#    inject the executive summary, risks, and recommendations:

ins = None
if module7_bundle is not None:
    ins = module7_bundle.scenario_insights.get(scenario_name)

if ins is not None:
    story.append(Paragraph("Executive insight summary", styles["Heading3"]))
    story.append(Paragraph(ins.executive_summary, styles["BodyText"]))
    story.append(Spacer(1, 6))

    if ins.risks:
        story.append(Paragraph("Risks", styles["Heading3"]))
        for r in ins.risks:
            story.append(Paragraph(f"- {r}", styles["BodyText"]))
        story.append(Spacer(1, 6))

    if ins.recommendations:
        story.append(Paragraph("Recommendations", styles["Heading3"]))
        for r in ins.recommendations:
            story.append(Paragraph(f"- {r}", styles["BodyText"]))
        story.append(Spacer(1, 10))

# 7) Finally, update the call site in results_ui(state) where pdf_bytes is created:

pdf_bytes = create_pdf_bytes(state, scenario_payload_for_exports, module7_bundle=module7_bundle)
