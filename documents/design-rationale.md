# Watchline NYC: Design Rationale
## Why the System Is Built the Way It Is

**Version 1.0 -- Draft for discussion. June 2026.**

---

## Purpose of This Document

The Charter says what Watchline must do. The Ontology Specifications say what exists in the system and how it is structured. This document explains why the key design decisions were made the way they were.

Its primary audience is future contributors: developers, data engineers, ontology designers, and policy collaborators who need to understand the reasoning behind the architecture in order to extend it without inadvertently undermining it. Many of the decisions recorded here will seem obvious in hindsight. They were not obvious at the time, and without this record, they are likely to be quietly reversed.

Each entry follows a consistent structure: the decision, the alternatives that were considered, the arguments that settled the question, and where relevant, the dissenting considerations that were acknowledged but set aside.

---

## Decision 1: Watchline is an evidence system, not a knowledge graph

**The decision:** Watchline is designed and described as an evidence system for public accountability, not as a knowledge graph or data integration platform.

**Alternatives considered:** The project could have been framed as a knowledge graph linking NYC housing datasets, with an AI query interface on top. This would have been a more conventional description and would have aligned with how similar projects are typically described.

**Why this decision was made:** A knowledge graph optimizes for traversal: can the system get from Building X to Owner Y in two hops? An evidence system optimizes for justification: can the system reconstruct why a claim is warranted, and what would change if one piece of evidence were removed? These are different design goals that produce different architectural choices. Framing Watchline as an evidence system from the outset ensures that justification, not merely connectivity, is treated as a first-class concern throughout the architecture.

The framing also clarifies what the system is not. A knowledge graph that integrates HPD, DOB, ACRIS, and DHCR data is a useful tool but not a distinctive one. Many organizations can do that. What distinguishes Watchline is that it allows someone to ask, in plain language, why a claim is warranted, and receive a transparent, evidence-backed answer. That capability is not a feature of the knowledge graph layer; it is a property of the whole system.

**Dissent acknowledged:** The "evidence system" framing is less immediately legible to technical audiences who are familiar with knowledge graphs but unfamiliar with evidence systems as a software category. This is a real cost. The decision to accept it reflects a judgment that the framing will prove more durable as the system is built and explained.

---

## Decision 2: The ontology is the product

**The decision:** The ontology is treated as Watchline's primary intellectual asset, not as a schema that supports the software. The knowledge graph, ingestion pipelines, entity resolution engine, and AI agent are all implementations of the ontology.

**Alternatives considered:** The ontology could have been treated as a technical artifact, produced by engineers to support a graph database, and updated as implementation needs dictate. This is how ontologies are typically managed in software projects.

**Why this decision was made:** The datasets that Watchline integrates are public and can, in principle, be replicated by any organization with sufficient engineering resources. The AI agent layer is also reproducible: the underlying models are commercially available, and the query interface is not architecturally novel. What cannot be easily replicated is the conceptual framework that specifies what counts as an observation, what counts as evidence, how identities are established, what rules transform evidence into claims, and how every conclusion can be challenged, explained, or revised. That framework embeds years of domain judgment and deliberate normative choices. It is Watchline's most durable asset.

Treating the ontology as the product also has a practical consequence: it forces every significant design decision to be articulated and documented at the conceptual level before implementation begins. This discipline prevents the system from silently reproducing the structure of its source datasets, which is the most common failure mode in knowledge graph projects.

**Dissent acknowledged:** Treating the ontology as primary can create friction in fast-moving development cycles, where engineers need to make implementation decisions quickly. The response to this concern is that the ontology is not expected to be complete before implementation begins. The Minimum Viable Ontology principle applies: define what you need to answer the first real questions, and grow from there.

---

## Decision 3: Five layers, not three

**The decision:** The ontology is organized into five layers: Domain, Evidence, Identity, Interpretation, and Investigation. Earlier drafts used three layers (Domain, Evidence, Identity) or four (Domain, Evidence, Identity, Investigation).

