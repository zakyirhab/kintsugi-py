"""
Example 04: Enterprise Mode (mode="propose") & Secret Redaction
Demonstrates how to use Kintsugi safely in production pipelines where
automated hot-swapping is restricted. Instead, Kintsugi validates the patch,
redacts secrets, and generates a HealReport for human approval.
"""

import logging
from kintsugi import heal, HealReport, ProposedPatchError

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def notify_slack_channel(report: HealReport):
    print("\n" + "=" * 60)
    print("📢 [SLACK ALERT] Proposed Autonomous Fix Ready for Review!")
    print(f"Target Function: `{report.func_name}`")
    print(f"Trigger Exception: {report.error_type} - {report.error_message}")
    print(f"Attempts to Repair: {report.attempts} via {report.provider} ({report.model})")
    print("\nUnified Diff:")
    print(report.diff)
    print("=" * 60 + "\n")


@heal(
    mode="propose",                   # Does NOT hot-swap in memory; generates proposal
    on_heal=notify_slack_channel,     # Sends diff to team
    signature_only=True,              # Privacy: Only send arg types/shapes, no real customer data
    validate=lambda res: len(res) > 0 # Catch silent empty results
)
def extract_partner_catalog(payload: dict) -> list:
    """Brittle catalog extractor containing sensitive user context."""
    # Suppose payload structure changed from 'products' to 'items'
    return payload["products"]


if __name__ == "__main__":
    # Payload contains dirty/changed keys and sensitive customer tokens
    raw_payload = {
        "items": ["Laser Scanner 3D", "Robotic Arm v2"],
        "customer_api_key": "sk-production_super_secret_token_1234567890",
        "customer_email": "admin@defense-contractor.gov",
    }

    try:
        extract_partner_catalog(raw_payload)
    except ProposedPatchError as err:
        print(f"Caught ProposedPatchError as expected in mode='propose':\n{err}")
        print("Function remains untouched in memory. Safe for high-compliance environments!")
