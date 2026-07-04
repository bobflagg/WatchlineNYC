"""
watchline/fw/intents/__init__.py

Intent handler registry. Maps intent_category strings to handler instances.

To add a new intent:
  1. Create watchline/fw/intents/<name>.py with a class extending IntentHandler
  2. Import it here and add it to REGISTRY
  3. Remove the corresponding stub from stubs.py
"""

from watchline.fw.intents.deterioration import DeteriorationTrajectoryHandler
from watchline.fw.intents.stubs import (
    PortfolioIdentificationHandler,
    PortfolioConditionHandler,
    RecidivismHandler,
    WorstFirstHandler,
    ConcealmentDetectionHandler,
    EnforcementAccountabilityHandler,
    GeographicConcentrationHandler,
    OwnershipChangeHandler,
    BuildingDueDiligenceHandler,
    RentStabilizationHandler,
    FineEvasionHandler,
    GeneralHandler,
)

# Instantiate once at import time — handlers are stateless
REGISTRY: dict[str, object] = {
    h.intent_category: h
    for h in [
        DeteriorationTrajectoryHandler(),
        PortfolioIdentificationHandler(),
        PortfolioConditionHandler(),
        RecidivismHandler(),
        WorstFirstHandler(),
        ConcealmentDetectionHandler(),
        EnforcementAccountabilityHandler(),
        GeographicConcentrationHandler(),
        OwnershipChangeHandler(),
        BuildingDueDiligenceHandler(),
        RentStabilizationHandler(),
        FineEvasionHandler(),
        GeneralHandler(),
    ]
}