**Alternatives considered:** A three-layer model (Domain, Evidence, Identity) would have been simpler and is a reasonable starting point for most knowledge graph projects. A four-layer model that added Investigation without a separate Interpretation layer was also considered.

**Why this decision was made:** The Interpretation layer was added as a distinct layer when it became clear that the investigative concepts Watchline needs to support, such as Persistent Hazardous Conditions, Probable Common Beneficial Control, and Recidivism, are normative concepts, not descriptive ones. They apply a standard to evidence; they do not merely label it. A system that produces these concepts without an explicit layer devoted to the rules that define them would be making normative claims it cannot explain. The Interpretation layer is where those rules live, and making it distinct from the Investigation layer preserves an important separation: Investigation is about what users want to find out; Interpretation is about the system's licensed methods for transforming evidence into conclusions.

**Dissent acknowledged:** Five layers is more complex than necessary for early development. The practical response is that implementation naturally starts at the bottom (Domain and Evidence) and works upward. The layers do not all need to be fully built before the system is useful.

---

## Decision 4: Rules are first-class ontological objects, not code

**The decision:** Every inference the system makes must be produced by a named, versioned, documented Rule. Rules are nodes in the ontology with defined properties. They are not functions, not configuration files, and not prompts embedded in the AI agent.

**Alternatives considered:** Inference logic could have been implemented as code in the ingestion pipeline or query layer, as configuration rules in a rules engine, or as instructions in the AI agent's system prompt. All three approaches are common and would have been faster to implement initially.

**Why this decision was made:** The cross-examination test requires that for any conclusion, the system can answer: what rule produced it, who defined that rule, and what evidence would change it. None of the alternative approaches make rules inspectable in the way the cross-examination test demands.

If rules are code, they are inspectable only by developers, not by users, journalists, or lawyers. If they are configuration, they may be inspectable but are typically not versioned or attributed. If they are embedded in AI prompts, they are neither inspectable nor stable: the same prompt can produce different conclusions on different runs, and there is no record of what rule was applied to a specific conclusion.

Making rules first-class objects in the ontology means that every Claim node carries a reference to the Rule that produced it, every Rule carries a version number and an attribution, and every Rule change is a documented event. This is the minimum required to make the system's reasoning auditable.

A further consequence is architectural: when rules are first-class objects, the AI agent's role changes. It does not decide what is true; it orchestrates the system's defined reasoning machinery. The quality of the system's conclusions depends on the quality of the rules, not on the unpredictable capabilities of a language model. This is a significantly safer architecture for a system that names names.

**Dissent acknowledged:** Making every inference depend on an explicit Rule creates a bottleneck: the system cannot produce new kinds of conclusions until new Rules are defined and approved. This is intentional. The bottleneck is the governance mechanism that prevents the system from making claims it cannot justify. The cost is real but acceptable given the stakes.

---

## Decision 5: Interpretive status categories instead of confidence scores

**The decision:** Uncertainty in Watchline's conclusions is represented by a controlled vocabulary of Interpretive Status values (Observed, Derived, Estimated, Inferred, Stipulated, Disputed) rather than by numerical confidence scores.

**Alternatives considered:** Numerical confidence scores (e.g., 0.84) are standard in probabilistic systems and are familiar to data scientists. Many entity resolution systems produce probability scores, and it would have been natural to propagate these through to Claims.

**Why this decision was made:** Most of the uncertainty in Watchline's conclusions is not statistical. It does not arise from sampling error or model uncertainty. It arises from interpretation: a judgment that certain evidence is sufficient to support a conclusion, applied through a rule with a defined threshold. "These LLCs are under common beneficial control" is not 84% likely; it is a judgment that the evidence satisfies Rule BO-001, which was defined with a specific threshold, by a specific author, under a specific source of authority.

Presenting this as a probability score misrepresents the nature of the uncertainty and is potentially misleading to users who would naturally interpret 0.84 as a statistical claim. Worse, it makes the conclusion harder to challenge: a user who disagrees with a 0.84 score has no obvious lever to pull. A user who disagrees with a conclusion produced by Rule BO-001 can inspect the threshold, the evidence, and the source of authority, and articulate a specific objection.

