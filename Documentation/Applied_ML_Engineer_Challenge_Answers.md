# Applied ML Engineer Challenge – Responses

## 1. Rollbacks

> You are building an agent that performs potentially destructive actions (e.g. write, delete documents or change answers of a form in the DB). One option is to have humans in the loop to approve destructive actions. However, this limits agent autonomy and their ability to run for a long time.
>
> **Question:** How would you implement rollbacks for tool calls that perform actions calling an internal API that sits in front of a DB so that if the user realizes the agent made mistakes it can undo the changes that were written to the DB?

**Response**

To make destructive agent actions recoverable without constant human supervision, I designed the tooling layer around a transaction-aware rollback service.

- **Pre-action snapshots.** Every tool call that can mutate state first asks the internal API for the current representation of the target resource. The snapshot is stored alongside contextual metadata (resource type, IDs, timestamp, calling user/agent) in a lightweight rollback store.
- **Transaction identifiers.** The API returns a structured result that includes the newly created or updated resource _and_ the transaction identifier produced by the rollback manager. This identifier is exposed to the user so a single command can revert the specific change at any time.
- **Structured rollback endpoint.** The rollback API provides `POST /rollback` with the transaction id. When invoked, it fetches the stored snapshot and applies the inverse operation (delete becomes re-insert, update restores previous fields, etc.).
- **Audit trail and safeguards.** Every transaction records the before/after payloads, timestamps, actor, and client. Failed rollbacks are surfaced to monitoring, while successful rollbacks mark the transaction as `ROLLED_BACK` so it is excluded from future change sets.

**Advantages**
- Keeps the agent autonomous; humans intervene only when something needs to be undone.
- Offers deterministic rollbacks with a single API call.
- Maintains complete history for compliance and post-mortems.

**Disadvantages**
- Requires additional storage proportional to the size of snapshots.
- Complexity increases when actions have side effects across multiple resources; batch transactions must be rolled back atomically.

---

## 2. Evals

> You have to build an eval for agent traces where the agent worked on production data with tools that connect to a production API / database.
>
> **Scenario:** Assuming you run a trace with n steps through the eval where you expect that in step n+1 the agent would call a tool that normally would perform an action in the production database.
>
> **Question:** How would you build the system, so the agent could actually do that without changing information in the production database?

**Response**

The evaluation environment mirrors production but isolates writes through a mock/shadow API.

- **Dual endpoints.** The orchestration layer exposes both the production API and a mock API. Evaluations switch the agent’s tool endpoints to the mock service, keeping live workloads untouched.
- **Snapshot bootstrapping.** Before the evaluation run starts, the mock database is seeded with a fresh snapshot from production. Reads feel real, but writes only affect the sandboxed store.
- **Transaction logging and reset.** The mock API reuses the same rollback manager so every change is tracked. After each evaluation run completes, the mock store resets to the baseline snapshot, guaranteeing clean starting state.
- **Selective passthrough.** When an evaluation requires the latest read-only data (e.g., reference catalogues), the mock API can forward GET requests to production while continuing to intercept and sandbox any mutation.
- **LangSmith integration.** Each evaluation run is traced through LangSmith. Custom evaluators check completeness (todos finished), correctness (no errors in transaction log), and safety (asserting the run used the mock endpoint).

**Advantages**
- Allows the evaluation to observe and score realistic behaviour, including the final write step.
- Prevents accidental production changes during experimentation.
- Provides a full audit log of the simulated actions for analysis.

**Disadvantages**
- Requires reliable snapshot pipelines; stale snapshots can skew evaluation accuracy.
- Additional infrastructure footprint (mock API + sandbox database).

---

## 3. RAG Pipeline Improvements

> How would you improve the RAG pipeline to find similar devices to a user's current device from a corpus of 300,000 510k summary documents (https://www.fda.gov/medical-devices/premarket-notification-510k/content-510k)?
>
> **Current setup:**
> 1. Conversion of all 510k summaries to markdown documents
> 2. Chunk each document in fixed 300–400 token segments
> 3. Embed as dense vectors using OAI text-embedding-ada-002
> 4. Store in Qdrant
> 5. Agent creates query string from device information
> 6. Query gets embedded and cosine similarity is calculated against vectors in Qdrant
> 7. n most similar chunks are returned; related documents of similar devices are returned to agent for review. Agent can repeat or determine that similar devices have been found
>
> **Questions:**
> 1. How can this be improved? Explain architecture, methods, technologies that you would use.
> 2. How would you evaluate which approach works best?

