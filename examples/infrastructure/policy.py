"""Infrastructure change control -- the flagship example.

This is the clearest case for deterministic governance, because the proposed
action is unambiguously consequential: an agent asks to delete a volume, and
either it is deleted or it is not. There is no interpretive middle ground
about whether the output was "appropriate".

Four properties, in the order they are checked:

1. **Reversibility.** Can the prior state be restored? The interesting
   value is not "no" -- it is *unknown*. An action whose recoverability
   could not be established gates as if it were permanent. Not knowing
   whether something can be undone is not evidence that it can, and any
   other choice lets a failed lookup widen autonomy, turning an outage in
   the read path into an escalation bypass.

2. **Blast radius.** How many resources does this affect? A ceiling is a
   crude control and an effective one: most catastrophic changes are
   ordinary changes applied to far more things than intended.

3. **Environment.** Production is not a risk score. It is a different
   authority regime, and the same action can be routine in staging and
   require a second human in production.

4. **Approval.** Checked against `context`, never against the proposal.
   A proposal claiming `"approved": true` is an agent asserting its own
   authority, which is the one input a gate must never take at face value.

`policy_version` is bumped on any rule change. It is recorded in every
decision, so a replay that disagrees can distinguish "the policy changed"
from "the answer changed".
"""
from __future__ import annotations

from typing import Any, Mapping

from governance_core.decision import Decision, Outcome, decide

POLICY_ID = "infrastructure.change"
POLICY_VERSION = "1.0.0"

#: Resources one change may touch before it needs a human, per environment.
#: Production is tighter because the cost of "more than I meant" is higher,
#: not because production actions are inherently riskier.
BLAST_RADIUS_CEILING: dict[str, int] = {"production": 5, "staging": 50, "dev": 500}

#: Recoverability tiers, ordered. `None`/absent means "could not establish",
#: which deliberately gates as IRREVERSIBLE.
REVERSIBLE = "REVERSIBLE"
COMPENSABLE = "COMPENSABLE"
IRREVERSIBLE = "IRREVERSIBLE"

#: Actions that destroy state no backup restores. Listed explicitly rather
#: than matched on the word "delete": `delete_stale_cache_entry` is not in
#: this class, and a substring rule would catch it. (The repository this
#: example grew out of hit exactly that bug -- a rollback gate that denied on
#: the substring "delete".)
UNCONDITIONALLY_IRREVERSIBLE = frozenset(
    {"delete_snapshot", "purge_backup", "destroy_key_material"}
)


def _ceiling(environment: str) -> int:
    # An unrecognised environment gets the strictest ceiling, not the
    # loosest. A typo in an environment name must not buy more authority.
    return BLAST_RADIUS_CEILING.get(environment, BLAST_RADIUS_CEILING["production"])


class InfrastructureChangePolicy:
    """Deterministic gate for a proposed infrastructure change."""

    policy_id = POLICY_ID
    policy_version = POLICY_VERSION

    def evaluate(
        self, proposal: Mapping[str, Any], context: Mapping[str, Any]
    ) -> Decision:
        def verdict(outcome: Outcome, *reasons: str) -> Decision:
            return decide(
                outcome,
                policy_id=self.policy_id,
                policy_version=self.policy_version,
                proposal=proposal,
                context=context,
                reasons=reasons,
            )

        action = str(proposal.get("action", ""))
        environment = str(proposal.get("environment", "production"))
        blast_radius = proposal.get("blast_radius")
        reversibility = proposal.get("reversibility")

        # -- 1. Reversibility ------------------------------------------------
        if action in UNCONDITIONALLY_IRREVERSIBLE:
            reversibility = IRREVERSIBLE

        if reversibility is None:
            return verdict(
                Outcome.ESCALATE,
                f"REVERSIBILITY_UNDETERMINED: could not establish whether "
                f"'{action}' on {proposal.get('resource_id', '<unknown>')} can be "
                "undone; an unestablished recovery path gates as permanent",
            )

        if reversibility == IRREVERSIBLE and environment == "production":
            return verdict(
                Outcome.DENY,
                f"IRREVERSIBLE_IN_PRODUCTION: '{action}' destroys state with no "
                "recovery path this policy can verify; a production change that "
                "cannot be undone is not admissible without a different decision",
            )

        # -- 2. Blast radius -------------------------------------------------
        if blast_radius is None:
            return verdict(
                Outcome.ESCALATE,
                "BLAST_RADIUS_UNKNOWN: the number of affected resources was not "
                "supplied, so the ceiling cannot be applied",
            )

        ceiling = _ceiling(environment)
        if int(blast_radius) > ceiling:
            return verdict(
                Outcome.DENY,
                f"BLAST_RADIUS_EXCEEDED: {blast_radius} resources affected in "
                f"{environment}, ceiling is {ceiling}",
            )

        # -- 3/4. Environment and approval -----------------------------------
        # Approval is read from context, which the caller supplies from its
        # own records. Anything the proposal says about its own approval is
        # ignored: an agent cannot authorise itself.
        approvals = context.get("approvals") or []
        has_human_approval = bool(approvals)

        if environment == "production" and reversibility == COMPENSABLE:
            if not has_human_approval:
                return verdict(
                    Outcome.ESCALATE,
                    f"COMPENSABLE_IN_PRODUCTION_NEEDS_APPROVAL: '{action}' is "
                    "recoverable but not exactly reversible (the data survives, "
                    "the identity does not), and no approval is recorded",
                )

        if environment == "production" and not context.get("change_window_open", True):
            return verdict(
                Outcome.ESCALATE,
                "OUTSIDE_CHANGE_WINDOW: production changes outside the declared "
                "window need a human to accept the timing",
            )

        return verdict(Outcome.APPROVE)
