# Roadmap

Planning document. Nothing here is built yet. Each phase lists **why now**, **concrete
steps**, **acceptance criteria** (testable — no "works well"), **depends on**, and **risks**.

All phases obey the ten swap-safety rules in `README.md`. In particular: nothing here
imports Odysseus internals, and nothing hardcodes a model name.

## Milestones at a glance

| # | Phase | Effort (rough) | Payoff |
|---|---|---|---|
| 0 | Foundations | 0.5–1 day | Makes every later phase safe and reversible |
| 1 | Voice loop you actually use | 1–3 days (browser) / 1–2 weeks (daemon) | You can talk to it hands-free |
| 2 | Memory that compounds | 2–4 days | It stops being a stranger every morning |
| 3 | Proactivity | 1–2 weeks | **The real Jarvis.** It initiates |
| 4 | Actuators | ongoing, 1 service at a time | It changes the world |
| 5 | Ambient presence | 1–2 weeks + hardware | It is *in the room*, not on a tab |
| 6 | Latency & model policy | 3–5 days | Voice stops feeling slow |
| 7 | Hardening & ops | ongoing | Survives updates, mistakes, and time |

Do 0 → 1 → 2 → 3 before touching 5. Phase 4 can run in parallel with 3, one service at a time.

---

## Phase 0 — Foundations

**Goal:** a safe, reversible base so later phases can't wreck the deployment.

**Why now:** every later phase hands a new client access to your assistant. Do the token and
upgrade discipline before, not after.

**Steps**

1. Mint a dedicated **`chat`-scoped API token** for the voice client (Settings → API tokens).
   Name it for the client, so it can be revoked alone. Never reuse the admin session.
2. Decide the always-on host: this machine, a spare box, or the phone as a stopgap
   (see `README.md` safety posture). Write the decision down here.
3. Pin the container image to an immutable tag instead of `:latest`
   (`ODYSSEUS_IMAGE=ghcr.io/odysseus-dev/odysseus:<X.Y.Z>-<sha>` in `.env`), and note the
   digest. Upgrades become deliberate.
4. Scaffold the **compatibility smoke test** from `CONTRACTS.md` and run it against the
   current install so you have a known-good baseline result to compare against.
5. Record the baseline facts (already captured in `README.md`) and re-run them after every
   upgrade.

**Acceptance criteria**

- A named binary passes: `jarvis/scripts/compat_check.sh` exits 0 against the current install, and its output is saved as a baseline artifact.
- The running container reports a pinned image tag, not `latest` (`docker inspect` shows no `:latest`).
- The voice token appears in Settings → API tokens with only the `chat` scope, and revoking it does not affect the browser session.

**Depends on:** nothing.
**Risks:** pinning means you stop receiving upstream fixes automatically — that is the point,
but you must schedule upgrades (see `CONTRACTS.md` upgrade checklist).

---

## Phase 1 — A voice loop you actually use

**Goal:** speak to it, hear an answer, without touching the keyboard — first in the browser,
then as a client daemon.

**Why now:** it is the most visible piece, and it also tells you whether you *like* talking to
it before you invest in hardware.

**Step 1a — browser-only (near-zero work, validates the idea)**

1. Set the STT and TTS providers to `browser` (`speechSynthesis` / Web Speech). Both run
   client-side, and server-side local TTS is unavailable on Python 3.14 (see `README.md`).
   Ways to set them, least friction first:
   - `POST /api/auth/settings` with an **admin** browser session — this is what the Settings UI
     itself calls. The agent's `manage_settings` tool can also change non-secret speech
     settings. Note the asymmetry: a `chat`-scoped token can *use* speech endpoints but cannot
     *configure* them, so provisioning is a one-time admin action.
   - or un-hide the UI card (next item), the only option that keeps it discoverable later.
