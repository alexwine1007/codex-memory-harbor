# Desktop and Dashboard

- Status: Current implementation with documented design debt
- Applies to: Memory Harbor 0.4.4-beta.1 on macOS
- Last verified: 2026-09-03

## Purpose

The desktop layer keeps a small, low-cost status card available while isolating the richer
dashboard and its Python process. This chapter documents what exists today. The target
experience is defined separately in the [Frontend Foundation](../design/FRONTEND_FOUNDATION.md).

## Process topology

```text
Memory Harbor compact owner (native Cocoa, accessory app)
    │ user opens details
    ▼
Memory Harbor dashboard helper (native Cocoa, regular app)
    │ starts and owns
    ▼
harbor.py loopback server (127.0.0.1, ephemeral port)
    │ serves
    ▼
static HTML/CSS/JavaScript inside WKWebView
```

The compact owner remains alive but hides its window while the helper is open. Returning to
the desktop terminates the helper; the helper-owned server observes its parent process and
also exits. The compact owner then restores its saved desktop position and refreshes its
summary.

The helper uses an ephemeral loopback port. No fixed port is part of the interface. The
server prints its selected URL to the helper over stdout, and the helper waits for readiness
before revealing WebKit.

## Source map

| Source | Responsibility |
| --- | --- |
| `macos/CodexMemoryHarbor.swift` | compact owner window, mount/wake events, status process, helper lifecycle |
| `macos/CodexMemoryHarborDashboard.swift` | dashboard window, server ownership, WKWebView, Codex deep links |
| `skills/codex-memory-harbor/scripts/harbor.py` | scanning, catalog, recall, mutation routes, local server |
| `skills/codex-memory-harbor/assets/dashboard/index.html` | dashboard document structure |
| `skills/codex-memory-harbor/assets/dashboard/styles.css` | current dashboard presentation |
| `skills/codex-memory-harbor/assets/dashboard/app.js` | current dashboard state, rendering, and actions |
| `scripts/build_macos_app.sh` | app/helper bundles, resources, property lists, signing |
| `scripts/install_macos.sh` | canonical install, legacy retirement, installed Skill, launch behavior |

## Current compact-card contract

The native card requests `compact-status`, which returns only summary values needed for the
idle surface. It does not receive the task inventory or recall fragments. Mount, unmount,
volume rename, and wake notifications trigger bounded refreshes; there is no repeating idle
poll.

Current displayed information:

- service availability;
- safely eligible capacity;
- attached writable volume name and available capacity;
- an action that opens the isolated dashboard helper.

The card currently emphasizes reclaimable bytes. The target design changes its first
question to continuity health and required attention.

## Current dashboard transport

The server binds only to `127.0.0.1`. A per-process action token is returned by `/api/config`
and required for mutation requests. The dashboard does not read browser credentials and the
current foreground path makes no external network request.

Read routes:

- `GET /api/config`
- `GET /api/scan`
- `GET /api/volumes`
- `GET /api/storage-targets`
- `GET /api/catalog`
- `GET /api/search`
- `GET /api/recall`

Action routes:

- `POST /api/settings`
- `POST /api/protect`
- `POST /api/task-detail`
- `POST /api/task-record`
- `POST /api/rebuild-catalog`
- `POST /api/repair-links`
- `POST /api/build-recall-index`
- `POST /api/plan`
- `POST /api/offload`
- `POST /api/migrate`
- `POST /api/audit`
- `POST /api/finalize`
- `POST /api/restore`

Some POST routes are read-oriented but still require the action token. HTTP method alone is
not a safety classification; the underlying operation contract is authoritative.

## Current dashboard state

`app.js` owns one global snapshot plus selection, recommendation, pin, expansion, search,
filter, sort, and active-task state. It renders HTML strings and binds events after each
render. This was adequate for the beta but is now a shallow frontend interface: transport,
normalization, policy presentation, rendering, and operation orchestration are coupled.

The redesign should deepen the frontend around the modules named in the Frontend Foundation
without changing the backend safety contract as a side effect.

## Current lifecycle and failure behavior

- The helper hides WebKit until the local server has responded.
- Startup failure closes the empty window, reports an error, and terminates the helper.
- Unexpected server exit closes the helper rather than leaving a frozen dashboard.
- The server watches the helper PID and stops when its owner exits.
- Installation retires an exact-path orphan left by an older build.
- The main compact owner uses accessory activation and stays out of the Dock.
- The separately signed helper is the only visible Dock app while the dashboard is open.

These statements are backed by the current test suite and the dated evidence ledger. They do
not establish behavior on another Mac, another filesystem, or another Runtime Adapter.

## Current design debt

- the dashboard is Codex-specific in navigation, labels, and data assumptions;
- all jobs share a single page and one global JavaScript state object;
- style values are duplicated between Cocoa and CSS;
- visual semantics are not encoded as shared tokens;
- several controls rely on very small metadata text or text glyphs;
- responsive CSS hides columns by child position;
- frontend verification is dominated by static-string and backend-flow tests;
- no screenshot fixture covers empty, healthy, offline, permission, integrity, or partial
  failure states;
- legacy widget assets remain in the Skill tree and need an ownership decision before the
  redesign.

## Safe manual inspection

1. Open the installed `Memory Harbor.app` and confirm the compact card appears without a
   persistent helper or Python server.
2. Open the dashboard and confirm one helper owns one ephemeral loopback server.
3. Compare displayed summary counts with `harbor.py compact-status` and `harbor.py scan`.
4. Inspect healthy, empty, and offline fixture states without invoking mutation routes.
5. Use “return to desktop” and confirm both helper and server exit while the compact owner
   remains.

Real docking, release, restore, unplug, and permission-denial checks are separate acceptance
procedures. Do not use live history merely to inspect layout.