The addition of Stipulated as a status category reflects a further distinction: conclusions established by a legal finding or official determination are different in kind from conclusions produced by Watchline's own rules. Conflating them would misrepresent the basis for the conclusion.

**Dissent acknowledged:** Some aspects of entity resolution genuinely are probabilistic, and suppressing probability scores entirely may obscure real uncertainty in identity assertions. The resolution adopted is to use confidence vocabulary (High, Medium, Low) for Identity Assertions, while reserving Interpretive Status categories for Claims. This preserves the distinction between uncertainty about who an entity is and uncertainty about what the evidence shows.

---

## Decision 6: Identity is a first-class layer, not a preprocessing step

**The decision:** Entity resolution is modeled as a distinct layer of the ontology, with its own node types (IdentityObservation, IdentityAssertion, ResolutionMethod) and its own uncertainty representation. It is not treated as a preprocessing step that produces clean data before the graph is built.

**Alternatives considered:** Entity resolution could have been handled as a data engineering problem: run a matching algorithm, produce a canonical entity table, load it into the graph. This is how most knowledge graph projects handle it.

**Why this decision was made:** In NYC housing enforcement data, the same real-world person or company can appear under dozens of name variations across HPD, DOB, ACRIS, and Secretary of State filings. The uncertainty about whether two appearances refer to the same entity is material to the claims the system draws. A claim that Building X is owned by LLC Y is only as strong as the identity assertion that established LLC Y as a canonical entity distinct from a dozen similar names.

If identity resolution is treated as a preprocessing step, that uncertainty disappears into the pipeline and is invisible to users. A user who disagrees with an ownership conclusion has no way to know whether the disagreement is with the evidence, the inference rule, or the identity match that connected the two. Making Identity a first-class layer means that every canonical entity carries a record of the observations it was resolved from, the method used, and the confidence of the assertion. A user who challenges a conclusion can inspect each of these in turn.

There is also a practical governance reason. Identity resolution algorithms improve over time. If identity is treated as preprocessing, improving the algorithm requires rebuilding the graph from scratch. If identity is a first-class layer, improving the algorithm produces new IdentityAssertions that can propagate through to affected Claims without touching the underlying Observations.

**Dissent acknowledged:** Modeling identity resolution explicitly adds significant complexity to the schema and to the ingestion pipelines. This cost is real. The judgment is that the complexity is justified by the stakes of getting identity wrong in a system that makes public claims about who owns buildings.

---

## Decision 7: The AI agent is an orchestrator, not a reasoner

**The decision:** The AI agent's role in Watchline is to identify the user's investigative intent, select the appropriate rules and traversal patterns, retrieve evidence from the graph, and present conclusions in plain language. It does not independently reason about what is true or produce conclusions that are not traceable to defined rules.

**Alternatives considered:** A more capable AI agent could be given broader reasoning authority: ask it a question, let it traverse the graph, draw conclusions, and cite the evidence it found. This would be faster to build and would leverage the full capabilities of current language models.

**Why this decision was made:** The cross-examination test requires that for any conclusion, the system can explain what rule produced it. A conclusion produced by a language model's internal reasoning cannot meet this test. The model's weights are not inspectable, its reasoning is not reproducible, and its conclusions can vary across runs. For a system that names names in the context of NYC real estate, where the conclusions may be challenged by lawyers, this is not an acceptable basis for asserting facts.

The orchestrator model also has a practical advantage: it separates the system's reliability from the capabilities of any particular language model. When a better model becomes available, the agent layer can be upgraded without changing the rules, the ontology, or the evidence chains that produce conclusions. The conclusions improve because the orchestration improves, not because the model has been given more latitude to reason independently.

**Dissent acknowledged:** Restricting the agent to orchestration limits what questions the system can answer to those for which explicit rules have been defined. A question that falls outside the existing set of Canonical Questions and Rules cannot be fully answered. This is a real constraint on the system's utility in the short term. The response is that it is exactly the right constraint: the system should not answer questions it does not have the rules to answer honestly.

