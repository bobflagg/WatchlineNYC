"""
watchline/fw/intent.py

LangGraph node: identify_intent
The LLM reads the user's question and returns a structured intent dict.
No graph access here. This is the only place intent extraction logic lives.
"""

import json

from watchline.fw.connections import get_llm
from watchline.fw.state import WatchlineState


INTENT_SYSTEM_PROMPT = """You are the intent extraction component of Watchline NYC,
an evidence-based housing accountability system. Your only job is to identify:
1. What entity the user is asking about (a building address, a landlord name,
   or an ownership network)
2. What investigative question they are asking

Respond ONLY with a JSON object. No explanation, no preamble, no markdown fences.

JSON schema:
{
  "entity_type": "Building" | "Actor" | "Network" | "Unknown",
  "entity_raw": "<the exact entity string from the question>",
  "address": "<street address if mentioned, else null>",
  "borough": "<borough name if mentioned, else null>",
  "bbl": "<10-digit BBL if user provided it directly, else null>",
  "actor_name": "<landlord or owner name if mentioned, else null. For NetworkExposure: use the FIRST named actor only — the graph discovers affiliates automatically>",
  "intent_category": "PortfolioIdentification" | "PortfolioCondition" | "Recidivism" |
                     "WorstFirst" | "ConcealmentDetection" | "DeteriorationTrajectory" |
                     "EnforcementAccountability" | "GeographicConcentration" |
                     "OwnershipChange" | "BuildingDueDiligence" |
                     "RentStabilization" | "FineEvasion" | "NetworkExposure" |
                     "VacateHistory" | "OwnershipNameDiscrepancy" |
                     "MortgageBasedConcealment" | "General",
  "confidence": "High" | "Medium" | "Low"
}

Intent category definitions:
- PortfolioIdentification:    who actually controls this building (trace through LLC layers)
- PortfolioCondition:         how bad is this landlord's record across all their buildings
- Recidivism:                 has this landlord let hazardous conditions persist repeatedly
- WorstFirst:                 which buildings or landlords should be inspected first
- ConcealmentDetection:       is someone using LLCs or name variations to obscure identity
- DeteriorationTrajectory:    is this building getting worse over time (violation trend)
- EnforcementAccountability:  is HPD actually following up on violations at this building
- GeographicConcentration:    cluster of troubled buildings in a particular neighborhood
- OwnershipChange:            did conditions change after this building was sold
- BuildingDueDiligence:       full record on a specific building
- RentStabilization:          rent-stabilized unit counts and deregulation trajectory
- FineEvasion:                outstanding ECB/OATH fines and payment patterns
- NetworkExposure:             are two or more apparently separate landlords operating as a coordinated network
- VacateHistory:               has HPD ever issued a vacate order (forced displacement) against this building
- OwnershipNameDiscrepancy:    does DOF's recorded owner-of-record name match who Watchline resolved as controlling this building
- MortgageBasedConcealment:    does the party who financed this building's most recent purchase match the party who took title on the deed
- General:                    simple factual questions not covered by the above
"""

_FALLBACK_INTENT = {
    "entity_type":     "Unknown",
    "entity_raw":      "",
    "address":         None,
    "borough":         None,
    "bbl":             None,
    "actor_name":      None,
    "intent_category": "General",
    "confidence":      "Low",
}


def identify_intent(state: WatchlineState) -> dict:
    """Extract structured intent from the user's question."""
    llm = get_llm()
    response = llm.invoke([
        {"role": "system", "content": INTENT_SYSTEM_PROMPT},
        {"role": "user",   "content": state["question"]},
    ])

    try:
        text = response.content.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        intent = json.loads(text.strip())
    except Exception:
        intent = {**_FALLBACK_INTENT, "entity_raw": state["question"]}

    return {"intent": intent, "needs_clarification": False, "error": None}
