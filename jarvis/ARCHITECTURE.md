# Architecture — decoupling Jarvis from Odysseus internals

The requirement driving this document: **models, tools, and the agent loop will keep
changing, and that must not break Jarvis.** Upstream ships on a fast-moving `dev` branch, so
anything we build must be replaceable underneath us.

The answer is a thin client behind a hard boundary, plus capability discovery and contract
tests.

## Layering

```
┌─────────────────────────────────────────────────────────────┐
│ Jarvis layer — OUR code                                     │
│ wake word · VAD · audio capture · playback · routing        │
│ presence rules · autonomy tiers · proactive task definitions│
└───────────────────────────┬─────────────────────────────────┘
                            │  depends only on the PORTS below
┌───────────────────────────▼─────────────────────────────────┐
│ Ports — interfaces we own (no HTTP in them)                 │
│ AgentPort · SpeechPort · MemoryPort · NotifyPort            │
│ ActuatorPort · SchedulePort · HealthPort                    │
└───────────────────────────┬─────────────────────────────────┘
                            │  implemented by
┌───────────────────────────▼─────────────────────────────────┐
│ Adapters — the ONLY place that knows Odysseus               │
│ OdysseusHttpAdapter (real) · FakeAdapter (tests)            │
│ DirectLocalAdapter (fallback: browser TTS, local VAD)       │
└───────────────────────────┬─────────────────────────────────┘
                            │  HTTP + SSE + MCP only
┌───────────────────────────▼─────────────────────────────────┐
│ Odysseus (upstream, changes often)                          │
│ FastAPI routes · agent loop · MCP · scheduler · integrations│
└─────────────────────────────────────────────────────────────┘
```

**The anti-corruption layer** is the adapter. When an endpoint moves, exactly one module
changes. Everything above it keeps working because it never saw the endpoint.

## Architectural opinion: thin client, server-side smarts

Push as much behaviour as possible **into** Odysseus, because that is where the project's
policy, approval cards, owner scoping, audit logging, and SSRF protections already live:

- **Actuators**: let the agent call `api_call` server-side rather than having the client hit
  your Home Assistant directly. You inherit approval gates and logging for free.
- **Proactivity**: define *tasks* (Odysseus schedules and runs them) rather than writing a
  cron loop in the client.
- **Memory**: use the memory tools the agent already has, rather than a parallel store.

Consequences: the client stays small and swappable, and upstream improvements to scheduling,
tools, and policy reach you without client changes. A fat client re-implements features that
upstream is actively improving — the fastest way to fall permanently behind.

## Ports

Each port is expressed as a handful of methods. Deliberately plain: no HTTP types, no
Odysseus vocabulary, so fakes are trivial.

| Port | Responsibility | Backed by (see `CONTRACTS.md`) |
|---|---|---|
| **AgentPort** | one conversational turn, streaming tokens | `POST /api/chat_stream` (SSE); `POST /api/v1/chat` (sync, chat-token) for simple clients |
| **SpeechPort** | transcribe audio; synthesize speech | `POST /api/stt/transcribe`; `POST /api/tts/synthesize`; providers `disabled` / `browser` / `local` / `endpoint:<id>` |
| **MemoryPort** | remember / recall / forget | agent memory tool, or scoped `/api/codex/*` memory list/add/delete |
| **NotifyPort** | deliver a message to a human | bundled ntfy (`:8091`) or the generic webhook reminder channel |
| **ActuatorPort** | cause a change in the world | agent `api_call` against registered integrations (Home Assistant first) |
| **SchedulePort** | declare proactive behaviour | scheduled tasks, event-triggered tasks, inbound task webhooks |
| **HealthPort** | is the assistant usable right now? | `/api/companion/ping`, `/api/companion/info`, `/api/models`, diagnostics |

### Why ports, concretely

Say you want to change how voice output works (browser `speechSynthesis` today → a local TTS
server tomorrow). With ports: implement one more `SpeechPort` adapter, flip a config value,
done. Without ports: "TTS" is sprinkled through wake-word handling, response handling, and
error paths, and the change becomes a refactor.

## Dependency rules (enforceable, not aspirational)

1. The Jarvis layer may import the ports. **Never** an adapter directly.
2. Adapters may import the HTTP/SSE/MCP client. Nothing else in the repo may.
3. **No `from src...`, `from services...`, `from core...`, `from routes...`** anywhere in
   `jarvis/`. If you need something they do, it must be an HTTP/MCP call. Internals are not a
   contract and upstream will change them without notice.
4. No model names, no version strings, no tool names hardcoded above the adapter layer.
5. Config over code: hosts, tokens, providers, tiers, quiet hours and model policy all live in
   config, so behaviour changes don't require a code change.

