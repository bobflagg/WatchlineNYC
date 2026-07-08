"""
watchline/fw/intents/stubs.py

Stub IntentHandlers for intents that are recognized but not yet implemented.
Each stub returns a not_supported_response so the narrator can explain gracefully
rather than the pipeline crashing or silently returning empty results.

Replace each stub with a full handler module as the intent is implemented.
"""

from watchline.fw.intents.base import IntentHandler


class _Stub(IntentHandler):
    """Generic stub — subclass and set intent_category and entity_class."""

    def get_cypher(self) -> str:
        return ""

    def get_params(self, intent: dict) -> dict:
        return {}

    def evaluate(self, raw_results: list) -> dict | None:
        return None


class OwnershipChangeHandler(_Stub):
    intent_category = "OwnershipChange"
    entity_class    = "building"


class GeneralHandler(_Stub):
    intent_category = "General"
    entity_class    = "building"
