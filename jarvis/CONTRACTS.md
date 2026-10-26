# Contracts — the Odysseus surfaces Jarvis depends on

This is the defensive document: what we rely on, how stable it is, what breaks if it changes,
and how to find out early.

**How to read the "Verified" column:**

- **live** — I executed it against this deployment on 2026-10-08.
- **spec** — documented in this checkout's `specs/`, not personally executed.

Nothing here has been wired into a client yet. This is the dependency list we commit to.

## The surfaces

| # | Surface | Auth | Purpose for Jarvis | Verified | Stability | If it changes |
|---|---|---|---|---|---|---|
| 1 | `POST /api/chat_stream` (SSE) | session or token | the conversational turn, streamed | spec | **High** — the core product surface, used by the whole web UI | Update `AgentPort` adapter; ignore unknown events |
| 2 | `POST /api/v1/chat` | `chat`-scoped token | simple synchronous turn for thin clients | spec | **Medium** — external API, newer, fewer consumers | Keep both; fall back to one |
| 3 | `POST /api/stt/transcribe` | session or token | speech → text | spec | **Medium** — touched by the hidden-settings work | Fallback: client-side STT |
| 4 | `POST /api/tts/synthesize` | session or token | text → speech (binary or base64 JSON) | spec | **Medium** | Fallback: client-side `speechSynthesis` |
| 5 | `GET /api/models` | session or `chat`-scoped token | model inventory for the model policy | spec | **Medium-High** | Model policy must fail soft to "ask the server to choose" |
| 6 | `GET /api/companion/ping` | session or token | "is auth working right now?" | live (401 unauthenticated) | **Medium** | `HealthPort` degrades to a plain chat probe |
| 7 | `GET /api/companion/info` | session or token | identity + capability flags | live (401); **name conflict observed** | **Medium-Low** — see warning below | Probe for `info` **or** `manifest`; tolerate neither |
| 8 | `GET /api/companion/models` | session or token | model endpoints, no key material | live (401) | **Medium** | Same as #5 |
| 9 | `POST /api/companion/pair` | **admin cookie** | mint a scoped token via QR | live (401 unauthenticated) | **Medium** | Human-driven only; not on the client's critical path |
| 10 | `POST /api/stt/*`, `/api/tts/*` stats | session | health/diagnostics | spec | Low — informational | Ignore failures |
| 11 | Scheduled tasks (scheduled / event / webhook triggers) | session/admin | all proactivity | spec | **Medium-High** | Proactivity is config, not code — re-create tasks |
| 12 | `POST /api/tasks/<task_id>/webhook/<token>` | **token in path, auth-exempt** | let anything fire a task | spec | **Medium** | Re-generate tokens; keep the URL out of logs |
| 13 | Outgoing webhooks (`session.created`, `chat.message`, `chat.completed`, `webhook.test`) | HMAC `X-Odysseus-Signature` | event-driven reactions | spec | **Medium** | Verify signature; treat unknown events as no-ops |
| 14 | Event bus triggers | internal | reactions to email/docs/memory/etc. | spec | **Low-Medium** — internal wiring | Prefer webhooks (stable) over internal emitters |
| 15 | `api_call` + integration registry | agent tool (admin-only) | actuators, incl. **Home Assistant** | live (no integrations registered) | **Medium-High** — a documented tool | Keep integration config in `data/integrations.json`, re-registerable |
| 16 | `/api/codex/capabilities` + scoped routes | scoped token | memory/todos/calendar/document access for external agents | spec | **Medium-Low** — scope names must stay reconciled upstream | Capability-probe before use |
| 17 | MCP servers (built-in + custom) | internal | the preferred extension seam | live (built-ins connected in logs) | **Medium-High** | Add tools via MCP, never by patching core |
| 18 | Agent memory tool | agent tool | remember/recall/forget | spec + live (memory MCP registered) | **Medium** | `MemoryPort` adapter; never write the DB directly |
| 19 | ntfy (`:8091`, bundled) | container-local | push notifications to the phone | live (200 OK) | **High** — our own container | Also support the generic webhook reminder channel |
| 20 | `/api/diagnostics/*` (logs, service health) | admin | ops visibility | spec | Medium | Best-effort; never a dependency |

## Two warnings worth writing down

**1. `info` vs `manifest` naming.** This checkout exposes `/api/companion/info`. A third-party
companion client and an upstream discussion referenced `/api/companion/manifest`. One concept,
two names. *Mitigation:* probe a list of candidate paths, accept the first that answers with a
sane shape, and degrade to "no capability info" rather than failing. This is the single best
argument for capability probing over hardcoding.

