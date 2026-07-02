"""
deedwatch_agent.py
==================
A LangChain DeepAgent that answers questions about NYC landlord accountability
by querying the DeedWatch knowledge graph (Neo4j) and augmenting with live
web search (Tavily).

Every Cypher query and every web search issued during a run is captured and
printed in a transparent provenance block at the end of every answer.

Usage
-----
    # 1. Set credentials
    export NEO4J_URI="bolt://<host>:7687"
    export NEO4J_USERNAME="neo4j"
    export NEO4J_PASSWORD="<password>"
    export ANTHROPIC_API_KEY="<key>"
    export TAVILY_API_KEY="<key>"           # optional — web search disabled without it

    # 2. Run
    python deedwatch_agent.py

    # 3. Or import and call programmatically
    from deedwatch_agent import run_question
    answer = run_question("Who owns 123 Main St Brooklyn and how many violations do they have?")

Dependencies
------------
    pip install deepagents langchain-anthropic neo4j tavily-python
"""

from __future__ import annotations

import json
import os
import textwrap
from datetime import datetime
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from dotenv import load_dotenv
load_dotenv()


# ─────────────────────────────────────────────
# Live schema snapshot (fetched from graph at
# build time; also returnable as a tool call)
# ─────────────────────────────────────────────

SCHEMA_SNAPSHOT = textwrap.dedent("""
    ╔══════════════════════════════════════════════════════════════════╗
    ║               DEEDWATCH NEO4J SCHEMA  (live snapshot)           ║
    ╚══════════════════════════════════════════════════════════════════╝

    NODE TYPES  (label → count → properties)
    ─────────────────────────────────────────
    Property  [858 602]
        bbl* address borough bldgclass landuse unitsres unitstotal yearbuilt
        assesstot ownertype ownername latitude longitude cd ct2010 zipcode
        numbldgs numfloors version
        tax_lien_has_tax_debt tax_lien_latest_date tax_lien_latest_cycle
        tax_lien_final_sale tax_lien_tax_class
        rentstab_units2007 rentstab_units2017..2023 rentstab_diff
        rentstab_percentchange rentstab_source2018..2023
        rentstab_j51 rentstab_a421 rentstab_c420 rentstab_scrie rentstab_drie
        (* = unique index; bbl is the primary key)

    SuspiciousProperty  [32]  — co-label on Property nodes
        same properties as Property PLUS:  risk_score

    Person  [6 460 417]
        nodeid* name address entity_type source bbls splink_cluster_id

    Corporation  [1 464 458]
        nodeid* name address entity_type source bbls splink_cluster_id

    Portfolio  [97 451]
        portfolioId* bbls landlordNames origId size

    Violation  [11 018 256]  — HPD housing code
        violationid* novid novtype class novdescription
        novissueddate inspectiondate approveddate
        originalcorrectbydate currentstatus currentstatusdate
        violationstatus rentimpairing ordernumber story registrationid
        ⚠️  TWO SEPARATE STATUS FIELDS — do not confuse them:
          violationstatus : 'Open' | 'Close'   ← use this to filter open vs closed
          currentstatus   : free-text audit trail value, e.g. 'NOV SENT OUT',
                            'VIOLATION CLOSED', 'VIOLATION DISMISSED',
                            'NOT COMPLIED WITH', 'FIRST NO ACCESS TO RE-INSPECT...'
                            currentstatus <> 'Close' is WRONG — 'Close' never appears here
        ⚠️  `class` is a reserved word — always quote it: v.`class`
        Indexes: (violationid) unique; (class, violationstatus) composite — use both
                 fields together in WHERE for index-backed filtering

    DobViolation  [2 460 501]  — DOB/buildings
        isn* violation_number violation_type_code violation_category
        issue_date disposition_date description is_active

    EcbViolation  [1 789 287]  — OATH/ECB fines
        ecb_violation_number* ecb_violation_status dob_violation_number
        issue_date hearing_date hearing_status severity violation_type
        violation_description respondent_name
        penalty_imposed amount_paid balance_due

    HpdLitigation  [238 755]  — HP court cases
        litigation_id* building_id case_type case_status respondent
        harassment_found open_judgement
        (note: no "penalty" field in current data)

    Eviction  [100 424]  — marshal records
        court_index_number* docket_number executed_date
        residential_or_commercial eviction_type is_ejectment
        eviction_apt_num marshal_first_name marshal_last_name

    DeedTransaction  [3 815 054]  — ACRIS deeds
        document_id* doc_type doc_date recorded_date amount pct_transferred crfn

    MortgageTx  [5 207 703]  — ACRIS mortgages
        document_id* doc_type doc_date recorded_date amount crfn is_cema

    DosFiling  [258 558]  — NY DOS corp records
        dosid* currententityname entitytype initialdosfilingdate
        dosprocessname dosprocessaddress dosprocesscity dosprocessstate dosprocesszip
        registeredagentname registeredagentaddress registeredagentcity
        registeredagentstate registeredagentzip

    RegisteredAgent  [236 479]
        name address city state zip entity_count is_commercial_agent

    MotifHit  [104]  — deed-pattern detections
        hit_id motif_type detected_at days_to_complete delta_days_used
        deed1_doc_id deed1_date deed1_amount
        mortgage_doc_id mortgage_date mortgage_amount
        deed2_doc_id deed2_date deed2_amount
        intermediate_llc final_grantee lender_name
        score_timing score_equity_extraction score_rs_loss
        score_violations score_harassment score_shell_llc
        risk_score

    RELATIONSHIP TYPES  (count → pattern)
    ──────────────────────────────────────
    HAS_VIOLATION        [10 996 524]  (Property|SuspiciousProperty) → Violation
    HAS_DOB_VIOLATION    [ 2 254 334]  (Property|SuspiciousProperty) → DobViolation
    HAS_ECB_VIOLATION    [ 1 683 723]  (Property|SuspiciousProperty) → EcbViolation
    HAS_LITIGATION       [   238 260]  (Property|SuspiciousProperty) → HpdLitigation
    HAS_EVICTION         [    99 435]  (Property|SuspiciousProperty) → Eviction
    COVERED_BY           [ 8 022 308]  (Property|SuspiciousProperty) → DeedTransaction|MortgageTx
    BELONGS_TO           [   171 324]  (Property|SuspiciousProperty) → Portfolio
    CONTROLS             [   118 487]  (Person|Corporation)          → Portfolio
    GRANTED_BY           [ 6 142 527]  DeedTransaction → (Person|Corporation)
    GRANTED_TO           [ 6 045 339]  DeedTransaction → (Person|Corporation)
    MORTGAGOR_IN         [ 8 284 418]  (Person|Corporation) → MortgageTx
    MORTGAGEE_IN         [ 5 805 708]  (Person|Corporation) → MortgageTx
    FILED_AS             [   330 450]  Corporation → DosFiling
        props: match_method
    HAS_REGISTERED_AGENT [   283 525]  DosFiling → RegisteredAgent
        props: source
    SAME_AS              [ 1 480 565]  (Person↔Person) | (Corporation↔Corporation)
        props: source  match_probability
    SIMILAR_TO           [   283 752]  Person ↔ (Person|Corporation)
        props: connection_type  weight
    FLAGGED_PROPERTY     [       106]  MotifHit → (Property|SuspiciousProperty)
    INVOLVES_TRANSACTION [       312]  MotifHit → (DeedTransaction|MortgageTx)
    RELATED_TO           [        14]  (purpose unclear — avoid)

    KEY CONVENTIONS
    ───────────────
    BBL format  : string, zero-padded  "{borough}{block:05d}{lot:04d}"
                  e.g. Manhattan block 123 lot 45  →  "1001230045"
    Borough codes: 1=Manhattan  2=Bronx  3=Brooklyn  4=Queens  5=Staten Island
    Violation class:  A=non-hazardous  B=hazardous  C=immediately hazardous
    Open violation filter:  WHERE v.`class` = 'C' AND v.violationstatus = 'Open'
        ✗ WRONG:  v.currentstatus <> 'Close'   ('Close' is not a currentstatus value)
        ✓ RIGHT:  v.violationstatus = 'Open'    (values are exactly 'Open' or 'Close')
    `class` is a Cypher reserved word — always backtick it: v.`class`
    Performance: traverse FROM the filtered violation side TO portfolio, not the reverse
        ✓ FAST:  MATCH (v:Violation)<-[:HAS_VIOLATION]-(p:Property)-[:BELONGS_TO]->(port:Portfolio)
        ✗ SLOW:  MATCH (port:Portfolio)<-[:BELONGS_TO]-(p:Property)-[:HAS_VIOLATION]->(v:Violation)
    Always add LIMIT (default ≤ 25) — some patterns touch millions of edges
    Use OPTIONAL MATCH for CONTROLS edges so portfolios without controllers still appear
    Case-insensitive name search:  toLower(n.name) CONTAINS toLower($term)
    rentstab_diff < 0  →  net loss of rent-stabilised units
""").strip()


