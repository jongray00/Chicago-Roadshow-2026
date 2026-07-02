# SignalWire Agents SDK Workshop

A self-guided, browser-first workshop app for building AI voice agents with the
[SignalWire Agents SDK](https://github.com/signalwire/signalwire-agents). Attendees
log in with their own SignalWire credentials, connect a phone number in three
clicks, and talk to **Buddy**, an AI agent they then rebuild step by step, from
"hello" to a production-shaped agent with tools, skills, a governed state machine,
and full call observability.

> **Duration:** ~60 minutes | **Level:** Beginner | **Runs on:** Replit (or any host with a public URL)

## What attendees experience

1. **Credentials.** Paste a SignalWire Project ID, API token, and space into the
   landing page. Each browser session keeps its own credentials; nothing is shared
   between attendees on a common deployment.
2. **Phone number.** The wizard lists numbers already on the project (or searches
   and buys one) and points the chosen number at the workshop agent through a
   Call Fabric SWML webhook resource. No dashboard digging required.
3. **Call it.** Dial the number from a real phone, or click to call from the
   browser. Browser calls are video calls: Buddy renders as an animated robot
   avatar, and a **Live Wire** panel streams the call's real-time AI events
   (speech detection, function calls, step changes) next to the video.

After the first call, the page unlocks the learning path: seven versions of Buddy,
each adding one capability, with source views in Python and TypeScript, suggested
phrases to try, and links into the SignalWire docs.

## The learning path

Every version runs simultaneously on its own route. Re-point your number (one
click in the wizard) to hear the difference between versions.

> The `/stepNN` route and `stepNN_*.py` file names are historical (some
> versions were merged during development), so they skip numbers; the
> The **guided path is four versions** that build on each other. Each version's
> route is a semantic slug (`/hello`, `/tool`, `/skills`, `/complete`) that
> matches its version number, so the SWML URL you see always agrees with the
> label. Three older agents stay live for reference but are **archived** — the
> guided UI never lists them.

| Route | Version | What it adds |
|-------|---------|--------------|
| `/hello` | Version 1 — Hello Buddy | The smallest possible agent: a voice, a personality prompt, a post-prompt summary |
| `/tool` | Version 2 — Buddy Gets a Tool | A SWAIG function with parameters: live weather for any city via Open-Meteo, and jokes on demand |
| `/skills` | Version 3 — Buddy Gets Skills | Built-in skills: date/time and math in one line each |
| `/complete` | Version 4 — Complete Buddy | Production shape: see below |
| `/step06` | Archived — Hardcoded Jokes | First SWAIG function (`define_tool`): the AI decides when to call your code |
| `/step07` | Archived — Live API Jokes | The same function backed by a real external API (icanhazdadjoke.com) |
| `/step09` | Archived — Polished Agent | Personality, speech hints, fillers, and timeout tuning |

All weather lookups run as server-side SWAIG tools (keyless Open-Meteo, no
prerequisites). DataMap, the serverless alternative, is explained in the `/tool`
source for comparison.

### The final agent (Version 4, `/complete`)

The complete agent demonstrates what the SDK recommends for real deployments:

- **A contexts/steps state machine** in the shape the
  [SDK contexts guide](https://github.com/signalwire/signalwire-agents/blob/main/docs/contexts_guide.md)
  recommends: six meaningful steps (`greeting`, `weather`, `joke`, `time`, `math`,
  `wrap_up`). Each topic step exposes only its own tool, and every topic connects
  directly to every other topic, so callers move freely instead of being routed
  through menus. This is System-Directed AI: the platform enforces which tools and
  transitions exist at each step.
- **Four capabilities, three integration styles:** a custom SWAIG function
  (jokes), a parameterized server-side tool (weather), and two built-in skills
  (datetime, math).
- **Call recording** (stereo WAV via `record_call`) and a **structured post-prompt**
  that returns JSON (summary, topics handled, decisions, outcome) after every call.
- **Video avatar and vision** parameters for browser calls, ignored gracefully on
  audio-only phone calls.
- Clean `_configure_*()` / `_register_*()` method organization.

## Observability: the admin dashboard

Open `/admin` to see every call the room makes, live:

- **Post-prompt viewer:** transcript, AI-generated summary, structured JSON, and
  call metadata for each call, updating over a live stream as calls end.
- **State Flow:** the agent's step graph (every step and allowed transition)
  overlaid with the path the caller actually took, built from the platform's
  `step_change` events.
- **Timeline and charts:** per-call event timelines and room-wide metrics.
- **Recordings:** stereo WAV playback per call.
- **SWAIG health:** every registered function across all agents, with one-click
  live test runs (`/admin/swaig`).
- **Errors and exports:** recent failures and a JSON export of captured calls.

The post-prompt pipeline is the teaching backbone: agents opt in to
`swaig_post_conversation` and `swaig_post_swml_vars`, the platform POSTs the full
call log after each call, and the server correlates it to the attendee's session.

## REST and RELAY demos

Two Run-button demos on the landing page round out the platform tour:

- **REST** (`python/steps/step12_rest_demo.py`): provision the agent as a dialable
  Call Fabric resource and mint a short-lived guest token with the REST API.
- **RELAY:** the click-to-call widget itself. The browser fetches a guest token,
  loads `@signalwire/js`, and dials the agent's Call Fabric address, video included.

## Quick start

### On Replit (recommended)

1. Fork the repl (or deploy this repo on a **Reserved VM**, see below).
2. Click **Run**. The public URL is detected automatically and all agents start.
3. Open the page and follow the three-step wizard. Credentials are entered in the
   browser, so no secrets are required to host the app.

Optional server secrets:

| Secret | Purpose |
|--------|---------|
| `SIGNALWIRE_PROJECT_ID` / `SIGNALWIRE_TOKEN` / `SIGNALWIRE_SPACE` | Auto-fill your own credentials for solo testing. Do NOT set these on a shared deployment. |
| `SWML_BASIC_AUTH_USER` / `SWML_BASIC_AUTH_PASSWORD` | Override the basic auth embedded in SWML webhook URLs (defaults: `workshop` / `password`). |
| `ADMIN_USER` / `ADMIN_PASSWORD` | HTTP Basic auth for the `/admin` dashboard (it exposes every attendee's call data). Defaults: `admin` / the SWML password above. **Set `ADMIN_PASSWORD` to a strong secret on any shared deployment.** Set it to an empty string to disable the gate (trusted/local only). |
| `WORKSHOP_SHARED_ACCOUNT` | Shared workshop-account mode: the build runs on the shared account with no credential screen, and attendees connect their own account only for the outbound finale and number verification (never the shared token). **This is the DEFAULT whenever the `SIGNALWIRE_*` creds are present** — the workshop always defaults to the workshop account. Set to `0` (or `false`/`no`/`off`) to force the per-attendee "bring-your-own-from-the-start" model instead. With no `SIGNALWIRE_*` creds present it is inactive regardless. The number wizard (`/api/setup/search|select|route`) is disabled in shared mode; attendees never buy or re-route numbers on the shared account. |

### Locally

SignalWire must be able to reach the server, so a public URL is required even in
development. Set it **before** starting: agents bake their webhook URLs at
construction time.

```bash
pip install -e .                       # or: uv sync
cloudflared tunnel --url http://localhost:5050   # note the public URL it prints
PORT=5050 SWML_PROXY_URL_BASE=https://<your-tunnel-url> python main.py
```

Without `SWML_PROXY_URL_BASE` the app falls back to its deployed Replit URL and
calls will reach that deployment instead of your machine.

### Hosting one URL for a whole room (multi-tenant)

Each attendee's credentials, number, and agent handler are scoped to a per-browser
session (httpOnly `sw_session` cookie) and persisted across restarts. API tokens
stay on the server and are stripped from anything published or snapshotted. Two
deployment rules:

- **Reserved VM, not Autoscale.** Sessions live in one server process; multiple
  stateless instances would split them.
- **No `SIGNALWIRE_*` secrets on the deployment.** Those are per-attendee and
  entered in the browser.

## Project layout

```
main.py                  Server: agent registration, wizard + admin APIs, SSE streams
python/steps/            The seven agent versions plus shared helpers
  _weather.py            Keyless Open-Meteo SWAIG tool shared by steps 8-11
  _postprompt_params.py  Post-prompt capture flags shared by every agent
  step12_rest_demo.py    REST provisioning + guest tokens (also powers click-to-call)
typescript/steps/        Reference-only TypeScript siblings of each step
web/                     Landing page, admin dashboard, Live Wire, charts, timeline
call_store.py            Post-prompt normalization, transcripts, state-flow extraction
session_store.py         Per-browser session isolation (tokens never persisted)
live_events.py           Real-time AI event bus behind the Live Wire panel
function_health.py       SWAIG function registry + live test runner
tests/                   pytest suite covering agents, stores, routes, and UI data
```

## Tests

```bash
python -m pytest -q
```

The suite covers the agents' rendered SWML (step graphs, tool scoping, recording,
post-prompt contracts), the wizard and admin routes, session isolation, and the
post-prompt pipeline.

## More demos to build from

This workshop is part of the [SignalWire Demos](https://github.com/signalwire-demos)
collection. Standouts to explore next, each with a live deployment:
[Santa](https://santa.signalwire.io), [Blackjack](https://blackjack.signalwire.io),
[Cinebot](https://cinebot.signalwire.io), [Bobby's Table](https://bobbystable.signalwire.io),
[Holy Guacamole](https://holyguacamole.signalwire.io), [Cabby](https://cabby.signalwire.io),
and the [Example Agent](https://example.signalwire.io) starter template.
