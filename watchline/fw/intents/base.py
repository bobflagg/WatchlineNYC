"""
watchline/fw/intents/base.py

Abstract base class for Watchline intent handlers.

Each intent is a self-contained module that owns:
  - Its Cypher query
  - Its parameter extraction logic
  - Its rule evaluation logic (if any)
  - Its traversal type identifier

The pipeline calls these methods in sequence:
  1. router.py resolves the entity and calls handler.get_params()
  2. execute_traversal runs handler.get_cypher() with those params
  3. execute_traversal calls handler.evaluate() on the raw results
  4. The rule_evaluation dict (if any) is merged into traversal_results
  5. narrator.py receives the full traversal_results and narrates
"""

from abc import ABC, abstractmethod


class IntentHandler(ABC):

    # Class-level constants — must be set by each subclass
    intent_category: str  # matches the intent_category string from identify_intent
    entity_class: str     # "building" or "actor"

    @abstractmethod
    def get_cypher(self) -> str:
        """Return the Cypher query string for this intent."""
        ...

    @abstractmethod
    def get_params(self, intent: dict) -> dict:
        """
        Extract Cypher parameters from the resolved intent dict.
        The intent dict at this point already has a resolved 'bbl' or
        'canonical_id' injected by the router.
        """
        ...

    def evaluate(self, raw_results: list) -> dict | None:
        """
        Apply rule logic to the raw Cypher results.

        Returns a rule_evaluation dict if this intent applies a named Rule,
        or None if the intent is purely a data retrieval (no rule to evaluate).

        Subclasses should override this only when a formal Rule applies.
        """
        return None

    def traversal_key(self) -> str:
        """
        Unique key for this handler in the traversal map.
        Default: '{entity_class}_{intent_category_lowercase}'.
        Override if needed.
        """
        return f"{self.entity_class}_{self.intent_category.lower()}"

    def not_supported_response(self) -> dict:
        """
        Returned by stub handlers for intents not yet implemented.
        The narrator receives this as traversal_results and explains gracefully.
        """
        return {
            "not_supported": True,
            "intent_category": self.intent_category,
            "message": (
                f"The '{self.intent_category}' intent is recognized by Watchline "
                f"but is not yet supported in this version. Check back soon."
            ),
        }