def get_schema() -> str:
    """
    Return the complete DeedWatch Neo4j schema: every node label with its
    property names, every relationship type with direction and edge count,
    and key query conventions (BBL format, borough codes, LIMIT rules).

    Call this FIRST before writing any Cypher query.  The schema tells you
    the exact property names to use — guessing them is the leading cause of
    failed queries (e.g. the field is `class`, not `violation_class`; it is
    `novissueddate`, not `issued_date`; HpdLitigation has no `penalty` field).
    """
    return SCHEMA_SNAPSHOT


# ─────────────────────────────────────────────
# Neo4j tool
# ─────────────────────────────────────────────

def run_cypher(query: str, params: dict | None = None) -> str:
    """
    Execute a read-only Cypher query against the DeedWatch Neo4j graph.

    Always call get_schema() before your first run_cypher() call so you use
    the correct property names and relationship directions.

    Tips
    ----
    - Match properties by BBL:  MATCH (p:Property {bbl: $bbl})
    - Match by address fragment: WHERE toLower(p.address) CONTAINS toLower($addr)
    - Violation class filter:   WHERE v.`class` = 'C'
    - Open violations:          WHERE v.currentstatus <> 'Close'
    - Unpaid ECB fines:         WHERE e.balance_due > 0
    - Harassment found:         WHERE l.harassment_found = true
    - Always LIMIT to ≤ 25 rows unless explicitly asked for more
    """
    from neo4j import GraphDatabase

    uri      = os.environ["NEO4J_URI"]
    user     = os.environ.get("NEO4J_USERNAME", "neo4j")
    password = os.environ["NEO4J_PASSWORD"]
    db = os.environ.get("NEO4J_DOMAIN_DATABASE", "neo4j")
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session(database=db, default_access_mode="READ") as session:
            result = session.run(query, parameters=params or {})
            records = [dict(r) for r in result]
            cleaned = []
            for rec in records:
                cleaned.append({
                    k: (dict(v) if hasattr(v, "items") else
                        list(v) if hasattr(v, "__iter__") and not isinstance(v, str) else v)
                    for k, v in rec.items()
                })
            return json.dumps(cleaned, default=str, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})
    finally:
        driver.close()