2. **Known blocker — read-aloud is disabled in this build.** Verified in `static/index.html`:
   the TTS settings card is `<div class="admin-card" hidden style="display:none">`, and the
   "TTS Mode" overflow button is `hidden style="display:none"` as well. The markup and wiring
   JS are intact, so enabling voice output means removing those two `hidden`/`display:none`
   pairs. `static/index.html` is **upstream-owned**: keep this as a patch under
   `jarvis/patches/`, not an untracked edit you will silently lose on the next `git pull`.
3. Use the phone PWA over Tailscale as the client. Browser recording needs a secure context —
   you already have HTTPS, so this works.

**Step 1b — a real client daemon (the "Jarvis client")**

Pipeline: wake word → voice activity detection → record → transcribe → agent turn → speak,
with barge-in (talking over it stops it).

1. Choose a client language/runtime and keep **all** Odysseus knowledge inside one adapter
   module (`ARCHITECTURE.md`, rule 1).
2. Speech in: `POST /api/stt/transcribe` (server `local` or `endpoint:<id>`), or an embedded
   engine. If embedded, the adapter is still the only thing that knows the difference.
3. Agent turn: `POST /api/chat_stream` and consume SSE. Ignore unknown event types (rule 5).
4. Speech out: `POST /api/tts/synthesize` (binary or base64 JSON), or client-side synthesis.
5. Wake word: openWakeWord (open, trainable) or Porcupine (easy, licensed). Run locally
   only — never stream always-on audio to a server.
6. Barge-in: stop playback as soon as VAD detects speech; cancel the in-flight stream if the
   client supports it.

**Acceptance criteria**

- Hands-free: saying the wake word + a question produces spoken audio, with no keyboard or
  screen interaction.
- Barge-in: speaking during playback stops the audio within ~300 ms.
- Wake-word false-positive rate is low enough that you leave it enabled for a full day.
- Kill test: stopping the container mid-conversation produces a spoken or logged
  "assistant unavailable" — never a silent hang.
- The client holds **no** admin credential; only the scoped token from Phase 0.

**Depends on:** Phase 0 (token).
**Risks:** false wake words (annoying, privacy-relevant); latency (see Phase 6); microphone
permissions and secure-context requirements; a wake word that works in a quiet office may
fail across a room.

---

## Phase 2 — Memory that compounds

**Goal:** it knows you, across days and across interfaces (voice and text share the same
memory).

**Why now:** proactivity is worthless if the assistant has no idea who you are. Memory is
what turns "a chatbot" into "my assistant".

**Steps**

1. Turn on memory capture and decide the **memory policy**: what is worth remembering
   (people, preferences, ongoing projects, decisions) versus noise.
2. Define explicit trigger phrases ("remember that…", "forget…") and make sure the voice
   path reaches the same memory as text.
3. Add a **nightly consolidation scheduled task**: read the day's sessions, extract durable
   facts, write them to memory, drop duplicates. Prompt lives in a skill file so it can be
   swapped without code changes.
4. Add a small review ritual: a weekly task that lists what it decided to remember, so bad
   memories get caught early (and are cheap to fix if wrong).

**Acceptance criteria**

- Tell it something today; days later, in a *new* session, it recalls it unprompted when relevant.
- The nightly task is idempotent: running it twice does not duplicate memories (verify by count).
- A weekly review output exists that a human can act on (list of remembered items + source session).
- Deleting a memory actually removes it from retrieval results (verify by querying after delete).

**Depends on:** nothing technical (can start before Phase 1 finishes).
**Risks:** memory poisoning from untrusted content (web pages, email) — keep the policy that
external content is never auto-remembered; unbounded growth → require the consolidation task
to prune; privacy → memory is plain data under `data/`, back it up and keep it off Git.

---

## Phase 3 — Proactivity (this is the real Jarvis)

**Goal:** it starts conversations because something happened, not because you prompted.

**Why now:** highest payoff per hour of work, and it uses machinery Odysseus already has:
the task scheduler, event bus, webhooks, and ntfy.