---

## Decision 8: Reversibility is a first-class design requirement

**The decision:** All conclusions in Watchline are generated from evidence rather than manually authored, and they must update automatically when the underlying evidence changes. A corrected deed, a resolved violation, an improved entity-resolution algorithm, or a revised Rule should propagate through the system to affected conclusions.

**Alternatives considered:** Conclusions could have been authored once and cached, updated manually when significant changes occur. This is how most publication-oriented systems work, including investigative journalism, where an article is fixed at publication and corrected only by explicit editorial decision.

**Why this decision was made:** Watchline produces conclusions about real people and organizations. If a deed is corrected, an ownership conclusion based on that deed should not persist in the system after the correction. If an entity-resolution algorithm is improved and determines that two entities previously merged are actually distinct, claims that relied on that merger should be revised. Persistent incorrect conclusions about real actors have real consequences: reputational, legal, and financial.

The reversibility requirement also has a structural benefit. It prevents the accumulation of stale conclusions that undermine the system's credibility over time. A system that cannot update its conclusions as evidence changes will eventually contradict itself, and a system that contradicts itself cannot be trusted.

**Dissent acknowledged:** Full automated reversibility is architecturally demanding. Not every change to source data should trigger a cascade through the system; some changes are corrections, others are updates, and others are errors. A mature implementation will require a change management process that classifies incoming data changes before propagating them. This complexity is acknowledged but does not change the fundamental requirement.

---

## Decision 9: Watchline refuses to make conclusions it cannot fully expose

**The decision:** The limiting principle for what conclusions Watchline will make is: the system makes only those claims whose justification can be fully exposed to the user. If a claim cannot be traced, through its chain of reasoning, to primary source records through defined rules, the system does not make it.

**Alternatives considered:** The limit could have been defined as a list of prohibited statement types (no legal conclusions, no statements about intent, no attributions of fraud). Many similar systems define their limits this way.

**Why this decision was made:** A list of prohibited statement types is inevitably incomplete. Novel situations will always produce cases that fall between the prohibited categories. A principled limit based on the structure of justification is more robust: it asks not what the conclusion says, but whether the system can show its work.

This principle also resolves a class of edge cases cleanly. "These LLCs share a registered agent, overlapping officer names, and a repeated transaction pattern" is a conclusion the system can expose fully: it points to specific observations in specific source records. "These LLCs are secretly owned by the same person" is a conclusion the system cannot expose fully, because the word "secretly" implies intent, which is not observable in any source record. The principle tells the system where to stop without requiring an enumeration of every possible prohibited conclusion.

**Dissent acknowledged:** This principle is demanding and will sometimes prevent the system from answering questions that are answerable by a skilled human investigator using the same evidence. A human investigator can exercise judgment in ways that are not fully articulable. Watchline cannot. This is a real limitation, and it is accepted deliberately: the system's value is in being trustworthy and inspectable, not in being as capable as the best human investigator.

---

## Decision 10: LangGraph as a pipeline framework, not an agent framework

**The decision:** LangGraph is adopted as the AI orchestration framework for Watchline, used strictly as a deterministic pipeline framework. The StateGraph is acyclic. The language model is called exactly twice per pipeline execution: once to identify investigative intent, and once to present results in plain language. All reasoning between those two calls is governed by the ontology and the Rules. LangSmith is used for observability from day one. The Neo4j checkpoint saver is used for session persistence.

**Alternatives considered:** Three alternatives were evaluated. First, a vanilla Python pipeline with direct Anthropic or OpenAI SDK calls and `langchain-neo4j` for graph queries, without LangGraph. This is simpler, more obviously deterministic, and has less framework overhead. Second, a fully agentic LangGraph implementation where the model autonomously decides which graph paths to traverse and which rules to apply. Third, other orchestration frameworks including PydanticAI, the OpenAI Agents SDK, and CrewAI.

