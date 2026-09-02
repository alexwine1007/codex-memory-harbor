# ADR 0001: Keep the Harbor core runtime-neutral

- Status: Accepted
- Date: 2026-09-03

## Context

The first working Memory Harbor implementation understands Codex session JSONL, task identity, local paths, and symlink-based continuity. The product direction is broader: preserve trustworthy, discoverable, accessible, and resumable work history across agent runtimes and harnesses such as Codex, Claude Code, and OpenClaw, as well as clients built around model providers such as DeepSeek.

Those systems do not share one history format, liveness signal, identity scheme, or native resume contract. Embedding Codex assumptions in the core would make later integrations either unsafe or cosmetic. Reducing every system to exported files would be portable, but would discard native continuity and confuse evidence readability with resumability.

## Decision

Memory Harbor will have a runtime-neutral core with two explicit seams:

1. A Runtime Adapter maps native history identity, discovery, liveness, protection, evidence membership, open, and resume capabilities into the Harbor history-object contract.
2. A Storage Adapter maps a storage backend into availability, capacity, durable write, integrity verification, materialization, restore, and exit capabilities.

The core owns admission policy, transactional docking, evidence receipts, manifests, indexing, recall, restore orchestration, and foreground resource budgets. It does not own a runtime's private session semantics or a storage provider's credential flow.

Adapters publish a capability matrix. The core reports only independently verified capabilities and never upgrades evidence readability into native open or resume support.

The Codex integration remains the first concrete Runtime Adapter. We will document the candidate interface from it, but will not call that interface stable until a second real Runtime Adapter exercises the same seam. This follows the rule that one adapter makes a seam hypothetical; two adapters make it real.

## Alternatives considered

### Keep a Codex-specific product

This minimizes near-term work but contradicts the product direction and spreads Codex assumptions through storage, indexing, UI, and evidence formats.

### Build a universal export archive

This makes ingestion easy but preserves only files. It cannot honestly promise native discovery, opening, or continuation and would collapse distinct continuity levels into one misleading status.

### Standardize the adapter interface before a second integration

This appears architecturally clean but would freeze assumptions learned from only one runtime. The resulting interface would likely be wide, leaky, and expensive to change.

## Consequences

- Current Codex behavior remains an implementation and evidence baseline, not the universal data model.
- Runtime-specific code must move behind the Runtime Adapter seam as that seam is extracted.
- Storage-specific behavior and credentials must remain behind the Storage Adapter seam.
- Product UI and receipts must display capability level and adapter version.
- Adding a model provider alone does not create a Runtime Adapter; a concrete harness with a persistent history contract is required.
- The second runtime integration is an architectural validation milestone, not merely another import format.
