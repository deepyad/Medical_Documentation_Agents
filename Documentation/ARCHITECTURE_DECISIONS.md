# Architecture Decision Log

This document tracks the architectural decisions needed to take Medical Documentation Agents from its current proof-of-concept state to the re-architected system. It is a living log, not a one-time report.

**How to use it:**
- Every entry starts at `Status: Open`. When a decision is made, fill in the `Decision` line and flip the status to `Decided`.
- If a decision is later revisited, don't delete the old entry — add a note and a new dated decision line so the history stays visible.
- Add new entries as new questions surface during the re-architecture. Keep numbering stable within a section (append, don't renumber) so links/references don't break.
- Each entry's `Recommendation` is a starting proposal grounded in the current code, not a final answer — it exists to give the discussion a default to react to.

**Status legend:** `Open` — needs a decision · `Decided` · `Superseded` — replaced by a later entry (link to it)

---

## A. Foundations

### A1. Source of truth for requirements
**Status:** Open
**Context:** Nearly every docstring in `src/` cites a "requirement doc," `Architecture.pdf`, and `extracted_text.txt` as the specification these modules implement (see e.g. `src/agent.py:29`, `src/rollback.py:22`, `src/knowledge_retrieval.py:24`). None of these three files exist in this repository. The closest surviving artifact is `Documentation/Medical_Documentation_Agentic_POC_Outline.md`, which summarizes the same five capability areas but is a summary, not the original spec.
**Options:**
1. Locate and add the original requirement doc/Architecture.pdf to the repo (e.g. under `Documentation/source/`).
2. Treat the POC outline as the new source of truth going forward and stop citing the missing doc.
3. Write a fresh versioned spec now, before institutional knowledge of the original requirements decays further.
**Recommendation:** Do (2) immediately as a stopgap, and pursue (3) alongside this re-architecture — capture what's actually being built as we decide it, rather than continuing to point at a document nobody in the repo can read.
**Decision:** _(pending)_

---

## B. LLM & Agent Orchestration

### B1. LLM provider and model selection
**Status:** Decided — partially implemented
**Context:** `src/agent.py` (pre-change) hardcoded `ChatOpenAI(model="gpt-4-turbo-preview", ...)` — a specific, aging OpenAI model with no config override and no alternative provider path.
**Options:**
1. Keep OpenAI, but move the model name into `src/config.py` (env-configurable) and update to a current-generation model.
2. Add a provider abstraction so the model/provider is swappable (OpenAI, Anthropic, etc.) without touching `agent.py`.
3. Standardize on Claude models given this re-architecture is being driven through Claude Code tooling.
**Recommendation:** (1) at minimum — config-driven model selection is a small change with outsized flexibility. Evaluate (2)/(3) once the provider question has a real business driver (cost, quality benchmarks, or a client requirement).
**Decision:** 2026-08-16 — Implemented the config-driven half of option (1): added `openai_model` to `src/config.py` (default `"gpt-4-turbo-preview"`, override via `OPENAI_MODEL` env var), `src/agent.py` now reads `settings.openai_model` instead of a hardcoded string. Deliberately did **not** implement the other half of option (1) ("update to a current-generation model") — I don't have reliable, verifiable knowledge of what OpenAI model is actually current/available right now, and guessing a model ID risks silently breaking the agent with a nonexistent model. Left the existing value as the default; you can override via `.env` (`OPENAI_MODEL=...`) with whatever model you've confirmed is right. Options (2) (provider abstraction) and (3) (standardize on Claude) remain open — no business driver yet, per the original recommendation.

### B2. Agent orchestration framework
**Status:** Open
**Context:** The workflow is built on LangGraph's `StateGraph` (`src/agent.py:133-173`) wrapping a LangChain `AgentExecutor` (`create_openai_tools_agent`, itself a legacy LangChain pattern that predates LangChain's newer tool-calling APIs).
**Options:**
1. Keep LangGraph for the phase graph, but replace `AgentExecutor`/`create_openai_tools_agent` with a more current tool-calling loop.
2. Replace LangGraph entirely with a custom or different orchestration layer.
3. Keep as-is.
**Recommendation:** (1) — the LangGraph phase structure (plan → research → create → review) fits the problem well; the legacy `AgentExecutor` wrapper is the part worth modernizing.
**Decision:** _(pending)_

### B3. Planning-phase output parsing
**Status:** Decided — implemented
**Context:** `_plan_phase` (`src/agent.py`, pre-change) asked the LLM for a "JSON list of todos" in free text, then did `json.loads(response.content)` inside a bare `except:` that silently fell back to a hardcoded 5-item todo list on any parse failure — including on malformed LLM output that wasn't logged or surfaced anywhere.
**Options:**
1. Use structured output / tool calling (pydantic schema) instead of prompt-and-parse.
2. Keep prompt-and-parse but replace the bare `except:` with typed error handling and logging.
3. Leave as-is.
**Recommendation:** (1) — structured output eliminates this entire failure class rather than handling it better, and every current LLM API supports it natively.
**Decision:** 2026-08-16 — Implemented option (1). Added `PlannedTodo`/`PlanOutput` schemas (`src/models.py`), bound via `self.planning_llm = self.llm.with_structured_output(PlanOutput)` in `MedicalDocumentationAgent.__init__`. `_plan_phase` now calls `self.planning_llm.invoke(...)` directly — no `json.loads`, no try/except, no hardcoded fallback plan. A genuine LLM/API failure now propagates as a real exception instead of being silently replaced by a fake plan.

