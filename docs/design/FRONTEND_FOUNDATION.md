# Memory Harbor Frontend Foundation

- Status: Draft 0.1
- Date: 2026-09-03
- Applies to: macOS compact card, dashboard, and future runtime/storage adapter surfaces
- Implementation status: target design; not shipped unless a section says otherwise

## Product role

The interface exists to make continuity trustworthy and understandable. It is not a disk
cleaner with a decorative dashboard. At every point it should answer three questions:

1. Is my work history safe and accessible?
2. Does anything need my attention?
3. What will happen before I authorize a state-changing action?

The visual hierarchy is therefore:

```text
continuity health > required attention > evidence > available action > capacity savings
```

Saved bytes are useful, but they are never more prominent than integrity or accessibility.

## Current-state assessment

The 0.4.4 beta has a coherent dark MVP rather than a complete product design. It already
provides a native compact card, a WebKit dashboard, storage selection, summary cards, a
project/task tree, search, protected-item controls, migration confirmation, progress,
audit, restore, and local-backup release.

The main design debt is structural:

- the dashboard still presents Memory Harbor as Codex storage optimization;
- browse, recall, docking, integrity, recovery, and connection management share one page;
- `0.0 B` remains the hero even when the more meaningful state is “all docked history is
  currently accessible”;
- `整理`, `优化`, `迁移`, `停泊`, and `释放` overlap without one action vocabulary;
- compact Cocoa and dashboard CSS repeat visual decisions without a shared specification;
- the frontend is one global-state JavaScript file and one compressed stylesheet;
- narrow layouts silently hide data columns rather than providing a deliberate compact row;
- 9–11 px labels, glyph icons, and weak focus treatment do not meet the target accessibility
  standard;
- there are no state-fixture screenshots, keyboard-flow tests, or visual regression gates.

## Experience principles

### Proof before reassurance

Do not display “safe”, “healthy”, or “complete” without a nearby scope and last-verification
time. A receipt or inspection path must be available for consequential claims.

### One primary decision per view

A page can expose secondary inspection actions, but it has one visually dominant next step.
Destructive or irreversible actions are never visually paired with routine navigation.

### Issues first, storage second

When everything is healthy, the interface may summarize capacity. When any continuity issue
exists, the issue becomes the hero and capacity moves down the hierarchy.

### Capabilities, not vendor promises

Each Runtime Adapter and Storage Adapter shows the capabilities it has actually passed.
Unsupported native open or resume behavior is explicit, not hidden behind a generic online
badge.

### Calm infrastructure

The product should feel quiet, durable, and precise. Retain the current violet/teal identity,
but reduce decorative glow and glass effects. The harbor metaphor informs language and
structure; it should not become nautical ornament.

### Progressive disclosure

Default views show health, identity, scope, and the next decision. Hashes, paths, adapter
versions, stage timings, and raw receipts remain one inspection step away.

## Information architecture

The dashboard becomes a stable application shell rather than one long operations page.

```text
Memory Harbor
├── Overview          continuity health and attention
├── History           cross-runtime discovery and recall
├── Docking           candidates, plans, active transfers
├── Integrity         audits, faults, and recovery
├── Connections       runtime and storage adapters
├── Activity          receipts and lifecycle events
└── Settings          retention, privacy, and local behavior
```

Global shell:

```text
┌──────────────┬───────────────────────────────────────────────────────┐
│ Memory Harbor│ Page title                         Global health       │
│              ├───────────────────────────────────────────────────────┤
│ Overview     │                                                       │
│ History      │                    Page content                       │
│ Docking      │                                                       │
│ Integrity    │                                                       │
│ Connections │                                                       │
│ Activity     │                                                       │
│ Settings     ├───────────────────────────────────────────────────────┤
│              │ Contextual selection/action bar, only when required  │
└──────────────┴───────────────────────────────────────────────────────┘
```

The global health control opens a small status panel with Runtime, storage, index, and
last-audit state. It is not also used as the storage picker.

## Page contracts

### Overview

Primary question: “Can I trust and reach my history right now?”

Required regions:

- continuity hero: healthy, attention required, working, or unavailable;
- verified scope: accessible objects / docked objects and last verification time;
- issues requiring action, ordered by data risk;
- Runtime and storage connection summary;
- capacity summary, including internal occupancy and retained local copies;
- recent evidence receipts.

When no object is eligible for docking, the hero says the harbor is healthy. It does not
make `0.0 B` the largest object on screen.

### History

Primary question: “Where is the work I need, and what can I do with it?”

- search accepts topic, title, project, runtime identity, task identity, and date;
- filters include Runtime, project, continuity capability, location, protection, and fault;
- result rows expose identity, source Runtime, latest evidence time, storage state, and
  verified capability level;
- the detail drawer separates summary, recall leads, provenance, integrity, and available
  Runtime actions;
- an offline source remains discoverable; opening raw evidence explains which storage is
  required.

### Docking

Primary question: “What can safely leave active storage, and exactly what will happen?”

