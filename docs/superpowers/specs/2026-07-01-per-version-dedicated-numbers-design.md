# Per-Version Dedicated Numbers (Workshop Shared Mode) — Design

**Date:** 2026-07-01
**Branch:** feat/workshop-robustness-search-annotated-code (uncommitted, git HELD)

## Problem

In workshop (shared-credentials) mode the guided path has four versions of Buddy
(`/hello`, `/tool`, `/skills`, `/complete`) but only **one** SWML webhook
resource (`HANDLER_NAME`) and one phone number. Selecting a version rewrites that
resource's `primary_request_url`, so when several attendees pick different
versions they clobber each other's number, and it is impossible to tell which
number reaches which version.

## Goal

Give each guided version its **own** dedicated SWML resource and its **own**
dedicated phone number, so all four are simultaneously dialable and every
attendee gets a consistent, non-overlapping experience. Surface the
version to number mapping clearly in the UI.

## Account facts (workshop space, verified 2026-07-01)

- 38 numbers total; 19 free (no `calling_handler_resource_id`, no
  `call_relay_script_url`), all in the 520-436 pool.
- A phone-number object exposes `calling_handler_resource_id` and
  `call_relay_script_url`; a number is FREE when both are empty.
- Dedicated numbers chosen (grouped, easy to read on the floor):
  - V1 Hello → +15204363368
  - V2 Tools → +15204363380
  - V3 Skills → +15204363383
  - V4 Complete → +15204363397

## Approach

The legacy single-`HANDLER_NAME` resource path (used by the solo-mode wizard and
the browser call) is left UNCHANGED. Per-version provisioning creates four
SEPARATE resources named per route, so nothing about the existing flow breaks.

### Backend (`python/steps/step12_rest_demo.py`)

- `GUIDED_AGENTS`: ordered list of `{route, version, title, resource_name}` for
  the four guided versions. `resource_name = f"{HANDLER_NAME} - {slug}"`.
- `number_is_free(n)`: `not n.get("calling_handler_resource_id") and not n.get("call_relay_script_url")`.
- `_find_swml_webhook(client, name=HANDLER_NAME)`: gains a `name` param so it can
  locate any per-route resource (default keeps legacy behavior).
- `provision_guided_agents(public_base, creds=None, client=None, sid=None)`:
  idempotent. For each guided agent, ensure its per-route resource exists and is
  pinned to its route; if the resource has no number yet, assign the next FREE
  number, then set that number's friendly name to `Buddy V{n} - {Title}`.
  Returns `[{route, version, title, e164, resource_id}]`.
- `guided_number_map(creds=None, client=None)`: read-only. For each guided
  agent, find its resource and the number currently routed to it. Returns the
  same shape (e164 may be null if unprovisioned). Drives the UI without
  re-provisioning on every boot.

### API (`main.py`)

- `GET /api/agent/numbers` → `{shared: bool, agents: [{route, version, title, e164}]}`.
  Reads via `guided_number_map`; cached in-process. Only meaningful in shared
  mode; returns `agents: []` off shared mode.
- `POST /api/admin/provision-agents` (admin basic-auth) → runs
  `provision_guided_agents` on demand and returns the mapping. Idempotent.

### UI (`web/index.html`)

- On load in shared mode, fetch `/api/agent/numbers`.
- Each guided version's section shows a prominent "Call this number to reach
  Version N" badge with its dedicated number (replacing the shared-number
  wizard framing in shared mode).
- The four-node overview gains the number under each node label.

## Out of scope

- Per-attendee session scoping of post-prompt data (tracked separately in the
  multitenancy plan). This change is only about stable per-version inbound
  numbers.

## Verification

- Unit tests for `number_is_free`, provisioning idempotency (mocked client),
  and `guided_number_map`.
- Live: run provisioning against the workshop account, confirm four numbers
  routed + named, `GET /api/agent/numbers` returns all four, Chrome shows the
  mapping.