**Why this decision was made:** LangGraph was chosen over the vanilla Python pipeline for three specific capabilities. First, the `langgraph-checkpoint-neo4j` package provides maintained, production-ready session persistence that stores conversation history and agent state directly in the Watchline Neo4j instance, meaning the checkpoint store shares the same infrastructure as the knowledge graph. Second, LangSmith provides the best observability tooling currently available for LLM pipeline debugging, which is not optional for a system whose Charter requires that every pipeline execution be traceable and auditable. Third, the explicit StateGraph with defined nodes and edges is a natural implementation of the five-stage pipeline (intent identification, rule selection, graph traversal, claim generation, explanation), and the explicitness serves as documentation: the StateGraph is a readable specification of what the pipeline does.

The fully agentic LangGraph implementation was rejected because it is incompatible with Charter Principles 7 and 8. A language model reasoning autonomously about which graph paths to traverse cannot satisfy the cross-examination test and cannot produce conclusions whose justification is fully exposed. This is not a limitation of LangGraph; it is a fundamental property of autonomous LLM reasoning.

The other frameworks were not evaluated in depth. The decision to use LangGraph is not a claim that it is the best framework in any absolute sense; it is a claim that it is adequate for Watchline's requirements and has a maintained Neo4j integration that reduces engineering work at the infrastructure layer.

**The key constraint this decision imposes:** LangGraph's design center is agentic, cyclical, self-directing behavior. Every LangGraph tutorial, template, and community pattern pushes toward that use case. Working with LangGraph in a deterministic, acyclic mode requires active discipline: resisting the conditional edge patterns that delegate routing to the model, resisting the ReAct loop patterns that allow the model to decide what to do next, and resisting the multi-agent patterns that coordinate autonomous agents. Charter Principle 17 exists to make this constraint constitutional rather than a coding convention that can drift. Implementation guidance for maintaining this discipline is documented in the `langgraph-watchline` SKILL.md.

**Dissent acknowledged:** The vanilla Python pipeline alternative has a real advantage that should not be understated: it is simpler and more obviously aligned with Watchline's deterministic pipeline architecture. If LangGraph's framework complexity proves to be a maintenance burden, or if the agentic patterns prove difficult to resist in practice, the pipeline could be reimplemented without LangGraph at relatively low cost, since the ontology, the Rules, and the graph schema are independent of the orchestration framework. That optionality is worth preserving by keeping the LangGraph implementation thin and not building deep dependencies on framework-specific features beyond checkpointing and observability.

---

## Decision 11: Knowledge graph over relational database as the primary data store

**The decision:** Neo4j, a property graph database, is used as Watchline's primary data store rather than a relational database such as PostgreSQL. This decision applies to the knowledge graph, the evidence chain, the identity layer, and the ontology objects (Rules, IdentityAssertions, ResolutionMethods). It does not preclude adding a separate analytical store for aggregate queries in a later phase.

**Alternatives considered:** A relational database, specifically PostgreSQL, is the most credible alternative. It is mature, operationally well-understood, has excellent tooling, and is used effectively by comparable NYC housing data projects. JustFix's Who Owns What, which addresses a closely related problem domain, is built on PostgreSQL. A relational implementation would use recursive CTEs for ownership chain traversal, foreign keys for the evidence chain, and junction tables for many-to-many relationships. This is achievable and many organizations do it successfully.

A hybrid approach was also considered: PostgreSQL for the Domain and Evidence layers, with a graph database added later only if traversal performance proved inadequate. This would defer the operational complexity of a graph database until it was demonstrably necessary.

**Why this decision was made:** Three properties of the Watchline problem domain favor a graph database structurally, not merely as a matter of convenience.

The first is variable-depth ownership chain traversal. The most important queries Watchline must answer involve tracing beneficial ownership through LLC chains of unknown depth. NYC ownership structures routinely run four or five layers deep and occasionally deeper. In a relational database, traversing a chain of unknown depth requires recursive CTEs that become difficult to write correctly, difficult to optimize, and slow as depth increases. In Neo4j, variable-depth traversal is a native operation expressible in a single Cypher pattern. This is not a performance preference; it is a structural match between the query type and the storage model.