**Steps**

1. **Briefings** — scheduled tasks, no new code:
   - Morning: calendar for the day, unread email that matters, anything due, weather.
   - Evening: what happened, what is pending tomorrow.
2. **Event-driven** — the event bus emits on chat/session/document/memory/research/email/skill
   paths:
   - Email arrives from a VIP sender → summarize → notify.
   - Research job or long background job finishes → tell you, with the result summary.
   - A document or memory changes in a way you care about → mention it once.
3. **Inbound triggers** — task webhooks (`/api/tasks/<id>/webhook/<token>`) let anything
   else in your world (a sensor, a script, a phone shortcut) fire a task with no cookies.
4. **Delivery policy** — decide and write down, per message class:
   - *silent log* (nothing you need now)
   - *push* (ntfy to the phone)
   - *speak* (only when you are present — see Phase 5)
   Plus **quiet hours** and a **daily interrupt budget** so it can't become a nag.
5. **Trust loop** — every proactive message gets a lightweight "was this useful?" reaction.
   Track it. If a class of message scores badly for two weeks, delete that task. A Jarvis you
   mute is a failure, and this is the measurement that prevents it.

**Acceptance criteria**

- At least 3 proactive messages per day arrive unprompted, each traceable to a task that
  produced it (logs/run records).
- The morning briefing runs unattended for 7 consecutive days without manual intervention.
- Quiet hours are respected: zero push/voice messages inside the window (verify against
  delivery logs).
- Feedback is recorded per message class, and at least one class is retired based on it.
- Every proactive message can be traced to its *source* (which email/job/event) — no
  unexplained assertions.

**Depends on:** Phase 0. Benefits hugely from Phase 2.
**Risks:** notification fatigue (mitigate with budgets + retirement rule); prompt injection
via email/web content driving actions (**keep proactive runs read-only** — a proactive run
must never send email, spend money, or delete anything); runaway scheduler loops (chained
tasks) — cap chain depth; cost (each proactive run is a model call — the morning briefing
should use a cheap/fast model, see Phase 6).

---

## Phase 4 — Actuators

**Goal:** it does things in the world. One service at a time, each with an explicit risk tier.

**Why now:** starts paying off as soon as Phase 3 exists ("lights on", "add to my list"),
and it is additive — one integration never blocks another.

**Steps**

1. **Home Assistant first** — it is already a preset in the integration registry. Register it
   (LAN base URL + long-lived token), then let `api_call` drive scenes, lights, sensors.
