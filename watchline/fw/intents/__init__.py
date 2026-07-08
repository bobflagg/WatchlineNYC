"""
watchline/fw/intents/__init__.py

Intent handler registry. Maps intent_category strings to handler instances.

To add a new intent:
  1. Create watchline/fw/intents/<name>.py with a class extending IntentHandler
  2. Import it here and add it to REGISTRY
  3. Remove the corresponding stub from stubs.py
"""

from watchline.fw.intents.deterioration import DeteriorationTrajectoryHandler
from watchline.fw.intents.portfolio_identification import PortfolioIdentificationHandler
from watchline.fw.intents.building_due_diligence import BuildingDueDiligenceHandler
from watchline.fw.intents.rent_stabilization import RentStabilizationHandler
from watchline.fw.intents.fine_evasion import FineEvasionHandler
from watchline.fw.intents.portfolio_condition import PortfolioConditionHandler
from watchline.fw.intents.worst_first import WorstFirstHandler
from watchline.fw.intents.enforcement_accountability import EnforcementAccountabilityHandler
from watchline.fw.intents.recidivism import RecidivismHandler
from watchline.fw.intents.concealment_detection import ConcealmentDetectionHandler
from watchline.fw.intents.geographic_concentration import GeographicConcentrationHandler
from watchline.fw.intents.network_exposure import NetworkExposureHandler
from watchline.fw.intents.stubs import (
    OwnershipChangeHandler,
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
        GeographicConcentrationHandler(),
        OwnershipChangeHandler(),
        BuildingDueDiligenceHandler(),
        RentStabilizationHandler(),
        FineEvasionHandler(),
        EnforcementAccountabilityHandler(),
        NetworkExposureHandler(),
        GeneralHandler(),
    ]
}
