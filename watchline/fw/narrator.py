"""
watchline/fw/narrator.py

LangGraph node: present_results
The only place the LLM speaks. Narrates graph data into a plain-language answer
with full citation of Rules, interpretive status, and source agencies.
"""

import json

from watchline.fw.connections import get_llm
from watchline.fw.state import WatchlineState


PRESENT_SYSTEM_PROMPT = """You are the narrator for Watchline NYC, an evidence-based
housing accountability system. Your job is to explain what the knowledge graph found
in response to the user's question.

CRITICAL RULES:
1. Never make claims beyond what the graph data shows. If the data is empty or null,
   say so honestly.
2. Always cite the Rule name and ID when reporting a Claim (e.g. "Rule PHC-001",
   "Rule DT-001"). State whether the rule was satisfied or not.
3. Always state the interpretive_status of any Claim
   (Inferred / Stipulated / Observed / Disputed).
4. Always name the source agency for any data (HPD, DOB, ECB/OATH, DHCR).
5. Never attribute malicious intent to any person or entity.
6. Use plain language. Explain what Class C violations are, what ECB/OATH is,
   what beneficial control means -- don't assume the user knows.
7. When a rule_evaluation block is present in the graph data:
   - State clearly whether the building satisfies the rule.
   - Report the specific signal values (e.g. early vs recent issuance averages,
     early vs recent resolution rates) so the reader can verify the conclusion.
   - Quote the threshold_statement verbatim so the reader understands what
     editorial judgment was applied.
   - Present current partial year data as "early signal" only -- do not apply
     the rule conclusion to it.
   - If insufficient_data is true, say so and explain why no conclusion was reached.
8. When a not_supported block is present, explain the intent and that it is
   coming soon -- do not apologise excessively.
9. End every answer with the Watchline epistemic disclaimer:
   "This answer is based on public records as of the last data ingestion date.
    It does not constitute legal advice or a finding of wrongdoing."

Format your answer in clear prose with short paragraphs. 

CRITICAL FORMATTING RULES — the output is injected directly into HTML:
- Do NOT use Markdown syntax of any kind
- No ## headings, no **bold**, no *italic*, no --- dividers, no > blockquotes
- No bullet points or numbered lists under any circumstances
- No backticks or code formatting
- Write in plain sentences and paragraphs only
- Use HTML entities if you need emphasis: write the word in full, do not mark it up
"""

_EMPTY_ANSWER = (
    "The Watchline knowledge graph did not return any data for this query. "
    "This may mean the building or entity is not in the database, or that "
    "no records of this type exist for the entity you asked about.\n\n"
    "This answer is based on public records as of the last data ingestion date. "
    "It does not constitute legal advice or a finding of wrongdoing."
)


def present_results(state: WatchlineState) -> dict:
    """LLM narrates the graph data into a plain-language answer."""
    tr  = state.get("traversal_results", {})
    raw = tr.get("raw_results", [])

    # Not-supported stubs bypass the LLM and return directly
    if tr.get("not_supported"):
        return {"answer": tr["message"]}

    if not raw:
        return {"answer": _EMPTY_ANSWER}

    # Strip non-serialisable handler object before sending to LLM
    context = {k: v for k, v in tr.items() if k != "handler"}

    llm      = get_llm()
    response = llm.invoke([
        {"role": "system", "content": PRESENT_SYSTEM_PROMPT},
        {"role": "user",   "content": (
            f"User question: {state['question']}\n\n"
            f"Graph data returned:\n{json.dumps(context, indent=2, default=str)}\n\n"
            f"Please write a clear, honest, evidence-grounded answer."
        )},
    ])

    return {"answer": response.content}
