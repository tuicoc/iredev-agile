"""Shared intake hint and Visionary support contract.

INTAKE_HINT is pre-submit user guidance for which details are most useful.
It reflects the kind of narrative input Visionary handles well: current
context, runtime roles, meaningful subgroups, boundaries, candidate shapes,
and desired outcomes.

VISIONARY_CONTRACT is the opening declaration of how to give Visionary a
strong intent and what Visionary will turn that intent into.

Both are surfaced by the CLI runner and the server's project intake endpoint
so both stay in sync.
"""

INTAKE_HINT = (
    "Write the product intent like a short product memo, not a feature checklist. "
    "Visionary handles narrative input well when it names:\n"
    "  - the current situation or friction people face today\n"
    "  - the runtime roles and any subgroups whose needs differ\n"
    "  - the kind of product or experience you are imagining, even if the shape is not fixed\n"
    "  - boundaries: what the product should sit beside, not replace, or not decide\n"
    "  - the outcome you hope changes for users, staff, customers, or other affected roles\n"
    "You can be uncertain. If you mention candidate ideas, competing audiences, "
    "or unresolved boundaries, Visionary will turn them into reviewable forks "
    "instead of forcing a premature decision."
)


VISIONARY_CONTRACT = (
    "## Start With Product Intent\n\n"
    "Visionary is strongest when your input reads like the AI Guidebook example: "
    "a few paragraphs about what is happening today, who is affected, where the "
    "line is unclear, what kind of product might help, and what the product must "
    "not replace.\n\n"
    "**Useful input shape:**\n"
    "- Name the runtime roles, including subgroups whose needs should not be flattened.\n"
    "- Describe today's behavior, confusion, workaround, or risk before the product exists.\n"
    "- Include candidate product ideas if you have them, but say when the shape is still open.\n"
    "- Name boundaries, source-of-truth systems, policies, authorities, or responsibilities the product should sit beside.\n"
    "- Say what outcome should improve, even if you do not know the exact feature yet.\n\n"
    "**What Visionary will do with that input:**\n"
    "- Separate concrete facts about today from desired future outcomes.\n"
    "- Build a role inventory and keep meaningful in-groups separate when the input signals different needs.\n"
    "- Produce a concise description, intent_summary, and target_outcome.\n"
    "- Surface first-release design forks as assumptions, each tagged stated / implied / inferred with an anchor.\n"
    "- Surface user-perceptible quality concerns and scope boundaries that downstream agents must respect.\n\n"
    "Visionary does not choose architecture, vendors, estimates, deadlines, or final requirements. "
    "Those belong to later agents after the vision, agenda, interview evidence, and requirement synthesis are reviewed."
)


def get_intake_hint() -> str:
    return INTAKE_HINT


def get_visionary_contract() -> str:
    return VISIONARY_CONTRACT