- candidates are grouped by Runtime and project;
- every exclusion explains why the object is protected;
- planning is read-only and displays destination, byte count, required stages, estimated
  duration, resource policy, and local-copy choice;
- execution progress names the current safety stage rather than showing an unexplained
  percentage;
- the completion view links to per-object evidence receipts;
- a first error stops the batch and distinguishes completed, recoverable, and untouched
  objects.

### Integrity

Primary question: “What is degraded, why, and what is the safest recovery?”

- issues precede healthy objects;
- media absent, mount changed, permission denied, integrity failed, adapter incompatible,
  and native-open failure are distinct states;
- automatic repair is offered only when its complete identity and hash contract is met;
- manual recovery explains required media, expected effect, and rollback before acting;
- bulk audit is a named, cancellable operation with bounded scope.

### Connections

Primary question: “Which Runtimes and storage targets are connected, and what can each do?”

Runtime cards show adapter name/version, discovered-object count, last successful scan, and
verified C0–C3 capability matrix. Storage cards show provider, identity, online state,
capacity, durability capability, filesystem/materialization mode, and latest probe.

“Connected” never means “all capabilities supported”.

### Activity

Primary question: “What changed, and what proves it?”

Receipts are append-oriented and filterable by operation, object, adapter, result, and time.
The default row shows human-readable outcome and scope; expanded evidence shows hashes,
paths, stage timings, versions, and error details without exposing credentials or unrelated
history text.

### Settings

Settings cover retention policy, protected projects/objects, index clearing, startup
behavior, resource budget, and privacy controls. Dangerous settings state their effect on
continuity. Credential material is delegated to supported system or provider authorization
flows and never displayed back.

## Compact card

The card is an ambient status surface, not a miniature dashboard.

```text
┌────────────────────────────────────┐
│  Memory Harbor          Healthy ●  │
│                                    │
│  All docked history is accessible  │
│  194 / 194 verified                │
│                                    │
│  Alex's Disk · online    Open ›    │
└────────────────────────────────────┘
```

The count is illustrative, not hard-coded product copy.

Card modes:

| Mode | Primary message | Secondary evidence | Action |
| --- | --- | --- | --- |
| Healthy | All declared continuity checks pass | accessible / docked, last checked | Open Harbor |
| Opportunity | Safe docking candidates are available | objects and reclaimable capacity | Review plan |
| Working | Docking or audit is active | named stage and progress | Open progress |
| Attention | A recoverable issue needs action | affected objects and risk | Review issue |
| Unavailable | Status cannot be established | Runtime/storage reason | Diagnose |

The card never offers one-click destructive work. It opens the relevant dashboard page.

## State model

### History lifecycle

```text
Active / Protected / Eligible
              │ plan
              ▼
           Planned
              │ stage + persist + verify
              ▼
   Verified external candidate
              │ preserve Runtime continuity
              ▼
 Independently verified docking
       ┌──────┴────────┐
       ▼               ▼
Docked with       Docked external
local copy        primary
       └──────┬────────┘
              │ restore
              ▼
          Local again
```

The UI receives a lifecycle state and available actions from the core. It does not infer
safety from button history or HTTP success alone.

### Fault vocabulary

| State | Meaning | Default UI treatment |
| --- | --- | --- |
| `storage_unmounted` | known storage identity is absent | amber, reconnect instructions |
| `mount_changed` | identity matches but native path changed | amber, offer verified repair |
| `permission_denied` | object exists but access is refused | amber, explain system permission |
| `integrity_failed` | required size/hash evidence disagrees | red, block release and restore |
| `runtime_unavailable` | Runtime cannot currently inspect/open | amber, retain evidence state |
| `adapter_incompatible` | adapter/runtime version contract failed | red, block mutation |
| `native_open_failed` | evidence is present but Runtime open failed | amber, distinguish from data loss |

Color supplements text and iconography; it never carries the state alone.

## Action language

Canonical actions:

| Action | Meaning |
| --- | --- |
| Review docking plan | create a read-only plan for selected objects |
| Dock | perform the verified transition to cold storage |
| Keep local copy | retain the rollback entity after docking |
| Release local copy | permanently remove a separately retained local entity after audit |
| Verify integrity | compare the evidence required by the applicable contract |
| Restore locally | return to an ordinary local Runtime-readable entity |
| Open in Runtime | use the Runtime's declared native-open capability |
| Read evidence | inspect preserved source evidence without implying resumability |

Avoid `一键优化`: it hides the state transition and makes a safety-critical operation sound
like routine cleanup. Chinese product copy should use `查看停泊方案`, `停泊`, `保留本地副本`,
`释放本地副本`, `验证完整性`, and `恢复到本机` consistently.

## Harbor UI visual system

### Personality

Quiet, dependable, local, and inspectable. Avoid cyberpunk storage imagery, excessive neon,
and gamified “cleanup scores”. Use generous dark space, crisp boundaries, and restrained
depth to communicate durable infrastructure.

### Color roles