# ─────────────────────────────────────────────
# Web search tool (Tavily)
# ─────────────────────────────────────────────

def web_search(query: str, max_results: int = 5) -> str:
    """
    Search the live web for current news, investigative journalism, court filings,
    policy context, or any information not available in the knowledge graph.

    Use this to supplement graph data with:
    - Recent media coverage of specific landlords or buildings
    - Legal context (HPD enforcement policies, rent stabilisation law changes)
    - NYC housing agency press releases or data releases
    - Explanations of acronyms or regulatory frameworks

    Returns a JSON list of {url, title, content} objects.
    """
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
        results = client.search(query, max_results=max_results)
        return json.dumps([
            {"url": r.get("url"), "title": r.get("title"), "content": r.get("content")}
            for r in results.get("results", [])
        ], indent=2)
    except KeyError:
        return json.dumps({"error": "TAVILY_API_KEY not set — web search unavailable"})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ─────────────────────────────────────────────
# Provenance tracker (wraps tools to log calls)
# ─────────────────────────────────────────────

class ProvenanceTracker:
    """Wraps tool functions to record every call made during a run."""

    def __init__(self) -> None:
        self.cypher_calls: list[dict] = []
        self.search_calls: list[dict] = []

    def wrap_schema(self, fn):
        def _wrapped() -> str:
            return fn()
        _wrapped.__name__ = fn.__name__
        _wrapped.__doc__  = fn.__doc__
        return _wrapped

    def wrap_cypher(self, fn):
        tracker = self

        def _wrapped(query: str, params: dict | None = None) -> str:
            tracker.cypher_calls.append({"query": query, "params": params or {}})
            return fn(query, params)

        _wrapped.__name__ = fn.__name__
        _wrapped.__doc__  = fn.__doc__
        return _wrapped

    def wrap_search(self, fn):
        tracker = self

        def _wrapped(query: str, max_results: int = 5) -> str:
            tracker.search_calls.append({"query": query, "max_results": max_results})
            return fn(query, max_results)

        _wrapped.__name__ = fn.__name__
        _wrapped.__doc__  = fn.__doc__
        return _wrapped

    def provenance_block(self) -> str:
        lines: list[str] = ["\n" + "─" * 60, "📋  PROVENANCE", "─" * 60]

        if self.cypher_calls:
            lines.append(f"\n🗄️  Cypher queries ({len(self.cypher_calls)}):")
            for i, call in enumerate(self.cypher_calls, 1):
                lines.append(f"\n  [{i}]  {'-'*40}")
                for ln in call["query"].strip().splitlines():
                    lines.append(f"        {ln}")
                if call["params"]:
                    lines.append(f"        params: {json.dumps(call['params'])}")
        else:
            lines.append("\n  (no Cypher queries run)")

        if self.search_calls:
            lines.append(f"\n🔍  Web searches ({len(self.search_calls)}):")
            for i, call in enumerate(self.search_calls, 1):
                lines.append(f"  [{i}]  {call['query']!r}  (max_results={call['max_results']})")
        else:
            lines.append("\n  (no web searches run)")

        lines.append("─" * 60)
        return "\n".join(lines)

    def reset(self) -> None:
        self.cypher_calls.clear()
        self.search_calls.clear()