### B4. Tool invocation architecture — direct calls vs. MCP
**Status:** Open
**Context:** `src/tools.py` defines 6 LangChain `@tool`-decorated functions, bound directly into `create_openai_tools_agent`/`AgentExecutor` in `src/agent.py:120-131`. This is in-process Python function calling: the LLM emits an OpenAI-format tool-call, LangChain looks up the matching Python function by name and calls it directly in the same process — no MCP involved. `mcp>=0.1.0` is listed in `requirements.txt:31` but nothing in `src/` actually uses it.
**Options:**
1. Keep direct in-process tool calling (current) — simplest, fastest, single deployable, easiest to test; tools are only reachable by this one agent process.
2. Expose tools via one or more MCP servers, with the agent acting as an MCP client — decouples tool implementations from the agent, makes them reusable by other agents/clients (including Claude Desktop or other MCP-compatible tools), and gives a natural seam for H1's deferred service-layer question. Costs: separate server process(es) to run and secure, a transport/auth layer, added latency, more moving parts to operate and debug.
3. Hybrid — keep in-process calling for now; revisit MCP if/when tools need to be shared across more than one agent or exposed to external consumers.
**Recommendation:** (3) — MCP earns its complexity when tools need to be reused outside this one agent (e.g. a separate client-facing service also needing `search_similar_devices`, or wanting other MCP clients to call these tools directly). That consumer doesn't exist yet, so adopting MCP now would be building for a need that hasn't materialized. Worth noting: MCP is provider-agnostic (it's not "an OpenAI thing") — it works with any MCP-compatible client regardless of which LLM is behind it. `create_openai_tools_agent`'s OpenAI-formatted tool-calling is a separate, unrelated layer (how the LLM *requests* a tool call) from MCP (how a tool is *reached* once requested); adopting MCP wouldn't require dropping OpenAI, or vice versa. If MCP isn't adopted, the unused `mcp` dependency should be dropped from `requirements.txt` as part of K1-style cleanup.
**Decision:** _(pending)_

---

## C. Data & Retrieval

### C1. Vector database choice
**Status:** Open
**Context:** Qdrant is used throughout (`src/knowledge_retrieval.py`, `src/rag_pipeline.py`), currently pointed at `http://localhost:6333` by default (`src/config.py:22`) with no deployed instance.
**Options:**
1. Continue with Qdrant — self-hosted (Docker) for dev, Qdrant Cloud for production (already documented in `SETUP.md`).
2. Move to a managed/embedded alternative (pgvector alongside the relational DB, Pinecone, Weaviate).
**Recommendation:** (1) — Qdrant is already integrated in two modules and its multi-collection model maps well onto the global/client knowledge split (D1). Switching only pays off if there's a strong reason (e.g. wanting one database instead of two).
**Decision:** _(pending)_

### C2. Embedding model
**Status:** Open
**Context:** `src/config.py:37` hardcodes `text-embedding-ada-002`, an older OpenAI embedding model that has been superseded by newer, cheaper, higher-quality embedding models.
**Options:**
1. Upgrade to a current-generation embedding model.
2. Keep `ada-002` for continuity with any already-indexed vectors.
**Recommendation:** (1), but note this is coupled to C1/C3 — any embedding model change requires re-indexing everything, so batch it with the real data ingestion work (C3) rather than doing it twice.
**Decision:** _(pending)_

### C3. Real FDA 510(k) data ingestion
**Status:** Open
**Context:** `SemanticChunker`/`HybridRetrieval` (`src/rag_pipeline.py`) and `KnowledgeRetrieval` (`src/knowledge_retrieval.py`) implement real chunking/indexing/retrieval logic, but nothing in the repo actually ingests FDA 510(k) data into them. `SETUP.md` step 7 ("Initialize Data") shows the indexing calls as commented-out example code. The "300,000+ FDA documents" language in `Documentation/BUSINESS_PRESENTATION.md` is aspirational, not something this repo currently does.
**Options:**
1. Build an ingestion pipeline against the public openFDA 510(k) API/database.
2. License or acquire a curated FDA regulatory dataset.
3. Continue with manual/ad-hoc indexing per engagement.
**Recommendation:** (1) as the default path — openFDA's 510(k) endpoint is public and sufficient to bootstrap a real corpus without a licensing decision blocking progress. This is likely the single highest-leverage gap to close, since nothing downstream (retrieval quality, evals, demos) is real without it.
**Decision:** _(pending)_

### C4. Hybrid retrieval tuning methodology
**Status:** Open
**Context:** Dense (Qdrant) + sparse (BM25) fusion weighting and an optional cross-encoder re-rank step are described in `Documentation/Medical_Documentation_Agentic_POC_Outline.md` section 3 and explicitly flagged there as unfinished "next iteration" work — no tuning process or benchmark exists yet.
**Options:**
1. Build an offline eval set (recall@k, precision@k, MRR on labeled device pairs, as the POC outline proposes) before tuning anything.
2. Tune weights ad hoc against spot checks.
**Recommendation:** (1) — this depends on C3 (real data) existing first; sequence it after ingestion, not before.
**Decision:** _(pending)_

---

## D. Knowledge Layer

### D1. Global vs. client knowledge conflict resolution
**Status:** Open
**Context:** `KnowledgeRetrieval` maintains separate `global_knowledge`/`client_knowledge` Qdrant collections (`src/knowledge_retrieval.py:79`) and the design supports detecting contradictory high-similarity facts, but there is no resolution workflow — conflicts can be flagged, not resolved. `Medical_Documentation_Agentic_POC_Outline.md` explicitly lists this as a next step.
**Options:**
1. Human-in-the-loop resolution (surface conflicts to a reviewer before they affect document generation).
2. Automatic resolution by recency/confidence scoring alone.
3. No resolution — leave both facts retrievable and let the generation prompt handle ambiguity.
**Recommendation:** (1) for anything that could affect regulatory submission content — given the compliance stakes (I2), silent automatic resolution is the wrong default here even though it's the cheapest to build.
**Decision:** _(pending)_

### D2. Fact-extraction pipeline
**Status:** Open — recommendation adopted as decision (deferred, tracked explicitly)
**Context:** Docs describe parsing conversations into atomic, timestamped, confidence-scored facts for the client knowledge store, but no such extraction pipeline exists in `src/` — only the storage/retrieval side (`KnowledgeRetrieval`) is implemented.
**Options:**
1. Build an LLM-based extraction step (conversation → structured facts) feeding `KnowledgeRetrieval`.
2. Defer — keep knowledge ingestion manual until there's a concrete conversation source to parse.
**Recommendation:** (2) until there's a real input source (e.g. actual client call transcripts) to design against — building extraction logic against no real data risks guessing the wrong schema.
**Decision:** 2026-09-02 — Adopting (2): deliberately deferred, no code to build without a real input source. Revisit once a concrete conversation source exists.

---

## E. Persistence: Rollback, Documents & Forms

### E1. Rollback storage backend
**Status:** Decided (direction) — implementation details split out to E4/E5 below
**Context:** `RollbackManager.__init__` (`src/rollback.py:61`, pre-change) defaulted `storage` to a plain `{}` dict — transactions lived only in process memory and were lost on restart, and couldn't be shared across multiple processes/workers. `SETUP.md`'s "Production Setup" section already flagged this: *"Update `src/rollback.py` to use PostgreSQL/MySQL instead of in-memory."* Investigating this also surfaced a real bug: the old `rollback()` method built `Transaction(**transaction.model_dump(), status=...)`, which passes `status` twice (once via `**` unpacking, once explicitly) — a `TypeError` on every call.
**Options:**
1. Postgres-backed transaction log (matches `database_url` already present in `src/config.py:30`, just unused).
2. Append-only event store / event-sourcing approach for stronger audit guarantees.
3. Keep in-memory for local dev, add a pluggable storage interface so prod can swap in (1) or (2).
**Recommendation:** (3) — `RollbackManager` already accepts a `storage` parameter, so the interface seam exists; the work is implementing a Postgres-backed implementation of it, not redesigning the class.
**Decision:** 2026-08-16 — Use Postgres (option 1) via a `RollbackStorage` interface (option 3's pattern): `InMemoryRollbackStorage` stays the default/eval-mode backend, `PostgresRollbackStorage` is the durable production backend. Tooling: SQLAlchemy + Alembic (see E4). This was drafted in `src/rollback.py` but implementation is currently paused pending the open questions below — not yet merged/finalized. Still coupled to I2 (compliance posture): if audit immutability turns out to be a hard requirement, revisit toward option 2 (event-sourcing) instead of a mutable Postgres table.

### E2. Multi-resource transaction atomicity
**Status:** Decided — implemented
**Context:** `RollbackManager.create_transaction` (pre-change) modeled one resource per transaction. Multi-document generation (the core use case — "creating 10+ documents") had no mechanism to roll back a partially-completed batch as a unit.
**Options:**
1. Saga pattern — compose multi-step operations from single-resource transactions with a defined compensation order.
2. Wrap batches in a parent "transaction group" ID that rolls back its children in reverse order.
3. Leave single-resource only; require callers to roll back each affected resource individually.
**Recommendation:** (2) — simplest extension of the existing transaction-ID model, and matches how document generation already proceeds sequentially through the todo list in `src/agent.py`.
**Decision:** 2026-09-02 — Implemented option (2), with one deviation: no `group_id` is stored anywhere. Storing one would require extending `Transaction`/`TransactionRecord` and both `RollbackStorage` backends (`InMemoryRollbackStorage` and the Postgres one), which is explicitly out of scope for this round (Postgres-layer work paused). Instead `RollbackManager.rollback_group(transaction_ids)` takes the list of IDs the caller already collected while building the batch, and rolls them back in reverse order — stopping at the first failure rather than sweeping past it, so a partial rollback is visible rather than silently hidden. `RollbackAPI.rollback_group()` added as the matching convenience wrapper. Covered by `tests/test_rollback.py::TestRollbackGroup` (see G1). Not yet wired into the live agent workflow — `agent.py`'s phase methods don't currently collect transaction IDs across the whole run to hand to this, since document creation happens one todo per LangGraph node invocation rather than in a single batched call. That wiring is a separate, larger decision (when should the agent actually decide to invoke a group rollback?) left for a future round.

### E3. Production document/form data store
**Status:** Decided (direction) — implementation paused, see E5
**Context:** Before this discussion, no real production data store existed at all — `MockAPI` (`src/mock_api.py`) was the *only* implementation of the documents/forms API, and (per E5) the write tools always used it regardless of the agent's mode. There was no ADR entry addressing this gap directly; it was implicit in C3 (real FDA data) and I2 (compliance) but never named.
**Options:**
1. Build `PostgresAPI` mirroring `MockAPI`'s exact method interface, so it's a drop-in swap.
2. Defer a real store; keep everything on `MockAPI` until there's a concrete production consumer (ties to H1, which also recommended deferring).
**Recommendation:** (1) — this is the change that actually makes the system "live" rather than mocked, which is the premise of this whole discussion thread.
**Decision:** 2026-08-16 — Build `PostgresAPI` (drafted, unreviewed, in `src/postgres_api.py`) as a same-interface replacement for `MockAPI` in production mode.

### E4. Storage schema shape: JSON columns vs. normalized tables
**Status:** Open
**Context:** The paused draft (`src/db_models.py`) stores `previous_state`/`new_state` (transactions), `metadata` (documents/forms), and `answers` (forms) as Postgres `JSONB` columns rather than normalized relational columns/tables (e.g. a separate `form_answers` row per question).
**Options:**
1. Keep JSONB blobs — flexible, no migration needed when document/form shapes change, matches how `MockDatabase` already stores these as free-form dicts.
2. Normalize into relational tables/columns — more queryable (can index/filter on individual fields, e.g. a specific form answer), but requires a settled schema and a migration for every shape change.
3. Hybrid — structured columns for the fields that are stable (id, type, title, status, timestamps), JSONB for the parts still in flux (metadata, answers).
**Recommendation:** (3) as drafted — the draft already does this for documents/forms (structured columns + a `metadata`/`answers` JSONB catch-all); full normalization is premature while document/form shapes aren't finalized (blocked on C3 — real FDA data hasn't been ingested yet, so the actual shape of a "document" in practice isn't known).
**Decision:** _(pending — you flagged wanting to think through more decisions before implementation continues)_

### E5. Mode-based storage wiring (eval vs. production)
**Status:** Open
**Context:** The paused draft routes eval mode to `MockAPI` + `InMemoryRollbackStorage` (ephemeral, resettable) and production mode to `PostgresAPI` + `PostgresRollbackStorage` (durable), selected via new `configure_api()`/`configure_rollback_manager()` calls in `src/tools.py`, invoked from `MedicalDocumentationAgent.__init__` based on `use_mock_api`. This also fixes a real bug: `create_document`/`update_document`/`update_form_answer` (`src/tools.py`) previously took an `api: Optional[MockAPI] = None` parameter that was never actually populated — LangChain's tool-calling can't route a non-JSON-serializable argument like an API client through the LLM — so all writes silently went to `MockAPI` regardless of mode.
**Options:**
1. Module-level mutable "active API" set once at agent construction (what's drafted) — smallest change, matches the existing module-singleton pattern already used for `rag_pipeline`/`knowledge_retrieval` in `tools.py`.
2. Thread the API/storage objects through `AgentState` or LangGraph's config/context instead of a module global — no mutable global state, safer if multiple agents/modes ever run concurrently in one process.
3. Separate tool sets per mode (e.g. `PRODUCTION_TOOLS` / `EVAL_TOOLS` lists), bound to the agent executor at construction.
**Recommendation:** (1) for now as the minimal fix; revisit toward (2) if/when concurrent multi-mode execution in one process becomes a real requirement — module-level state is fine for a single agent instance per process, which is the current usage pattern.
**Decision:** _(pending)_

### E6. Local dev environment — docker-compose scope
**Status:** Open
**Context:** Originally scoped as just "single `docker run` command for Postgres" (this project's earlier, narrower framing chose "rollback + document/form store" without the broader "docker-compose + local dev setup" tier). Revisited because the trigger condition named in that original framing — "revisit once there's a second or third service to coordinate" — is now true: local dev involves Qdrant (currently a manual `docker run` in `SETUP.md`, no volume — see below), Postgres (not yet documented at all), and the app/MCP server (`src/mcp_server.py`, drafted). The MCP server's reuse case (Claude Desktop, etc.) expects a simple local spawn command (`python -m src.mcp_server`), not a containerized invocation — Claude Desktop-style config runs a local command, and while `docker run -i`/`docker compose exec` *can* keep stdin attached for a stdio server, it adds friction to the exact use case that motivated building it (B4).
**Options:**
1. `docker-compose.yml` for backing services only (Postgres + Qdrant) — one `docker compose up -d` replaces separate manual `docker run` commands. App/MCP server stays a local Python process. Add a documented (or compose one-off) `alembic upgrade head` migration step.
2. Full-stack compose — backing services plus a built app/MCP image, so `docker compose up` brings up literally everything.
3. Separate manual `docker run` commands per service (status quo, plus one more for Postgres) — no compose file.
**Recommendation:** (1) — Postgres/Qdrant are pure stateful infrastructure with no reason to run outside a container; the MCP server has no state of its own and its main consumer (stdio clients like Claude Desktop) wants a plain local command. Revisit (2) if/when H1 (service exposure) moves toward a networked HTTP/SSE variant instead of stdio — that's a genuine "run as a service" shape Docker fits naturally, unlike a stdio subprocess spawned by a desktop client.

Additional concrete requirements, regardless of which option is chosen:
- **Volumes:** today's `docker run ... qdrant/qdrant` command in `SETUP.md` mounts no volume — all indexed vectors are lost when the container is removed. Whatever ships needs named volumes for both Qdrant (`qdrant_data:/qdrant/storage`) and Postgres (`postgres_data:/var/lib/postgresql/data`).
- **Networking convention:** `.env.example` should stay `localhost`-based (app runs locally outside compose, per the recommendation above) rather than needing compose-internal service-name hostnames — one config, not a split local/compose config.
- **Startup ordering:** `depends_on` alone only waits for container start, not Postgres readiness — a migration step needs `depends_on: postgres: condition: service_healthy` with a real `pg_isready` healthcheck (common compose gotcha otherwise).
**Decision:** _(pending)_

---

## F. Evaluation & Mock API

### F1. Mock/shadow API architecture
**Status:** Open
**Context:** `MockDatabase` (`src/mock_api.py:32`) is an in-process, in-memory structure seeded from an optional `snapshot_data` dict passed at construction time. No actual pipeline exists to produce that snapshot from a real production system — `SETUP.md`/`Medical_Documentation_Agentic_POC_Outline.md` describe periodic production snapshots, but nothing in `src/` generates one. Concrete example of this gap: `AgentEvaluator.evaluate_agent` (`src/evals.py:101-103`) has a commented-out call to `self._load_snapshot()` — a method that doesn't exist anywhere on the class. See F6 for the eval-specific version of this decision.
**Options:**
1. Build a real snapshot export job once a production data store exists to snapshot from.
2. Keep hand-authored fixture snapshots for now (sufficient for current dev/demo needs).
**Recommendation:** (2) until E1/production data infrastructure exists — there's no production system to snapshot from yet, so this is blocked on other decisions, not on `mock_api.py` itself.
**Decision:** _(pending)_

### F2. Evaluation framework
**Status:** Decided
**Context:** `langsmith` is a declared dependency (`requirements.txt:8`) and `src/config.py` has LangSmith tracing settings. Confirmed by reading `src/evals.py`: `AgentEvaluator` genuinely integrates with real LangSmith APIs (`Client`, `@traceable`, `evaluate()`, `src/evals.py:25-27`) — it is not a stub or a reimplementation. The problems are in the evaluators built on top of it, not in the choice of framework — tracked separately as F3/F4/F9.
**Options:**
1. Standardize on LangSmith datasets/evaluators since tracing is already wired.
2. Custom eval harness independent of LangSmith.
**Recommendation:** (1) — avoid maintaining a parallel eval system when the tracing integration already exists.
**Decision:** 2026-08-16 — LangSmith confirmed as the framework in use (option 1). Correctness gaps in the current evaluator implementation are tracked as F3/F4/F9, not a reason to reconsider the framework itself.

### F3. Evaluator correctness: per-run isolation, error signal, and unused ground truth
**Status:** Decided — implemented
**Context:** Three compounding bugs found in `src/evals.py`'s three evaluators, meaning none of them currently measure what they claim to:
1. **State wiring:** `completeness_evaluator` (`:119-161`) reads `run.outputs.get("state")`, but `evaluate_agent` (`:65-117`) returns the bare `AgentState` directly, never wrapped as `{"state": ...}`. Always falls to `score: 0.0`.
2. **Wrong instance, and no error signal exists anyway:** `correctness_evaluator` (`:163-205`) inspects `self.mock_api.get_transaction_log()` — `AgentEvaluator`'s own `MockAPI()` instance (`__init__`, `:63`), never touched by the actual eval run (each run builds its own `MedicalDocumentationAgent(use_mock_api=True)`, which creates a *separate* `MockAPI()`). Always scores `1.0` regardless of real behavior. Even fixed to the right instance, the check is structurally wrong: `MockDatabase.create/update/delete` (`src/mock_api.py`) never puts an `"error"` key into `transaction_log` entries — those are always `{"action", "resource_type", "resource_id", "timestamp"}`. Real failures surface only as `{"success": False, "error": ...}` return values from `RollbackAPI.execute_with_rollback`, landing as unstructured text inside `state.messages`; `AgentState.error` (`src/models.py`) exists but nothing ever sets it. Compounded by `max_concurrency=2` (`:358`) — concurrent eval runs would corrupt a naively-shared `mock_api`.
3. **Ground truth unused:** `create_eval_dataset()` examples define `outputs={"expected_documents": [...], "expected_todos_completed": N}` (`:262-299`), but `completeness_evaluator`/`correctness_evaluator`/`safety_evaluator` all take an `example` parameter and none of them ever reference `example.outputs`. `completeness_evaluator` computes its score purely from the run's own todo list, never diffing against `expected_todos_completed`. The entire point of a regression eval dataset — comparing actual vs. known-good behavior — isn't wired up.
**Options:**
1. Give tool/rollback failures a structured home (add `AgentState.tool_errors: List[Dict]`, populated by `src/tool_impl.py` whenever a call result contains `"success": False`/`"error"`) and have `evaluate_agent` return a dict bundling per-run state + tool_errors, so evaluators read from `run.outputs` (per-run, concurrency-safe) and diff against `example.outputs` instead of self-checking or reverse-engineering signal from the transaction log.
2. Confirm exact LangSmith version behavior for how a target function's return value populates `run.outputs` before finalizing the shape.
3. Bypass the evaluator/run/example signature entirely and compute scores directly inside `evaluate_agent`.
**Recommendation:** (1) — addresses all three bugs at once, and resolves the concurrency issue as a side effect. Should be paired with a unit test for these evaluators specifically (ties to G1) — this exact failure mode (evaluators trivially passing regardless of real behavior) is easy to silently reintroduce.
**Decision:** 2026-08-16 — Implemented option (1), with one adjustment made during implementation: tool errors are populated in `src/agent.py`, not `src/tool_impl.py` as originally proposed. Reason: `tool_impl.py`'s functions are plain module-level functions with no access to `AgentState` — the only place with both the tool call results *and* the state object in scope is `agent.py`'s phase methods, after `AgentExecutor.invoke()` returns. Concretely:
- `AgentState` gained a `tool_errors: List[Dict[str, Any]]` field (`src/models.py`).
- `AgentExecutor` now runs with `return_intermediate_steps=True` (`src/agent.py`), exposing each tool call's raw result instead of only the LLM's final folded-together text output.
- A new `MedicalDocumentationAgent._extract_tool_errors()` scans those intermediate steps for any result containing `"success": False`/`"error"`, and `_research_phase`/`_create_documents_phase`/`_review_phase` (every phase that calls the agent executor) now merge newly-found errors into `state.tool_errors`.
- `evaluate_agent` (`src/evals.py`) now returns `{"state": state}` instead of the bare state — fixes bug #1 directly.
- `correctness_evaluator` now reads `state.get("tool_errors", [])` from the per-run state instead of `self.mock_api.get_transaction_log()` — fixes bug #2 (both the wrong-instance problem and the "no error key exists" problem), and removes `AgentEvaluator.mock_api` entirely since nothing needs it anymore.
- `completeness_evaluator` now diffs against `example.outputs["expected_todos_completed"]` when present — fixes bug #3 (the unused ground truth).
- Concurrency-safety (originally raised in the F3 context) is resolved as a side effect: nothing reads from a shared evaluator-level instance anymore, only from each run's own `run.outputs`.

Not done in this pass: `safety_evaluator` (F4) — separate decision, unchanged here. The unit test recommended alongside this fix (ties to G1) also hasn't been written yet — G1 (testing strategy) is still Open.

### F4. Safety evaluator is a stub
**Status:** Decided — implemented
**Context:** `safety_evaluator` (pre-change) unconditionally returned `score: 1.0` with a canned comment — it didn't check anything, just assumed safety because mock mode was requested. Notable now that E5 introduces a real eval/production storage switch: a bug in that wiring could make an "eval" run silently touch `PostgresAPI`, and this evaluator would still report perfect safety.
**Options:**
1. Have `safety_evaluator` assert on the concrete storage class actually used for that run (e.g. record which API class `tool_impl` was configured with at run time and check it), rather than assuming.
2. Leave as an aspirational placeholder.
**Recommendation:** (1) — this is the one evaluator whose entire purpose is to catch exactly the kind of mode-wiring bug E5 could introduce; a no-op defeats its purpose now that production writes are real.
**Decision:** 2026-09-02 — Implemented option (1). `evaluate_agent` (`src/evals.py`) now captures `type(tool_impl._active_api).__name__` immediately after each run and returns it as `api_class`; `safety_evaluator` scores 0.0 if that isn't `"MockAPI"`. Caveat documented in `evaluate_agent`'s docstring: `tool_impl._active_api` is process-global mutable state (ADR E5's already-accepted limitation), so under `run_evaluation()`'s `max_concurrency=2` this snapshot isn't a hard per-run guarantee — it's still strictly more signal than the previous hardcoded 1.0, but not airtight under concurrent eval runs. Fixing that fully means revisiting E5's global-state design, which is out of scope here.

### F5. Eval dataset scope
**Status:** Open
**Context:** `create_eval_dataset()` (`src/evals.py:241-301`) hardcodes 2 examples, with an in-code comment acknowledging more are needed (different device types, regulatory classes, edge cases). Ties to C3 (real FDA data ingestion still pending) and mirrors C4's sequencing.
**Options:**
1. Expand the hardcoded list manually as scenarios are identified.
2. Derive examples from real (anonymized) client data once available.
3. Keep minimal until C3 lands — limited signal in expanding a retrieval-dependent eval dataset before real retrieval data exists.
**Recommendation:** (3) — same reasoning as C4.
**Decision:** 2026-09-02 — Adopting recommendation (3) as the decision: stays at 2 examples, no action needed. Revisit once C3 lands.

### F6. Eval snapshot seeding
**Status:** Decided — implemented
**Context:** `evaluate_agent` (pre-change) never loaded snapshot data — the only attempt was the commented-out, nonexistent `self._load_snapshot()` call noted in F1. Every eval run started from an empty `MockDatabase`, so `update_document`/`update_form_answer` paths were essentially never exercised (nothing existed yet to update) — only `create_document` paths got meaningfully eval-tested.
**Options:**
1. Hand-authored fixture snapshots checked into the repo (e.g. `tests/fixtures/eval_snapshot.json`) with a handful of pre-existing documents/forms.
2. Derive snapshots from real production data once E3 (production store) has real content.
3. Leave empty-start as intentional (only tests document creation, not updates).
**Recommendation:** (1) short-term — decouples eval realism from E3/C3 landing first, and is cheap to build now; revisit (2) once there's real production data to snapshot.
**Decision:** 2026-09-02 — Implemented option (1). Added `tests/fixtures/eval_snapshot.json` (one seed document, one seed form). `MedicalDocumentationAgent.__init__` gained a `mock_snapshot_data` parameter so `MockAPI` can actually be seeded at construction time (previously there was no way to pass snapshot data in at all — the QUICKSTART.md-documented pattern of swapping `agent.mock_api` after construction wouldn't have worked either, since it wouldn't re-run `tool_impl.configure_api()` to point tools at the new instance). `AgentEvaluator._load_snapshot()` now actually exists and loads the fixture; `evaluate_agent` passes it through.

### F7. Eval gating / promotion criteria
**Status:** Open — recommendation adopted as decision (no automation to build)
**Context:** The requirement doc language quoted in `src/evals.py`'s docstring ("only promote agents or flows to live when eval performance is satisfactory") isn't implemented anywhere — `run_evaluation()` returns raw scores with no threshold check.
**Options:**
1. Manual review of the LangSmith dashboard before any deploy (no automation).
2. Automated threshold gate in CI (fail the pipeline if completeness/correctness/safety scores drop below a bar) — depends on J1 (no CI exists yet) and G1 (testing strategy).
3. No formal gate; evals are diagnostic only.
**Recommendation:** (1) for now — CI-gated automation (2) is the right end state but is blocked on J1/G1 landing first; don't build gating logic with nothing to gate.
**Decision:** 2026-09-02 — Adopting (1): manual dashboard review, no code change. Revisit option (2) once J1 (CI) exists.

### F8. Eval cadence and cost
**Status:** Open — recommendation adopted as decision (no automation to build)
**Context:** Each eval run executes the full plan→research→create→review LLM workflow per example — real cost and latency, not free to run often. No CI exists (J1), so today evals only run when `run_evals.py` is invoked manually.
**Options:**
1. On-demand only (current, by default) until CI exists.
2. Run in CI on every PR touching `src/`.
3. Scheduled (e.g. nightly) against the full growing dataset (ties to F5).
**Recommendation:** (1) until J1 is decided — premature to pick a cadence for infrastructure that doesn't exist yet.
**Decision:** 2026-09-02 — Adopting (1): on-demand only, no code change. Revisit once J1 (CI) exists.

### F9. No evaluation of document content quality
**Status:** Open — recommendation adopted as decision (deferred, tracked explicitly)
**Context:** None of the three existing evaluators inspect generated document *content* — completeness counts todos, correctness checks tool call failures (fixed in F3), safety checks mock mode (fixed in F4). For a regulatory-document-generation product, whether a generated document actually contains required sections, cites retrieved similar devices, and uses appropriate regulatory language is arguably the most important axis to measure, and nothing evaluates it today.
**Options:**
1. Rubric-based evaluator checking for required structural elements (e.g. does content reference `search_similar_devices` results, does it cover required document sections per `DocumentType`).
2. LLM-as-judge evaluator scoring generated content against a quality/compliance rubric — LangSmith supports this pattern natively via `LangChainStringEvaluator`, already imported in `src/evals.py` but unused.
3. Defer until there's a real corpus (C3) and domain-expert-authored rubric to evaluate against — scoring content quality without real regulatory reference material has limited grounding today.
**Recommendation:** (3) short-term, but note this is the highest-value evaluator to eventually build — track it explicitly rather than letting it stay implicitly absent. (2) is the natural implementation once there's real content to judge against.
**Decision:** 2026-09-02 — Adopting (3): deliberately deferred, not forgotten. Highest-priority item to revisit once C3 (real FDA data) lands.

---

## G. Testing & Quality

### G1. Testing strategy
**Status:** Decided — unit test layer implemented; integration/eval-based layers still open
**Context:** `pytest`/`pytest-asyncio` are listed in `requirements.txt` and referenced in `SETUP.md`/`QUICKSTART.md`, but no test files existed anywhere in the repository. There was no automated way to catch regressions.
**Options:**
1. Establish unit tests for pure logic (`rollback.py`, `context_manager.py`, `models.py`) first, then integration tests for the agent workflow, then eval-based tests for retrieval/generation quality.
2. Skip unit tests, rely solely on eval-based testing (F2) for correctness.
**Recommendation:** (1) — given "lots of changes" are coming, a regression safety net for the deterministic modules (rollback, context management) should exist before that churn starts, since those are the modules where silent bugs (like the bare `except:` in B3) are easiest to introduce unnoticed.
**Decision:** 2026-09-02 — Implemented the first phase of option (1): 35 unit tests across `tests/test_rollback.py`, `tests/test_context_manager.py`, `tests/test_models.py`, covering `RollbackManager`/`RollbackAPI`/`rollback_group` (including the new E2 code), `ContextSegment`/`ContextManager`, and the pydantic models (including B3's `PlanOutput`/`PlannedTodo`). All 35 pass — actually run (not just syntax-checked) against a throwaway venv with `pytest`/`pydantic`/`pydantic-settings`/`python-dotenv`/`tiktoken` installed, then the venv was deleted; nothing about the venv is checked in.
- Added `pytest.ini` (`pythonpath = .`, `testpaths = tests`) — nothing previously made `pytest` runnable from the repo root at all.
- Added `tests/conftest.py` to set a placeholder `OPENAI_API_KEY` before collection — importing `src.config` now requires it unconditionally (ADR I1), which would otherwise block even these pure-logic tests from running without real credentials.
- Added `.gitignore` (didn't exist at all) — found necessary along the way to keep `.env`, `venv/`, and test caches out of version control.
- Found but deliberately did not fix: `ContextManager.restore_checkpoint` (`src/context_manager.py`) is a no-op stub — it accepts a checkpoint dict and returns `state` completely unchanged. Not covered by a test that would misleadingly imply that's correct behavior; flagged here instead as a known gap for whoever picks up checkpointing next.
- Not done: integration tests for the agent workflow and eval-based tests (the rest of option 1) — those need real API credentials/Qdrant to be meaningful and are a separate, larger effort.

---

## H. API / Interface Layer

### H1. Service exposure
**Status:** Open — recommendation adopted as decision (no build needed yet)
**Context:** The only entry points today are CLI scripts — `run_agent.py` (hardcoded single blood-glucose-monitor example task) and `run_evals.py` — plus, since the MCP work, `src/mcp_server.py` as a stdio entry point (see B4). There is still no HTTP/service layer; nothing in `src/` listens for network requests.
**Options:**
1. Add a REST/async API layer (e.g. FastAPI) wrapping `MedicalDocumentationAgent`, with sync submission + status polling or streaming (SSE/websockets) for long-running document generation.
2. Keep CLI-only for now, defer a service layer until there's a concrete consumer (web UI, external integration).
**Recommendation:** (2) short-term — don't build a service layer speculatively; revisit once there's a real caller (e.g. a client-facing UI) that needs one.
**Decision:** 2026-09-02 — Adopting (2): no HTTP service layer built. Revisit if/when MCP's stdio transport (B4) needs to grow into networked HTTP/SSE for a real external consumer — at that point this and B4 become the same decision.

---

## I. Security, Compliance & Multi-tenancy

### I1. Secrets and config management
**Status:** Decided — implemented (partially; option 2 still open)
**Context:** `src/config.py:30` hardcoded a placeholder credential string directly in source: `postgresql://user:password@localhost:5432/medical_documentation`. While this specific value was a placeholder, the pattern of embedding connection strings with credentials directly in a settings class (rather than only reading them from environment/secrets) was worth fixing before real credentials are ever near this file.
**Options:**
1. Require all credentialed settings to come from environment variables with no in-code fallback value (fail fast if unset, rather than silently defaulting).
2. Adopt a secrets manager (e.g. AWS/GCP Secrets Manager, Vault) for production.
**Recommendation:** (1) immediately as a low-cost fix; layer (2) on top once there's a real deployment target (J1) to integrate it with.
**Decision:** 2026-08-16 — Implemented option (1), refined by actual usage rather than applied uniformly:
- `openai_api_key`: made hard-required with no fallback (`src/config.py`) — it's used eagerly at import time across `agent.py`, `rag_pipeline.py`, `knowledge_retrieval.py`, so failing fast with a clear pydantic error beats the old silent `""` default that only broke later with a confusing OpenAI auth error.
- `database_url`: removed the fake-looking placeholder credential, but kept `Optional[str] = None` at the `Settings` level rather than hard-required — grep confirmed it's used in exactly one place (`src/db.py`), and making it hard-required would have broken importing `src.config` (and therefore nearly every module, since `src/agent.py` unconditionally imports `PostgresAPI`) for pure mock/eval-mode workflows that never touch Postgres, contradicting E5's mode split. The fail-fast check moved to `src/db.py`'s new `get_engine()`, applied lazily only when Postgres-backed storage is actually used, with a clear `RuntimeError` message.
- `langchain_api_key`: grep confirmed it's declared but never read anywhere else in `src/` (LangSmith's SDK reads `LANGCHAIN_API_KEY` from `os.environ` directly). Left `Optional[str] = None` — dropped the meaningless `""` default, not worth hard-requiring a value nothing consumes.
- Side fix: `src/db.py`'s SQLAlchemy engine/session creation was eager at module import time, which combined with the `database_url` fail-fast would have broken the same mock-mode import path. Made lazy (`get_engine()`, `_get_session_factory()`) so importing `src.db` (transitively, via `src.postgres_api`) no longer requires `DATABASE_URL`.
- Side fix: `pydantic-settings` (imported in `src/config.py`) was missing from `requirements.txt` entirely — added.

Option (2) (secrets manager for production) remains open, tied to J1.

### I2. Regulatory/compliance posture
**Status:** Open
**Context:** This system is intended to assist FDA regulatory submissions — a domain where traceability and auditability of every agent action likely matters. The rollback system's audit trail is currently only as durable as its storage backend (E1, currently in-memory = zero durability). No compliance requirements are documented anywhere in the repo.
**Options:**
1. Explicitly define what compliance/audit guarantees are actually required (retention period, immutability, who can read the audit log) before finalizing E1.
2. Proceed without a defined compliance target and revisit if/when a client or regulatory requirement surfaces.
**Recommendation:** (1) — this should be resolved early since it directly constrains E1's design (an event-sourced immutable log vs. a mutable Postgres table are very different commitments), not treated as a later add-on.
**Decision:** _(pending)_

### I3. Multi-tenancy enforcement
**Status:** Open
**Context:** `client_id` is threaded through `RollbackManager`, `MockAPI`, and `KnowledgeRetrieval` as an optional filter parameter (e.g. `src/rollback.py:71`, `:196`), but nothing enforces isolation — it's a value callers may or may not pass, not a hard boundary. There's no row-level security or namespace enforcement at the storage layer.
**Options:**
1. Enforce `client_id` as a required, non-optional parameter everywhere client data is touched, with storage-layer enforcement (e.g. Postgres row-level security once E1 lands, separate Qdrant collections/namespaces per client).
2. Leave as an application-level convention, trusted to be passed correctly by callers.
**Recommendation:** (1) before any real multi-client data coexists — the current optional/best-effort filtering is a real risk of cross-client data leakage the moment this handles more than one client's actual data.
**Decision:** _(pending)_

---

## J. Deployment & Infrastructure

### J1. Deployment target
**Status:** Open
**Context:** No `Dockerfile`, no CI configuration, and no infrastructure-as-code exist anywhere in the repo. `SETUP.md` only documents local `docker run` for Qdrant, not for the application itself.
**Options:**
1. Containerize the application (Dockerfile + docker-compose for local dev with Qdrant/Postgres), deploy to a cloud provider with managed Postgres + Qdrant Cloud.
2. Serverless/managed-platform deployment.
**Recommendation:** (1) — straightforward, matches the already-documented local Qdrant Docker pattern, and doesn't lock into a specific cloud provider prematurely.

Additional notes from the E6 discussion:
- The app image used for local compose and the one deployed to production should be the *same* Dockerfile — compose (E6) is a dev-only orchestration layer around it, not a second app definition to maintain.
- Explicit warning for whoever implements this: local compose's `env_file: .env` convention (fine for local, same trust boundary as running locally today) must not carry over to production — no secrets baked into the image via `COPY .env` or Dockerfile `ENV`/`ARG`. Ties directly to I1.
- The same compose stack (E6) is also the natural way to give **CI** real Postgres/Qdrant for integration tests (once G1/J1 land), rather than mocking the DB layer in tests — avoids needing cloud credentials in CI.
**Decision:** _(pending)_

### J2. Observability
**Status:** Open
**Context:** Beyond optional LangSmith tracing (env-gated via `LANGCHAIN_TRACING_V2`), there is no structured logging, metrics, or error tracking anywhere in `src/`.
**Options:**
1. Add structured logging (e.g. `structlog`) plus an error tracker (e.g. Sentry) alongside LangSmith tracing.
2. Rely on LangSmith alone.
**Recommendation:** (1) — LangSmith covers LLM/agent traces well but won't surface infrastructure-level failures (DB connection errors, API timeouts); those need conventional logging/error tracking regardless of the LLM tooling choice.
**Decision:** _(pending)_

---

## K. Repo & Docs Hygiene

### K1. Docs/code reconciliation
**Status:** Decided — implemented (partially)
**Context:** `QUICKSTART.md`, `SETUP.md`, and `CODE_DOCUMENTATION.md` all reference `examples/basic_usage.py` and instruct users to `cp .env.example .env` — neither file existed in the repo.
**Options:**
1. Build the missing files (`examples/basic_usage.py`, `.env.example`) to match what the docs already promise.
2. Update the docs to remove references to files that don't exist.
**Recommendation:** (1) — these are small, high-value files (a working example and an env template are exactly what a new contributor needs first) and the docs already describe what they should contain.
**Decision:** 2026-08-16 — Implemented option (1) for these two files specifically:
- `.env.example` — added, covering every var `src/config.py` reads (post-I1: `OPENAI_API_KEY` marked required, `DATABASE_URL`/`MCP_SERVER_MODE` marked optional with guidance on when they're needed). Also flagged `MOCK_API_URL`/`PRODUCTION_API_URL` as declared in `Settings` but confirmed (via grep) not read anywhere in `src/` — dead config, left in the file for now but marked as legacy rather than silently presented as load-bearing.
- `examples/basic_usage.py` — added, demonstrating the pieces `QUICKSTART.md`'s "Key Components" section already promised (rollback, RAG retrieval, knowledge retrieval, full agent run in mock mode), each as an independently callable function.

Broader K1 gap not yet addressed: `QUICKSTART.md`/`SETUP.md` still reference other stale specifics in places (e.g. troubleshooting sections written before this session's changes). Left as future cleanup rather than rewriting the docs wholesale in this pass.

### K2. Separation of engineering docs vs. fundraising material
**Status:** Blocked — do not move this file
**Context:** `Documentation/BUSINESS_PRESENTATION.md` is a 20-slide investor pitch deck (market sizing, financial projections, placeholder testimonials) living in the same directory as technical architecture docs. **Important constraint (confirmed by the user, 2026-09-02):** this file's current path is linked from an external site (samdivtech.com). Moving, renaming, or restructuring it would break that external linkage — do not do so without explicit confirmation, even though option (1) below looks like an easy, low-risk cleanup from inside the repo alone. The repo itself has no visible reference to the external link (confirmed via grep for "samdivtech" — no hits), so this constraint isn't discoverable from the code; treat this ADR note as the record of it.
**Options:**
1. Move business/fundraising material to a separate top-level directory (e.g. `Business/` or `Fundraising/`) so `Documentation/` stays purely technical. **Ruled out** given the external linkage above, unless done together with updating whatever on samdivtech.com points at the old path.
2. Leave as-is.
**Recommendation:** (2) — leave the file at its current path. The original reasoning for (1) (keeping technical and investor-facing docs visually separated) is still valid, but not worth the risk of a silent broken external link; revisit only as a coordinated change with whoever manages samdivtech.com.
**Decision:** 2026-09-02 — Decided (2), leave as-is. Attempted a move to `Business/` during this session; the user caught it before it happened and flagged the external dependency.

### K3. Unused dependency: `sentence-transformers`
**Status:** Decided — implemented
**Context:** Verified finding: `sentence-transformers` (`requirements.txt`) is unused. `src/rag_pipeline.py:39` imported `SentenceTransformer` but never instantiated or called it anywhere in the file — dense embeddings go through OpenAI's API instead (`embed_text`, `rag_pipeline.py:131`, `self.openai_client.embeddings.create(...)`). `sentence-transformers` transitively pulls in PyTorch (hundreds of MB to a couple GB), which matters concretely once J1/E6 produce a Docker image — bloats build size/time for a capability nothing uses.
**Options:**
1. Drop `sentence-transformers` from `requirements.txt`.
2. Keep it in case local embedding is wanted later.
**Recommendation:** (1) — low-risk removal, not a real architectural tradeoff; worth doing as part of writing the Dockerfile (J1) even independent of a broader K1 cleanup pass.
**Decision:** 2026-08-16 — Implemented (option 1): removed `sentence-transformers>=2.3.0` from `requirements.txt` and the dead `from sentence_transformers import SentenceTransformer` import from `src/rag_pipeline.py`. First item implemented from this ADR, chosen as the lowest-risk starting point.

---

## Summary Table

| # | Decision | Status |
|---|----------|--------|
| A1 | Source of truth for requirements | Open |
| B1 | LLM provider and model selection | Decided — partially implemented |
| B2 | Agent orchestration framework | Open |
| B3 | Planning-phase output parsing | Decided — implemented |
| B4 | Tool invocation architecture — direct calls vs. MCP | Open |
| C1 | Vector database choice | Open |
| C2 | Embedding model | Open |
| C3 | Real FDA 510(k) data ingestion | Open |
| C4 | Hybrid retrieval tuning methodology | Open |
| D1 | Global vs. client knowledge conflict resolution | Open |
| D2 | Fact-extraction pipeline | Decided — deferred |
| E1 | Rollback storage backend | Decided (direction) |
| E2 | Multi-resource transaction atomicity | Decided — implemented |
| E3 | Production document/form data store | Decided (direction) |
| E4 | Storage schema shape: JSON vs. normalized | Open |
| E5 | Mode-based storage wiring (eval vs. production) | Open |
| E6 | Local dev environment — docker-compose scope | Open |
| F1 | Mock/shadow API architecture | Open |
| F2 | Evaluation framework | Decided |
| F3 | Evaluator correctness: isolation, error signal, unused ground truth | Decided — implemented |
| F4 | Safety evaluator is a stub | Decided — implemented |
| F5 | Eval dataset scope | Decided — deferred |
| F6 | Eval snapshot seeding | Decided — implemented |
| F7 | Eval gating / promotion criteria | Decided — manual only |
| F8 | Eval cadence and cost | Decided — on-demand only |
| F9 | No evaluation of document content quality | Decided — deferred |
| G1 | Testing strategy | Decided — unit tests implemented |
| H1 | Service exposure | Decided — CLI/stdio only |
| I1 | Secrets and config management | Decided — implemented (partially) |
| I2 | Regulatory/compliance posture | Open |
| I3 | Multi-tenancy enforcement | Open |
| J1 | Deployment target | Open |
| J2 | Observability | Open |
| K1 | Docs/code reconciliation | Decided — implemented (partially) |
| K2 | Separation of engineering docs vs. fundraising material | Decided — leave as-is (external link) |
| K3 | Unused dependency: sentence-transformers | Decided — implemented |