**Response**

I evolved the retrieval stack into a hybrid semantic + lexical pipeline that preserves more context and scales better.

### Architecture & Methods

1. **Semantic chunking.** Instead of blind 300–400 token splits, documents are segmented by paragraph/sentence similarity to keep cohesive ideas together. Overlaps preserve continuity for long descriptions.
2. **Hybrid retrieval.** Each chunk receives a dense embedding (OpenAI) and is simultaneously indexed in a sparse BM25 structure. Queries fetch dense matches from Qdrant (HNSW index) and sparse matches from BM25; scores are combined via weighted fusion.
3. **Metadata-rich payloads.** Qdrant payloads store device category, submission year, manufacturer, and section labels so the agent can filter or re-rank by clinically relevant facets.
4. **Cross-encoder re-ranking (optional).** For high-precision lists, a transformer cross-encoder re-scores the top 50 dense+sparse candidates to surface the few truly similar submissions.
5. **Feedback-aware refinement.** Agents can flag a retrieved document as relevant/irrelevant—those labels feed retraining of the query expansion layer and adjust sparse/dense weights.

### Technologies
- **Qdrant** (HNSW) for vector storage and payload filtering.
- **OpenAI embeddings** for dense representations.
- **rank-bm25** (or Elasticsearch) for lexical matching.
- **LangChain/LangGraph** orchestrating retrieval, filtering, and re-ranking steps.
- **Task-specific cross-encoder** (optional fine-tuned transformer) for re-ranking.

### Evaluation Strategy
- **Offline metrics.** Build labelled pairs of "device A" and known similar submissions; compute recall@k, precision@k, MRR across candidate architectures.
- **A/B tracing.** Log retrieval steps during real agent sessions with LangSmith. Compare downstream document quality and agent confidence when switching retrieval strategies.
- **Human review loops.** Regulatory specialists periodically review retrieved sets to ensure medical relevance, not just textual similarity.
- **Latency & cost tracking.** Monitor response times for dense-only, sparse-only, and hybrid runs. Choose weights that keep latency within acceptable bounds for interactive use.

**Advantages**
- Hybrid scoring covers both terminology overlap and conceptual similarity.
- Semantic chunking reduces noise and duplication in results.
- Fine-grained metadata enables targeted filtering (e.g., same device class).

**Disadvantages**
- Additional indexing steps and infrastructure (two indexes) increase maintenance.
- Cross-encoder re-ranking adds latency; must be budgeted or cached.

---

## 4. Knowledge Retrieval

> You have to build knowledge storage and retrieval capability for an agent so that it has necessary context available for a given task (e.g. the client mentioned in a call that they are aiming for the clinical trial start in early 2026 and the trial involves 100 participants)
>
> **Two parts:**
> 1. Consultant knowledge (globally available)
> 2. Client knowledge (information about device scoped to organization)
>
> **Assume:** The knowledge is provided in small chunks from a pipeline that parses it from conversations (slack, discord, call recording). From the example above:
> - clinical trial starting early 2026 (client info)
> - trial involves 100 participants (client info)
> - One should not ask FDA open-ended questions for presubmission (global info)
>
> **Questions:**
> 1. Explain architecture, methods and technologies that you would use for indexing and retrieval.
> 2. Explain how redundant, conflicting or newer, replacing information would be managed continuously.

**Response**

The knowledge layer sits alongside the RAG stack but is tailored for structured client context.