2. Write a **skill** that defines *your* vocabulary and aliases ("the office lights", "night
   mode") so the model maps words to concrete service calls.
3. Then, in this order (each a separate risk review):
   reading email/calendar → writing calendar/notes/tasks → sending email on your behalf →
   files → SSH to your own machines → anything irreversible.
4. For every actuator, declare its tier (auto / auto+log / ask) **in the config**, not in the
   prompt — prompts drift, config does not.

**Acceptance criteria**

- A spoken command changes real physical state (e.g. lights) and the assistant confirms it.
- An irreversible action (sending email) always produces an approval step — verified by
  attempting one and confirming nothing is sent without confirmation.
- Every actuator call is logged with: what was requested, what ran, what changed, and which
  tier applied.
- Turning an integration off in settings makes the assistant say it is unavailable instead of
  hallucinating success.

**Depends on:** Phase 3 (delivery/notification path), Phase 0 (tokens).
**Risks:** this is where damage is possible — an irreversible actuator with a hallucinated
target. Keep the ask-tier default for anything destructive; test with toggles and
non-critical devices first; never hand the voice path shell access.

---

## Phase 5 — Ambient presence

**Goal:** it is a thing in the room, not a tab you open.

**Why now:** only after the loop is good — otherwise you put mediocre UX in a box.

**Steps**

1. Dedicated device (Pi or mini-PC) with microphone array + speaker, running the Phase 1b
   client as a service. Same scoped token mechanism; each device is just another client.
2. Placement and audio tuning: echo cancellation, gain, and a wake-word model tuned for the
   room. This is where most of the effort actually goes.
3. Presence routing: use Home Assistant presence/room sensors to decide *which* device
   answers, and to gate "speak" versus "push" (Phase 3 delivery policy).

**Acceptance criteria**

- Trigger and get an answer across the room, over normal room noise, without raising your voice.
- With two devices online, only the room you are in responds (no double answers).
- Unplugging one device degrades gracefully — other devices keep working, no crash loops.
- A device that loses network access reconnects unattended within 60 s of the network returning.

**Depends on:** Phase 1b, ideally Phase 3 live.
**Risks:** cost and e-waste; privacy (an always-on microphone is a real decision — keep
processing local, keep a visible mute); audio quality is genuinely hard; rooms differ.

---

## Phase 6 — Latency and model policy

**Goal:** voice latency low enough to feel like a conversation, without giving up reasoning
quality — and with models swappable at any time.

**Why now:** after the features exist, speed is what makes them feel real.

**Steps**

1. Define a **model policy by job**, not by name: fast intent/briefing model, reasoning model,
   and a fallback chain. Read candidates from `/api/models` at startup; never hardcode.
2. Serve a small local model via Cookbook for wake-word-level intents and short replies;
   keep the big model for real reasoning. Measure before/after.
3. Streaming end-to-end: start speaking the first sentence as soon as it arrives rather than
   waiting for the full response.

**Acceptance criteria**

- Measured time from end-of-speech to first audible token, recorded for 20 interactions
  (median and p90), with the numbers written down before claiming improvement.
- Swapping the model endpoint or name requires **no code change** — only config — and the
  client keeps working (this is the swap-safety rule made testable).
- A model that lacks tool-calling support degrades to a text-only reply instead of an error.

**Depends on:** Phases 1 and 3.
**Risks:** local inference competes for the same GPU/CPU as the app; quality regressions when
swapping models — keep a "golden set" of 10 prompts to compare answers after any model change.

---

## Phase 7 — Hardening and operations

**Goal:** it survives updates, mistakes, and time.

**Steps**

1. **Upgrade ritual**: run the compatibility check → pin new image → re-run checks → keep the
   previous pin so rollback is one line.
2. **Backups**: `data/` contains memory, sessions, integrations and tokens. Follow
   `website/backup-restore.md`; verify a restore actually works, not just that a file appears.
3. **Audit**: log every autonomous action with tier and outcome; review weekly.
4. **Kill switch**: one action that disables all proactive tasks and all actuators at once.
5. **Secret hygiene**: tokens/keys live in `.env` and settings, never in `jarvis/` files.
6. **Watch upstream**: record when a surface in `CONTRACTS.md` changes so the adapter is
   updated deliberately.

**Acceptance criteria**

- Restore-from-backup tested end to end on a throwaway copy, with the result recorded.
- Kill switch verified: one action stops all proactive tasks and actuators, and re-enabling restores them.
- Rollback to the previous image tag verified at least once.
- A quarterly review exists (calendar task) for integrations, memories, and proactive tasks.

---

## Explicitly not yet (and why)

- **Money/purchases, industrial control, security-critical automation** — irreversible, high
  blast radius, no rollback. Revisit only with an approval gate you have tested.
- **Shell or SSH in the voice/ambient path** — RCE surface with a microphone. Approach later,
  if ever, with explicit per-action approval.
- **Always-uploading audio to a remote ASR** — privacy cost with no benefit over local.
- **Forking Odysseus core** — you would fight upstream forever for little gain. Use MCP,
  integrations, skills, and tasks.
- **Multi-user Jarvis** — every phase above assumes one trusted owner. Multi-user changes the
  threat model (see the project's `THREAT_MODEL.md`) and needs its own plan.