| Token | Target role |
| --- | --- |
| `surface.canvas` | neutral near-black application background |
| `surface.raised` | primary cards and drawers |
| `surface.selected` | selected history rows and navigation |
| `accent.primary` | violet identity and ordinary primary action |
| `accent.secondary` | teal verification and active connection |
| `status.healthy` | verified healthy state only |
| `status.attention` | degraded but recoverable state |
| `status.danger` | integrity risk or irreversible action |
| `text.primary` | high-contrast title and values |
| `text.secondary` | explanatory copy, never below AA contrast |

Exact color values are chosen during visual exploration and recorded as shared tokens for
Cocoa and CSS. Semantic states must not reuse decorative accent colors arbitrarily.

### Type and spacing

- base body: 14 px / 20 px;
- secondary metadata: minimum 12 px / 16 px;
- compact-card status: minimum 13 px;
- page title: 24–28 px; overview metric: 36–48 px, not 68 px by default;
- spacing scale: 4, 8, 12, 16, 24, 32, 48;
- interactive target: at least 32 × 32 px, with 40 px preferred for primary actions;
- table/list density may be compact, but never by dropping below the minimum metadata size.

### Shape and depth

- use 8–12 px radii for controls and 14–18 px for major surfaces;
- reserve the 24–28 px radius for the compact card or a single hero surface;
- prefer solid layered surfaces over pervasive transparency;
- shadows communicate window or drawer elevation, not every card boundary.

### Motion

- 120–200 ms for state transitions;
- progress reflects real stage changes;
- no looping animation while idle;
- honor reduced-motion settings;
- a failed or paused operation does not continue visually advancing.

## Reusable interface modules

The target frontend should concentrate complexity behind a small set of modules:

- `HarborClient`: authenticated localhost transport, error normalization, cancellation, and
  response-version checks;
- `HarborStore`: one normalized application snapshot and explicit transitions;
- `CapabilityPresenter`: maps adapter capability evidence to consistent C0–C3 language;
- `OperationPresenter`: maps plans, progress stages, failures, and receipts to UI state;
- `HistoryExplorer`: query, filters, selection, hierarchy, and detail drawer;
- `StatusSurface`: shared semantic presentation contract for overview and compact Cocoa.

The Cocoa card and Web dashboard do not need to share rendering code. They must share state
names, copy, semantic color roles, icon meanings, and acceptance fixtures.

Suggested dependency-free source shape:

```text
dashboard/
├── index.html
├── app.js                 composition only
├── client/harbor-client.js
├── state/harbor-store.js
├── presenters/
├── views/
├── components/
├── styles/tokens.css
├── styles/base.css
├── styles/components.css
└── fixtures/
```

Do not introduce a framework merely to obtain folders. Adopt one only if measured interface
complexity, accessibility, or testability justifies its resident and build costs.

## Accessibility and localization gates

- all workflows are keyboard-complete, including tree navigation and dialogs;
- focus is visible against every surface;
- controls have names that describe actions rather than icon appearance;
- text and status contrast meet WCAG AA;
- status is never color-only;
- zoom at 200% retains every required action and does not silently hide evidence;
- reduced motion is respected;
- Chinese is the first complete locale, but interface copy moves to localization keys during
  the refactor so Runtime and storage terminology can be translated consistently.

## Verification strategy

Before connecting redesigned mutation controls to real history:

1. Build deterministic fixtures for healthy, empty, eligible, working, offline, permission
   denied, integrity failed, partial batch failure, and adapter-incompatible states.
2. Render Overview, History, Docking, Integrity, and compact-card variants from fixtures.
3. Add screenshot baselines at standard and minimum window sizes.
4. Add keyboard and dialog-focus tests.
5. Connect read-only live endpoints and verify displayed counts against CLI output.
6. Connect planning to synthetic data.
7. Connect mutation only after the durable docking module and its fault-injection gate pass.

## Delivery slices

### F0 — foundation

Approve this information architecture, action vocabulary, compact-card hierarchy, and visual
personality. Produce low-fidelity layouts before production styling.

### F1 — shell and read-only views

Implement shared tokens, application shell, Overview, History, Connections, and fixture
states. No real mutation behavior changes.

### F2 — durable operation experience

After the core durability gate passes, implement Docking, Integrity, progress stages,
failure recovery, and evidence-receipt inspection against synthetic fixtures, then live data.

### F3 — multi-runtime proof

Display the Codex adapter capability matrix, add the second real Runtime Adapter, and verify
that the shell, History, Integrity, and Activity views need no vendor-specific forks.

## F0 acceptance checklist

- every primary user question has one owning page;
- compact card communicates health before reclaimable bytes;
- no consequential state is represented by one generic “online” badge;
- action language distinguishes plan, dock, verify, release, restore, open, and read;
- every target page has healthy, empty, working, degraded, and error behavior;
- the design is Runtime-neutral while current Codex-only delivery remains explicit;
- implementation and screenshot testing can proceed without real user-history mutations.