**2. Route paths vs internal module paths.** Upstream keeps *compatibility shims* for top-level
route modules (for example, the canonical `routes/task/task_routes.py` with a top-level alias).
That tells us HTTP paths are treated as stable, while **Python module paths are not** — exactly
why rule 3 in `README.md` bans importing internals. The specs also note that some agent-tool
paths (`do_manage_tokens`, `do_manage_webhooks`) do *not* have parity with their HTTP routes.
**Therefore: our clients use HTTP routes, not agent tool aliases.**

**3. Speech providers are admin-owned configuration.** Settings *writes* go through
`POST /api/auth/settings` and are admin-only; the speech *endpoints* accept a session or token.
So a voice client holding a `chat`-scoped token can use speech but can never reconfigure it.
Provisioning providers is a one-time admin step, and the client must surface "speech not
configured" as a clear message rather than trying to fix it. Related: read-aloud is disabled
in this build (see the watch list) — both the TTS settings card and the "TTS Mode" button are
`display:none` in `static/index.html`.

## Capability probes (run these by hand any time)

```bash
# Auth working? (401 = server up, token missing/bad; 200 = good)
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $ODY_TOKEN" \
     http://127.0.0.1:7000/api/companion/ping

# Identity + capability flags (try both names; one may 404)
for p in info manifest; do
  printf '%s -> ' "$p"
  curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $ODY_TOKEN" \
       "http://127.0.0.1:7000/api/companion/$p"
done

# Model inventory for this token's owner
curl -s -H "Authorization: Bearer $ODY_TOKEN" http://127.0.0.1:7000/api/models | head -c 400
```

Never paste a real token into a shell history you don't control — read it from a file or the
environment.

## Compatibility check to be built (Phase 0)

**Status: does not exist yet.** `jarvis/scripts/compat_check.sh` is the Phase 0 deliverable.
It must exit non-zero on any failed assertion so it can gate upgrades. Required assertions:

1. **Reachability**: the app answers on the local port; the container is running.
2. **Auth**: a scoped token authenticates; an unauthenticated request is rejected (proves auth
   is actually on — a regression here is a security regression).
3. **Chat**: one turn completes through `AgentPort` and yields non-empty text.
4. **Streaming**: `/api/chat_stream` emits at least one content event and terminates; unknown
   event types do not crash the parser.
5. **Speech**: if a speech provider is enabled, one tiny synthesis + one transcription round
   trip succeeds; if disabled, the client reports "unavailable" rather than erroring.
6. **Models**: the inventory is non-empty and the model policy resolves to a real endpoint.
7. **Memory**: write a sentinel memory, read it back, delete it, confirm it is gone.
8. **Notifications**: ntfy accepts a test publish (or the webhook channel returns success).
9. **Scheduler**: the expected proactive tasks exist and have a sane `next_run`.
10. **Integrations**: enabled integrations are reachable; Home Assistant answers if registered.
11. **Exposure**: the app is NOT reachable on the Wi-Fi interface (regression guard for the
    tailnet-only posture).

Assertions 2 and 11 are security regressions, not feature tests — they must never be dropped
to make a check "pass".

## Upgrade checklist

Run in this order; stop at the first failure.

1. [ ] Read upstream changes touching surfaces #1–#19 above.
2. [ ] `compat_check.sh` passes on the **current** install (establish the baseline).
3. [ ] Record the current image tag/digest as the rollback point.
4. [ ] Pin the new image tag in `.env`; `docker compose up -d`.
5. [ ] Re-run `compat_check.sh`.
6. [ ] Run the golden set of ~10 prompts; diff answers against the previous run.
7. [ ] Re-run the exposure check (tailnet-only, Wi-Fi refused).
8. [ ] Only then: keep, or roll the pin back.

## Deprecation watch list

Things most likely to move, and what to do when they do:

| Watch item | Why | Action |
|---|---|---|
| Companion capability path name | `info`/`manifest` divergence already observed | keep the probe list; never hardcode one |
| `/api/codex/*` scope names | specs say scope names must stay reconciled with `ALLOWED_SCOPES` | capability-probe; avoid depending on a single scope |
| Top-level route shims | upstream treats them as compatibility layers | keep using HTTP paths, expect shims to be removed |
| Read-aloud / speech UI | hidden in this build: the `static/index.html` settings card **and** the "TTS Mode" button both carry `hidden style="display:none"` | set providers via `POST /api/auth/settings` (admin) or the `manage_settings` tool; keep any un-hiding as a patch in `jarvis/patches/` |
| `/api/v1/chat` behavior | newer external surface | keep `chat_stream` as the primary path |
| Image tags | `:latest` moves on every push | pin; a moving tag silently changes your dependency |
| SearXNG pinned image | pinned for a reason (a bad tag broke boot) | don't "helpfully" bump it |
| Local Kokoro TTS | unsupported on Python 3.13+; container is 3.14 | design voice output around client/endpoint providers |
