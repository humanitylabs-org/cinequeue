---
wizard: 0.2
id: cinequeue
name: CineQueue
type: service
category: app
version: 0.1.0
summary: Private movie and series watch queue with watch history, notes, documented API and MCP.
license: LicenseRef-Proprietary
source: .
icon: web/icon-512.png
runtime:
  kind: runtipi
  config: runtipi/config.json
  compose: runtipi/docker-compose.yml
api:
  port: 8765
  path: /api
  spec: openapi.json
mcp:
  path: /mcp
  port: 8765
  transport: streamable-http
skill: skill/SKILL.md
view:
  path: /
  port: 8765
  source:
    path: web
    build: node --check web/app.js
    dist: web
provides: [watch-queue, watch-history]
system: false
uses: []
needs: []
health: /healthz
---

# CineQueue

A private watch queue for films and series. Add titles, reorder or bump them, open a detail card,
mark them watched (history keeps every watch and its date), and queue a rewatch. A new install
starts with an empty queue that works straight away; nothing about any owner ships with the app.
Your queue, history, notes and request log live in the app's own data folder and survive updates
and reinstalls.

Optional, off unless configured at install:
- **Where to watch** (`CINEQUEUE_WATCH_REGION`, e.g. `TH` or `US`): streaming availability from
  JustWatch for that country. Unset hides the panel; no third-party lookups are made.
- **Agent requests** (`CINEQUEUE_ADMIT=live` plus `CINEQUEUE_WIZARD_ORIGIN`): "find and add" requests
  are handed to your Wizard, which resolves the exact title and fills in the card through this app's
  MCP tools. Without it, the add sheet adds simple cards directly and nothing is sent anywhere.

Private beta. The code's distribution licence needs owner approval before public listing.