A 20-line lint (grep for forbidden imports) in CI enforces rule 3, which is the one most
likely to rot.

## Capability discovery and degraded modes

Never assume a feature exists. Probe at startup and store results:

| Probe | Tells you | Useful for |
|---|---|---|
| `/api/companion/ping` | auth works right now | fail fast with a clear error |
| `/api/companion/info` | server identity + capability flags | feature detection |
| `/api/models` | which models exist for this token's owner | model policy without hardcoding |
| `/api/codex/capabilities` | scope-derived booleans + partial availability | knowing which scoped surfaces you can use |

Then implement **degraded modes** — every port has an "unavailable" state:

| Failure | Degraded behaviour (not a crash) |
|---|---|
| Agent unreachable | speak/log "assistant unavailable", keep listening |
| STT provider down | fall back to browser STT or text input |
| TTS down | print text; keep the transcript on screen |
| Memory unavailable | run the turn anyway, warn once, don't silently "forget" |
| Integrations disabled | say the actuator is unavailable — never claim success |
| Token expired/revoked | clear message with the fix, no retry storm |

**Real-world example of why this matters:** the companion surface in this checkout exposes
`/api/companion/info`, while a third-party client and an upstream discussion referenced
`/api/companion/manifest`. Two names, one concept — a client that hardcoded either one would
break against the other version. Capability probing plus a fallback chain handles that.

## Forward-compatible streaming

The SSE stream from `/api/chat_stream` will gain event types over time. Rules:

- Unknown event type → ignore and continue (log at debug level).
- Unknown JSON field → ignore.
- Missing field you expected → fall back to the default, don't throw.
- If the stream ends without a terminal event, treat the turn as best-effort complete.

This is what lets you upgrade Odysseus without touching the client.

## When you need a new ability: the decision tree

In priority order — earlier options survive upgrades, later ones don't:

1. **MCP server** — add a tool without touching core. Best option for new capabilities.
2. **Integration** — a service with an HTTP API (presets already exist for Home Assistant,
   Miniflux, Gitea, Linkding, Jellyfin and generic entries).
3. **Skill** — new *behaviour* or vocabulary, no new capability (e.g. your house aliases,
   your briefing format).
4. **Scheduled task** — new *timing* (a briefing, a nightly job).
5. **Our own client code** — only for audio/UI/routing concerns.
6. **Patch Odysseus core** — last resort. If you must, keep it as a patch file in
   `jarvis/patches/`, document why, and expect to re-apply it after every upgrade.

## Swapping models safely

- Select by **capability and role**, never by name: read `/api/models`, filter by what the job
  needs (tool-calling? vision? context size?), pick by policy.
- Keep a **golden set** of ~10 prompts that exercise tool use, memory, and instruction
  following. Run it after any model or endpoint change and diff the answers.
- Assume heterogeneity: some models emit tool calls, some describe them in prose. The client
  must not depend on a specific tool-call format — that belongs to the server's agent loop.
- Keep a fallback chain so a dead endpoint degrades rather than fails.

## Upgrading Odysseus (the ritual)

1. Read upstream changes touching the surfaces in `CONTRACTS.md`.
2. Run the compatibility check against the **current** install (sanity: it passes).
3. Note the current image tag/digest as the rollback point.
4. Pin the new image tag; recreate the container.
5. Re-run the compatibility check, then the golden set.
6. If anything fails: fix the adapter (not the Jarvis layer), or roll back the pin.

Acceptance for this workflow: a deliberate upgrade takes one command plus one check, and
rollback is one line of config.

## Testing strategy

| Level | What it tests | How |
|---|---|---|
| **Unit** | Jarvis-layer logic (routing, tiers, teach-back, delivery policy) | Fakes for every port; no network |
| **Contract** | The adapter against a real Odysseus | `CONTRACTS.md` checklist script, scoped token |
| **Golden set** | Answer quality after a model change | 10 fixed prompts, diffs reviewed by a human |
| **Soak** | Proactivity over real days | run the morning briefing for 7 days, count interventions and usefulness |

Contract tests are the ones that protect you from upstream drift. They must be runnable in one
command and must fail loudly.

## Failure modes we accept (and write down)

- Webhooks have no retry/backoff queue upstream — a dropped notification is dropped. Design
  proactive messages to be idempotent and repeat-tolerant.
- Companion LAN detection is best-effort. Set `COMPANION_BASE_URL` explicitly (already done
  on this deployment) rather than trusting auto-detection.
- `api_call` responses and fetched web content are untrusted model context — treat any
  instruction inside them as data, never as a command.