# ─────────────────────────────────────────────
# System prompt
# ─────────────────────────────────────────────

SYSTEM_PROMPT = textwrap.dedent(f"""
    You are DeedWatch, an expert research assistant for NYC housing accountability.

    You have access to the DeedWatch knowledge graph — an integrated Neo4j database
    covering HPD violations, DOB violations, ECB/OATH fines, HPD litigation, evictions,
    ACRIS deed and mortgage transactions, DOS corporate filings, rent stabilisation data,
    tax liens, and a portfolio clustering of ~858 000 NYC properties keyed by BBL.

    You also have access to live web search for news, journalism, and regulatory context.

    ══════════════════════════════════════════════
    MANDATORY WORKFLOW — follow this every time
    ══════════════════════════════════════════════

    STEP 0 — GET SCHEMA
        Call get_schema() before writing ANY Cypher.
        The schema contains the exact property names and relationship directions
        for every node type.  Guessing property names is the #1 cause of failed
        queries (e.g. the field is `class` not `violation_class`; it is
        `novissueddate` not `issued_date`; HpdLitigation has no `penalty` field).
        You may skip this step only if the schema is already visible earlier in
        this conversation.

    STEP 1 — PLAN
        Identify what BBL, owner name, or portfolio ID you need.
        Map the question to the correct node types and relationships from the schema.

    STEP 2 — QUERY
        Call run_cypher() with precise, parameterised Cypher.
        Always include LIMIT (≤ 25 rows by default).
        If a query returns an error, inspect the message, correct the property name
        or relationship direction, and retry — do not give up after one failure.

    STEP 3 — ENRICH (optional)
        Call web_search() for media coverage, regulatory context, or recent events
        not captured in the graph.

    STEP 4 — ANSWER
        Synthesise a clear, evidence-based response citing specific counts, dates,
        and dollar amounts from the query results.

    ══════════════════════════════════════════════

    The current schema is embedded below for quick reference, but always call
    get_schema() at the start of a new question to confirm you have the live version.

    {SCHEMA_SNAPSHOT}

    Tone: direct, factual, neutral.  Users are housing advocates, journalists,
    and researchers — accuracy matters more than hedging.
""").strip()


# ─────────────────────────────────────────────
# Agent factory
# ─────────────────────────────────────────────

def build_agent(tracker: ProvenanceTracker, checkpointer=None):
    """Create a DeepAgent with tracked schema, cypher, and search tools."""
    from deepagents import create_deep_agent

    tools = [
        tracker.wrap_schema(get_schema),
        tracker.wrap_cypher(run_cypher),
        tracker.wrap_search(web_search),
    ]

    agent = create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer
    )
    return agent.with_config({"recursion_limit": 25})

