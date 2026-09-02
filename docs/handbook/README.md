# Memory Harbor Technical Handbook

- Status: In progress
- Started: 2026-09-03

This handbook is the technical entry point for building, auditing, extending, packaging,
and recovering Memory Harbor. It distinguishes current implementation evidence from target
architecture. A document marked draft is not a shipped capability.

## Reading order

1. [Product north star](../../PRODUCT_NORTH_STAR.zh-CN.md) — why the product exists and how
   it is judged.
2. [Domain language](../../CONTEXT.md) — canonical Runtime, history, docking, continuity,
   adapter, recall, and receipt terms.
3. [Runtime-neutral core decision](../adr/0001-runtime-neutral-core.md) — why Runtime and
   Storage Adapter seams exist.
4. [Current desktop and dashboard](desktop-and-dashboard.md) — how the 0.4.4 beta actually
   runs today.
5. [Recall architecture](../RECALL_ARCHITECTURE.md) — thin-local / thick-external indexing
   and evidence retrieval.
6. [Tested boundaries](../../skills/codex-memory-harbor/references/tested-boundaries.md) —
   the evidence behind current support claims.
7. [Frontend foundation](../design/FRONTEND_FOUNDATION.md) — target information architecture,
   design system, state model, and UI verification plan.

## Handbook map

| Chapter | Status | Purpose |
| --- | --- | --- |
| Product north star | Draft 0.2 | product direction and acceptance metrics |
| Domain language | Current | stable vocabulary without implementation detail |
| ADR 0001 | Accepted | runtime-neutral core and adapter seams |
| Desktop and dashboard | Current 0.4.4 | process topology, local interface, lifecycle, and known debt |
| Recall architecture | Current plus roadmap | local discovery, evidence fragments, and associative recall direction |
| Tested boundaries | Evidence ledger | verified and unverified environment claims |
| Frontend foundation | Draft 0.1 | target experience and implementation slices |
| Docking transaction | Planned | durable write, verification, link/materialization, rollback, and recovery |
| Manifest and receipts | Planned | schemas, compatibility, provenance, and export |
| Runtime Adapter authoring | Planned | history discovery, liveness, capabilities, and conformance suite |
| Storage Adapter authoring | Planned | persistence, identity, availability, materialization, and credentials |
| Installation and upgrade | Planned | supported platforms, signing, permissions, migration, and rollback |
| Testing and release | Planned | fixtures, fault injection, performance gates, packaging, and promotion |

Planned rows describe the documentation backlog. They are not empty files and do not imply
that the underlying capability exists.

## Documentation rules

- Lead each technical chapter with `Status`, `Applies to`, and `Last verified`.
- Separate current behavior, target behavior, and tested evidence.
- Link a support claim to a repeatable command, test, or evidence ledger entry.
- Do not copy dated benchmark numbers into undated prose.
- Never include credentials, browser state, private conversation text, or real secret values.
- Use the canonical language in `CONTEXT.md`; introduce new domain terms there first.
- Update the handbook in the same commit as an interface or safety-contract change.
- Keep vendor-specific details in adapter chapters rather than leaking them into the core
  contract.

## Current scope

The only delivered Runtime Adapter is Codex on macOS. The only delivered Storage Adapter is
an attached external volume. The handbook is designed to grow toward additional runtimes
and storage backends, but it must not describe Claude Code, OpenClaw, DeepSeek-related
harnesses, network storage, or cloud storage as shipped before their own conformance and
recovery evidence exists.