### Architecture & Technologies
- **Dual collections.** Two Qdrant collections: `global_knowledge` for evergreen policies/guidelines and `client_knowledge` scoped by organization ID.
- **Chunk ingestion pipeline.** Conversation transcripts are parsed into atomic facts (speaker, timestamp, source). Each fact is embedded and stored with metadata such as client ID, device, confidence, and recency.
- **Unified retrieval.** A single query runs against both stores. Results are scored by semantic similarity, recency, and source confidence. Client-specific facts receive a recency boost to keep latest directions visible.
- **Conflict detection.** Retrieved facts are compared pairwise—high semantic similarity with inconsistent values flags a conflict. Conflicting pairs are surfaced to the user or marked for resolution.

### Managing Redundancy & Updates
- **Versioning via timestamps.** Newer chunks automatically supersede older ones during scoring; however, older conflicting entries remain for audit until explicitly resolved.
- **Confidence weighting.** Facts derived from authoritative documents outweigh offhand conversation notes.
- **Change alerts.** When a new chunk contradicts a high-confidence existing fact, the system records an alert for manual follow-up.
- **Decay policies.** Stale client information can be decayed or archived after configurable windows.

**Advantages**
- Keeps consultant-wide best practices separate from client-specific commitments.
- Allows the agent to blend hard regulatory facts with the client’s latest plans.
- Conflict detection prevents the agent from amplifying outdated instructions.

**Disadvantages**
- Requires diligent metadata capture at ingestion time.
- Conflict detection is only as good as embedding similarity; nuanced contradictions may need human review.

---

## 5. Long Context Work

> You have to build an agent that gets a task and then gets to work creating 10+ documents for a specific device which involves researching regulatory requirements, clinical data, similar devices etc. The agent has access to tools to pull in the information it needs and the ability to perform document retrieval and mutations.
>
> **Current setup:**
> 1. Agent has access to todo list to track the actions it wants to perform and to track the progress
> 2. Context compression after 60% of context window is used
>
> **Question:** How do you make sure the agent does not suffer context drift and pollution and is able to complete the task?

**Response**

I structured the agent workflow into dedicated workspaces with proactive context hygiene.

1. **Segmented context buffers.** Each major topic (regulatory requirements, clinical data, similar devices, draft outputs) has its own buffer. Information flows into the relevant segment only.
2. **Hierarchical planning.** The todo list records parent/child tasks so the agent only focuses on the current subtask, reducing cross-talk between objectives.
3. **Relevance-based compression.** When a segment crosses 60% of the context limit, the context manager ranks entries by recency and task relevance. Low-value entries are summarized or dropped; high-value notes remain intact.
4. **Checkpointing.** After finishing major subtasks (e.g., drafting a document), the state is checkpointed to external storage. If later compression trims key details, the agent can reload them from the checkpoint.
5. **External knowledge offloading.** Long-form references (full regulatory excerpts, raw study data) are stored in the knowledge base and re-fetched on demand, keeping the working context lean.
6. **Review loop.** A dedicated review phase looks for inconsistencies or missing dependencies before the workflow completes.

**Advantages**
- Keeps the agent focused on one document at a time, minimizing context bleed.
- Compression decisions are explainable and reversible via checkpoints.
- The agent can recover critical details even after aggressive pruning.

**Disadvantages**
- Requires careful tuning of relevance scoring to avoid trimming necessary context.
- More moving parts (segments, checkpoints) increases orchestration complexity.

---

## Suggestions

Beyond the specific answers above, the overall system would benefit from a few structural improvements:

1. **Automatic rollback application.** The document assumes that calling the rollback endpoint reinstates the previous state immediately. Designing the API layer so that rollbacks execute the stored inverse operation (instead of merely returning the snapshot) would deliver a true single-call undo experience.
2. **Clear production vs. mock wiring.** The architecture relies on production traffic using the live API and evaluation traffic using the mock/shadow API. Ensuring that tools receive the appropriate API client based on mode will keep the separation clean and maintain the audit trail the business expects.
3. **Fully wired context management.** Segmented buffers, relevance-based compression at 60 % usage, and checkpointing should be integrated throughout the workflow so the agent remains focused and avoids context drift during long document-building sessions.
4. **Explicit dependency handling.** Components like the hybrid retrieval stack depend on services such as Qdrant; documenting (or lazily checking) those dependencies avoids surprises in different environments.

Implementing these ideas would further align the platform with the intent of the assignment and make the solution more robust in real-world use.
