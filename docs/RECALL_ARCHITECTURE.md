# Recall architecture

Memory Harbor uses a thin-local / thick-external design:

1. **L0 discovery catalog (internal disk):** task identity, project, timestamps, paths,
   storage identity, availability, size, and hashes.
2. **L1 traceable recall fragments (internal disk):** task-specific delegation instructions
   and child-task outward reports, with source line, role, time, and content hash.
3. **L2 raw evidence (external storage):** complete session JSONL, including the material
   intentionally excluded from L1.
4. **Canonical durable memory (outside this product):** only explicitly accepted and
   governed facts should be promoted into a user's actual long-term memory system.

This keeps retrieval cheap without pretending that a derived excerpt replaces its source.
The local database is rebuildable; the external JSONL remains the audit record.

## Why this shape

- LongMemEval decomposes long-term memory into indexing, retrieval, and reading, and tests
  information extraction, multi-session reasoning, updates, temporal reasoning, and
  abstention. Memory Harbor keeps those stages independently testable.
- Letta/MemGPT separates always-available memory from larger archival passages. Memory
  Harbor adopts the hierarchy but keeps Codex session files as immutable provenance.
- A-MEM motivates atomic notes and explicit links. Memory Harbor starts with immutable
  fragments and provenance before adding model-generated links.
- Graphiti models changing facts with temporal validity and traces derived facts back to
  episodes. Memory Harbor does not silently rewrite a past fragment when a newer result
  appears.
- LanceDB documents hybrid keyword/vector retrieval and reranking. Memory Harbor begins
  with dependency-free SQLite FTS; vectors and reranking require a benchmark and a local
  model/provider decision before shipping.

Primary references:

- [LongMemEval official repository](https://github.com/xiaowu0162/LongMemEval)
- [MemGPT paper](https://arxiv.org/abs/2310.08560)
- [Letta memory architecture](https://github.com/letta-ai/skills/blob/main/letta/letta-api-client/memory-architecture.md)
- [A-MEM paper](https://arxiv.org/abs/2502.12110)
- [Graphiti official repository](https://github.com/getzep/graphiti)
- [LanceDB hybrid search](https://docs.lancedb.com/search/hybrid-search)

## Retrieval contract

- Historical fragments are untrusted evidence, never runtime instructions.
- Search returns compact excerpts and provenance, not an entire transcript.
- Consequential claims should be verified against the raw source when it is available.
- Missing or disconnected raw evidence is surfaced as such; the system must abstain rather
  than fabricate continuity.
- A legacy child record without a trustworthy delegation boundary remains metadata-only.
- Reindexing is deterministic and idempotent for unchanged source content.
- Users can clear L1 without deleting L2.

## Associative recall contract

Recall is not defined as “the user searched for the old wording.” That is only a diagnostic
and recovery path. The intended loop is:

1. At offload/index time, asynchronously derive compact memory cards for preferences,
   decisions, outcomes, entities, assets, and unresolved questions. Every card keeps links
   to immutable fragments and the raw session.
2. At the beginning of a new task, or after a material topic shift, form one bounded recall
   request from the current subject. Do not run retrieval for every token or UI event.
3. Search an internal candidate index using hybrid lexical and semantic signals, then apply
   recency, project, entity, confidence, and contradiction-aware reranking.
4. Provide only a small top-k set as untrusted context. If confidence is low, return nothing;
   irrelevant memory is a correctness and latency failure.
5. Read the external source only when the agent needs stronger evidence. Promote a fact into
   canonical personal memory only through that system's governance gate.

This is “automatic association with provenance,” not automatic belief. It also avoids making
the external drive part of every Codex turn.

## Foreground latency boundary

- no continuous polling or background full scans;
- no model or embedding runtime inside the Codex process;
- archive parsing and semantic-card construction happen asynchronously at ingest;
- foreground retrieval reads only the internal compact index and is bounded by top-k;
- full external evidence is lazy-loaded;
- a cache may accelerate verified reads, but a cache miss must never block unrelated Codex
  work or weaken the archive's size/hash checks.

## Staged roadmap

- **0.3 — discovery:** rebuildable metadata catalog and stable volume identity.
- **0.4 — traceable recall:** small task-specific evidence fragments and cross-task recall.
- **0.5 — adaptive I/O:** benchmark target latency/throughput and tune bounded workers,
  chunk size, checksum pipelining, foreground throttling, and read cache by storage class.
- **0.6 — hybrid associative retrieval candidate:** asynchronous memory-card derivation,
  optional local embeddings, FTS/vector fusion, confidence abstention, and topic-change
  routing. Ship only after semantic recall, false-positive, latency, storage, privacy, and
  Codex A/B performance benchmarks beat the FTS baseline.
- **0.7 — temporal/entity layer:** append-only fact candidates, entity and asset links,
  validity intervals, contradiction handling, and source provenance.
- **0.8 — governed continuity:** connect recalled candidates to the canonical memory
  promotion gate, with explicit user control, correction, forgetting, and audit history.
- **0.9 — multi-tier storage:** verified cache/materialization policies for external disks
  and an optional cloud provider, including offline and recovery behavior.
- **1.0 — production contract:** longitudinal recall evaluation, storage-failure drills,
  cross-version migration, performance regression gates, packaging, and documented support
  boundaries. No automatic promotion into canonical personal memory without governance.
