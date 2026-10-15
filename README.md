# Movies

A private watch queue for films and series: add titles, reorder and bump them, open a detail card,
swipe a row to mark it watched or archive it, keep a dated watch history and queue rewatches.
Installable as a PWA. Packaged as a Wizard OS managed app (`wizard.md`, Runtipi recipe, `/api`,
`/mcp`, `/healthz`, view at `/`).

## Run locally

```bash
CINEQUEUE_DATA=./data CINEQUEUE_BASE_PATH= python3 -m cinequeue   # http://127.0.0.1:8765/
```

## Configuration (all optional)

| Variable | Default | Meaning |
|---|---|---|
| `CINEQUEUE_DATA` | `./data` (`/data` in the image) | The only writable directory: `movies.json`, `add_requests.json`, where-to-watch cache. |
| `CINEQUEUE_WATCH_REGION` | empty in the image | Two-letter country for JustWatch availability. Empty hides the panel and makes no lookups. |
| `CINEQUEUE_TIMEZONE` | `UTC` | IANA zone for "watched today" dates. |
| `CINEQUEUE_ADMIT` | `disabled` | `live` hands "find and add" requests to the Wizard Agent Service; `stub`/`fail` are QA fakes. |
| `CINEQUEUE_WIZARD_ORIGIN` | empty | Agent Service origin, required for `live`. |
| `CINEQUEUE_AGENT_NAME` | `your Wizard` | Name shown on the request sheet when live. |
| `CINEQUEUE_ORIGINS` | empty | Extra exact browser origins allowed to write. |
| `CINEQUEUE_BASE_PATH` | `/cinequeue` (empty in the image) | Path prefix when not behind a prefix-stripping proxy. |

No third-party API keys are needed. Without agent admission the add sheet adds simple cards
directly; enriched metadata (poster, IMDb rating, cast…) is filled in by an agent through
`cinequeue_update` when the integration is enabled.

## Oscar / second Wizard setup

The stable internal app ID and MCP prefix remain `cinequeue` so updates retain existing data;
all display labels are Movies. Open the managed view through Wizard, where the central
`/wizard-os-home/core/app-client.js` resource is served. Do not copy platform code into the app.
For direct-port standalone use set `CINEQUEUE_SHARED_ORIGIN` to the reachable Wizard origin;
the app proxies only that one centrally maintained script. This defaults to the agent origin.

To enable enriched Add, set `CINEQUEUE_ADMIT=live` and `CINEQUEUE_WIZARD_ORIGIN` to the
reachable Wizard Agent Service origin. Verify `/api/config` reports `agent.ready: true`.
Register the app MCP endpoint with the owner's agent, or set `CINEQUEUE_AGENT_API_URL`
to this instance's agent-reachable HTTP origin so the run can use its OpenAPI/MCP directly.
Do not use another owner's URL. Required agent endpoints are `/wizard/hermes/api/sessions`
and `/wizard/hermes/v1/runs`; the configured origin must expose those paths. Use the
installation's network/service mapping, not a hard-coded personal hostname.

Test a real named film with year through Add; observe dispatched → processing → completed,
then read the card back. A completed request is only valid after metadata verification.
Disabled admission explicitly offers simple cards instead, never claims enrichment.
New installs seed Batman Begins (2005) once; an existing queue, including intentional `[]`,
is never reset. No owner queue, history or requests are included in the images.

## Test

```bash
python3 -m pytest -q tests            # synthetic only; browser tests need Playwright Chromium
NODE_PATH=<playwright> node qa/browser_managed.cjs http://127.0.0.1:8765/   # running container, fresh data
```

## Data and migration

State is plain JSON written atomically (temp file + rename) under an exclusive `flock` on
`<store>.lock`. Back up the data directory; the image never contains owner data.