# ─────────────────────────────────────────────
# High-level helper: run a single question
# ─────────────────────────────────────────────

def run_question(question: str, verbose: bool = True) -> str:
    """
    Run the DeedWatch agent on a single question and return the answer string.
    Provenance (all Cypher and web searches) is appended to the returned string.
    """
    tracker = ProvenanceTracker()
    agent   = build_agent(tracker)

    config  = {"configurable": {"thread_id": f"deedwatch-{datetime.utcnow().isoformat()}"}}
    result  = agent.invoke(
        {"messages": [HumanMessage(content=question)]},
        config=config,
    )

    answer = ""
    for msg in reversed(result.get("messages", [])):
        if isinstance(msg, AIMessage) and msg.content:
            answer = msg.content if isinstance(msg.content, str) else str(msg.content)
            break

    provenance  = tracker.provenance_block()
    full_output = answer + provenance

    if verbose:
        print(full_output)

    return full_output


# ─────────────────────────────────────────────
# Streaming variant
# ─────────────────────────────────────────────

def stream_question(question: str) -> None:
    """
    Stream the DeedWatch agent response token-by-token, then print provenance.
    """
    tracker = ProvenanceTracker()
    agent   = build_agent(tracker)

    config  = {"configurable": {"thread_id": f"deedwatch-stream-{datetime.utcnow().isoformat()}"}}

    print(f"\n🏙️  DeedWatch | {question}\n{'─'*60}\n")

    for chunk in agent.stream(
        {"messages": [HumanMessage(content=question)]},
        config=config,
        stream_mode="messages",
    ):
        msg, _meta = chunk if isinstance(chunk, tuple) else (chunk, {})
        if hasattr(msg, "content") and isinstance(msg.content, str):
            print(msg.content, end="", flush=True)

    print()
    print(tracker.provenance_block())


# ─────────────────────────────────────────────
# Interactive CLI
# ─────────────────────────────────────────────

def main() -> None:
    """Interactive CLI loop for DeedWatch."""
    print(textwrap.dedent("""
        ╔══════════════════════════════════════════════════════════╗
        ║          DeedWatch NYC — Landlord Accountability         ║
        ║          Powered by LangChain DeepAgent + Neo4j          ║
        ╚══════════════════════════════════════════════════════════╝

        Type a question about NYC housing, landlords, or buildings.
        Type 'quit' or press Ctrl-C to exit.

        Example questions:
          • Who owns 340 E 93rd St Manhattan and how many violations?
          • Which landlords in Brooklyn have the most open Class C violations?
          • Show the deed and mortgage history for BBL 3001230045
          • Which portfolios have both tax liens and harassment findings?
          • What are the biggest ECB fine balances unpaid in the Bronx?
    """).strip())

    missing = [v for v in ("NEO4J_URI", "NEO4J_PASSWORD", "ANTHROPIC_API_KEY")
               if not os.environ.get(v)]
    if missing:
        print(f"\n⚠️  Missing required environment variables: {', '.join(missing)}")
        print("   Set them and re-run.\n")
        return

    tracker = ProvenanceTracker()
    agent   = build_agent(tracker)

    session_id = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    config     = {"configurable": {"thread_id": f"deedwatch-{session_id}"}}
    history: list[Any] = []

    print("\nReady. (Agent maintains conversation context within this session.)\n")

    while True:
        try:
            question = input("❓ Question: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not question:
            continue
        if question.lower() in ("quit", "exit", "q"):
            print("Goodbye.")
            break

        tracker.reset()
        history.append(HumanMessage(content=question))

        print(f"\n{'─'*60}")

        try:
            result = agent.invoke({"messages": history}, config=config)
        except Exception as exc:
            print(f"⚠️  Agent error: {exc}")
            continue

        msgs    = result.get("messages", [])
        history = msgs

        for msg in reversed(msgs):
            if isinstance(msg, AIMessage) and msg.content:
                text = msg.content if isinstance(msg.content, str) else str(msg.content)
                print(text)
                break

        print(tracker.provenance_block())
        print()


if __name__ == "__main__":
    main()