The second is the evidence chain. The five-layer ontology requires that every Claim be traceable through Evidence to Observations to Sources, and that this chain be retrievable in a single query when a user asks why a conclusion was reached. In a relational database, retrieving this chain requires joining across five tables, and extending the chain requires a schema migration that touches every query that traverses it. In Neo4j, the chain is a native graph traversal and extending it is a matter of adding edges without modifying existing queries.

The third, and most specific to Watchline, is that the ontology models knowledge itself rather than just domain entities. Claim, Evidence, IdentityAssertion, and Rule are not records in a dataset; they are nodes in a reasoning structure whose connections carry meaning and must be traversable in multiple directions. A relational database can represent this structure, but it does so by making the relationships implicit in foreign keys and junction tables. The structure of the reasoning becomes invisible in the schema. In a graph database, the relationships are explicit, first-class, and directly queryable. For a system whose value proposition is transparent, inspectable reasoning, this alignment between the architecture and the product matters.

The fourth argument is forward-looking and concerns the Neo4j Graph Data Science (GDS) library. The three arguments above address how the pipeline answers individual questions. GDS enables a qualitatively different capability: discovering patterns across the entire graph that no individual query would reveal. This maps directly onto several of the investigative concepts already defined in Layer 5 of the ontology, and it is a capability that would require a complete architectural change to access from a relational database.

Specific GDS applications relevant to Watchline include: community detection algorithms (Louvain, Label Propagation) applied to the ownership and relationship network to surface clusters of buildings and actors under probable common control, even when no single ownership link is documented; this is the operational implementation of the "Concealment" investigative intent. Centrality algorithms (PageRank, Betweenness Centrality) applied to the Actor network to identify the registered agents, attorneys, and management companies that sit at the structural center of the largest ownership networks; these are often the most actionable accountability targets and are invisible to query-by-query investigation. Pathfinding algorithms to answer questions such as what is the shortest documented connection between this LLC and this known enforcement history, and what does each link in that chain represent. Similarity algorithms to support the "Neighborhood Pattern" investigative intent by finding buildings that share structural characteristics in their violation history and ownership pattern even without a direct ownership link.

GDS requires the library to be installed and appropriately licensed (available on Neo4j AuraDS and Enterprise Edition), and running algorithms at scale requires careful memory configuration and query planning. It is not available without cost or effort. The argument is not that GDS will be used immediately, but that the graph choice makes it available as a direct extension of the existing architecture, whereas a relational database would make it inaccessible without exporting the data to a separate analytical tool, immediately creating the synchronization and provenance problems the evidence system architecture is designed to prevent.

**Dissent acknowledged:** The case for PostgreSQL is stronger than a simple comparison of query capabilities suggests. The operational costs of Neo4j are real: it requires more tuning and monitoring than PostgreSQL, the tooling ecosystem is smaller, fewer engineers know Cypher than SQL, and production incidents are harder to resolve quickly given the smaller community. Aggregate queries (how many Class C violations were issued in the Bronx in 2025?) are handled less efficiently by a graph database than by a well-indexed relational table; for analytical workloads Watchline will eventually generate, a columnar store alongside the graph is worth planning for.

The hybrid approach of starting with PostgreSQL and adding a graph layer later was rejected not because it is wrong in principle but because the Watchline ontology is graph-shaped from the start. Retrofitting a graph layer onto a relational foundation that was designed without it tends to produce an awkward architecture where the graph and the relational store partially duplicate each other. Starting with the graph avoids that problem, at the cost of accepting the operational complexity upfront.

The decision should be revisited if: the engineering team finds Neo4j's operational burden significantly outweighs its query advantages in practice, or if aggregate analytical queries become a primary use case that the graph database cannot serve efficiently.

---

## Decision 12: langchain_neo4j directly, not MultiServerMCPClient, for internal graph access

**The decision:** The Watchline pipeline accesses Neo4j via the `langchain_neo4j` package directly, specifically `Neo4jGraph` for Cypher query execution and `Neo4jVector` for any vector search operations. `MultiServerMCPClient` and the `mcp-neo4j-cypher` MCP server are not used for the internal pipeline-to-database connection.

**Alternatives considered:** `langchain_mcp_adapters.client.MultiServerMCPClient` with the `mcp-neo4j-cypher` MCP server is the other documented path for connecting LangGraph pipelines to Neo4j. Neo4j Labs documents both options side by side. The MCP path would involve spawning the `mcp-neo4j-cypher` server as a subprocess (stdio transport) or connecting to a remote instance (HTTP/SSE transport), loading its tools via `MultiServerMCPClient.get_tools()`, and making those tools available to the pipeline.

**Why this decision was made:** `MultiServerMCPClient` is designed for agentic tool use: it surfaces Neo4j as a tool the language model can choose to call autonomously, and its default error handling returns failures as `ToolMessage` objects so the model can self-correct and retry. Both of those properties, model-directed tool invocation and model-directed self-correction, are precisely the agentic patterns prohibited by Charter Principle 17. Using `MultiServerMCPClient` to connect to Neo4j would structurally invite the model to decide when and how to query the database, which is the pattern the pipeline architecture is designed to prevent.

`langchain_neo4j` by contrast is a direct connection library. `Neo4jGraph.query()` executes a Cypher string and returns results. The pipeline decides what Cypher to run; the model is not involved. This is a clean match between the tool and the architectural requirement: deterministic, pipeline-controlled graph access with no model involvement between intent identification and result presentation.

There is also a practical note from the `langchain-mcp-adapters` documentation itself, which includes an explicit caution: before using the MCP stdio transport in a server context, evaluate whether a simpler direct tool would suffice. For Watchline, the answer is clearly yes.

**The one future case where MCP becomes relevant:** If Watchline later exposes its knowledge graph as a service that external tools can query, the `mcp-neo4j-cypher` server or a custom Watchline MCP server becomes relevant on the serving side. A journalist running Claude Desktop could connect to a Watchline MCP server and query it directly. That is an external interface decision that does not affect the internal pipeline architecture. When that feature is built, it should be treated as a new decision recorded here, not as a modification of this one.

**Dissent acknowledged:** The MCP path would make it easier to swap Neo4j for a different graph database in the future, since the MCP server abstraction layer decouples the pipeline from the specific database client library. The `langchain_neo4j` path creates a direct dependency on that package. This is a real tradeoff and is accepted on the grounds that Neo4j is not a provisional choice (see Decision 11) and that the decoupling benefit of MCP does not outweigh the architectural risk of introducing model-directed tool invocation.

---

## Decisions Still Open

The following questions were identified during the design process but not fully resolved. They are recorded here so they are not forgotten.

**Governance of Rules in practice.** The Charter specifies that Rules must be versioned and documented, and that changes must be recorded. It does not specify who has authority to propose, approve, or deprecate Rules, or what process governs disputes about Rule definitions. This will need to be resolved as the first Rules are written and tested against real data.

**Handling of disputed claims.** The Interpretive Status vocabulary includes Disputed, but the process by which a Claim becomes Disputed is not yet defined. Who can dispute a claim? What evidence is required? How is a dispute resolved or closed? These questions have legal and editorial dimensions that require deliberate policy decisions.

**Relationship between Watchline Rules and external standards.** Some Rules will draw on external standards: HPD violation classification, FinCEN beneficial ownership guidelines, New York LLC transparency law. When those external standards change, Watchline Rules that reference them need to be reviewed and potentially revised. The process for monitoring external standards and triggering Rule reviews is not yet defined.

**Public access and user permissions.** The Charter does not address whether all of Watchline's outputs are public, or whether some conclusions (for example, identity assertions that are only Medium or Low confidence) should be visible only to vetted users. This is a policy question with significant implications for both utility and risk.

---

*This document should be read alongside the Watchline Founding Charter, the Conceptual Ontology Specification, the Implementable Ontology Specification, and the `langgraph-watchline` SKILL.md.*
