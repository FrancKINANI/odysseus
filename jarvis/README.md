# Jarvis on Odysseus — planning docs

**Status:** planning only. Nothing in this directory is implemented, enabled, or running.
**Owner:** you. This directory is user-owned work, not part of the upstream project.

## Goal

Make Odysseus behave like a personal assistant in the Iron Man sense:

1. **You can talk to it** — hands free, natural speech in and out.
2. **It initiates** — it speaks up because something happened, not because you asked.
3. **It acts** — lights, calendar, email, files, your other machines.

Today Odysseus is excellent at "you type, it does". Jarvis is mostly about the other two
directions: **in (voice)** and **out (initiative)**.

## The three pillars

| Pillar | What it means | Where Odysseus stands today |
|---|---|---|
| **Voice interface** | Wake word, speech in, speech out, barge-in | Services exist (`/api/stt/*`, `/api/tts/*`) but voice is push-to-talk in the browser. **No wake word, no always-on listening anywhere in the codebase.** |
| **Proactivity** | It starts the conversation | Strong foundation: task scheduler (scheduled / webhook / event-triggered), event bus, email pollers, note reminders, ntfy push. Barely used in practice. |
| **Autonomy** | It changes the world | `api_call` + integration presets (**Home Assistant is a first-class preset**), shell/python/file tools, SSH to other hosts. **Zero integrations are currently registered.** |

Build them in that order, but note the trap: **the wake word is the least valuable part.**
Most people build a slick microphone first and end up with a slower chatbot. What makes it
feel like Jarvis is *proactivity plus memory that compounds*. Voice is the interface; the
agent is the substance.

## The core requirement: swappable parts

The agent architecture underneath (models, tools, agent loop, MCP, memory) is improving
fast — upstream is on a fast-moving `dev` branch. This plan must survive those changes.

Ten rules that make that possible:

1. **One boundary.** Only the client adapter knows Odysseus HTTP details. Everything else
   talks to our own interfaces. If an endpoint changes, you patch one file.
2. **No Python imports of Odysseus internals.** No `from src...`, no `from services...`.
   HTTP, SSE, and MCP only. Internals are not a contract; HTTP surfaces are.
3. **Discover, don't assume.** Probe capabilities at startup and adapt. Assume nothing
   about which tools, models, or features exist.
4. **Never hardcode model names.** Select by capability from `/api/models`. Models get
   added, renamed, and retired constantly.
5. **Parse forward-compatibly.** Unknown SSE event types, unknown JSON keys, and unknown
   capability flags are ignored, never fatal.
6. **Extend before you patch** (in order): MCP server → integration → skill → scheduled
   task → core patch. Core patches are last because upstream will move under you. See
   `ARCHITECTURE.md`.
7. **Pin the image.** Roughly `ghcr.io/odysseus-dev/odysseus:<version>-<sha>`, not
   `:latest`. Upgrades become a decision instead of an accident.
8. **Contract tests gate every upgrade.** Run `CONTRACTS.md`'s checklist before and after.
9. **Degrade, don't die.** Every port has an "unavailable" state and a fallback. Voice
   down? Fall back to text. Notifications down? Log to a file.
10. **Least privilege.** A dedicated `chat`-scoped token per client. Never an admin
    cookie, never the admin password, never a shell-equivalent scope you don't need.

## Current baseline (verified 2026-10-08)

Facts measured on this actual deployment, not assumed:

| Thing | State |
|---|---|
| Containers | odysseus, chromadb, searxng, ntfy — running via `docker compose up -d` |
| Exposure | loopback + Tailscale only. `https://julie.tail4f5d9d.ts.net` via `tailscale serve`; Wi-Fi refused |
| Mobile | working on the phone (Tailscale + PWA over HTTPS) |
| Docker at boot | **disabled** — daemon starts on demand, so containers need a manual `docker compose up -d` after reboot |
| Voice dependencies | **none installed**: no `faster_whisper`, `kokoro`, `soundfile`, `torch`, and no wake-word or VAD library anywhere in the codebase |
| Read-aloud (TTS) in the UI | **disabled in this build** — both the TTS settings card and the "TTS Mode" button carry `hidden style="display:none"` in `static/index.html` (an upstream-owned file) |
| Speech configuration | admin-only writes (`POST /api/auth/settings`); a `chat`-scoped token can use speech but not configure it |
| Container Python | **3.14.8** → upstream skips local Kokoro TTS on 3.13+, so *server-side local TTS is not an option here* |
| Integrations | **none registered** (no `data/integrations.json`) |
| Upstream checkout | `origin = github.com/odysseus-dev/odysseus`, branch `dev`, HEAD `2992bf6d` (2026-10-01) |
| Image tag in use | `:latest` — moves on every upstream push |

Two consequences that shape the plan:

- **Voice output must be client-side or an endpoint provider.** `browser` TTS works today
  (client `speechSynthesis`); `endpoint:<id>` needs an OpenAI-compatible `/audio/speech`
  somewhere. Do not design around in-container Kokoro.
- **Voice input** can start with `browser` STT (zero install). Local `faster-whisper` is an
  optional dependency and would need installing; CPU-only in this container.

Also note: upstream's own roadmap is aimed elsewhere (bug squashing, Cookbook reliability,
email performance, agent prompt bloat). Core features you want are unlikely to arrive from
upstream soon, and their fixes may change internals you were relying on. That is exactly
why rules 1–3 exist.

## Documents

| File | Read it for |
|---|---|
| `ROADMAP.md` | The staged plan: phases, concrete tasks, acceptance criteria, effort, risks |
| `ARCHITECTURE.md` | The decoupling design — ports and adapters, capability probing, upgrade workflow |
| `CONTRACTS.md` | The exact Odysseus surfaces we depend on, how stable each is, and what to do when it changes |

Suggested reading order: this file → `ROADMAP.md` → `ARCHITECTURE.md` → `CONTRACTS.md`.

Two paths referenced in these docs **do not exist yet** — they arrive with Phase 0, and are
listed here only so the intent is clear before anyone goes looking for them:

- `scripts/` — will hold the compatibility check (`CONTRACTS.md`, Phase 0 deliverable).
- `patches/` — will hold patches against upstream-owned files that must be re-applied after an
  upgrade (the read-aloud un-hiding in `ROADMAP.md` Phase 1 is the first candidate).

## Safety posture (non-negotiable)

Odysseus is an admin console: shell, files, email, model serving. The project's own
`THREAT_MODEL.md` says treat it as trusted-users-on-a-private-network only. An always-on
agent with a microphone, wired to a shell, on your main machine, is a remote-code-execution
surface with a voice front-end. Therefore:

- A **separate scoped token per client**, revocable from Settings → API tokens.
- **No shell tools in the voice/ambient path.** Voice drives chat, memory, notifications,
  and registered integrations — not `bash`.
- **Autonomy tiers**: read-only = automatic; reversible = automatic with a log; irreversible
  (sending email, spending money, deleting) = always ask. Odysseus already has an
  exact-action approval model for untrusted context — mirror that idea in our own tiering.
- **Keep exposure tailnet-only.** Never port-forward this.
- A dedicated always-on box (Pi/mini-PC) is preferred over your daily driver for anything
  that runs unattended.

## Git hygiene

This checkout tracks upstream, so `git pull` will regularly rewrite files. Rules:

- `jarvis/` is ours. Upstream has no such directory, so it never collides — but do **not**
  push it to `origin`.
- Keep this work on a **`jarvis` branch**, or better, its own repository, so upstream
  updates and your work never fight.
- Never add our files to a path upstream owns (`src/`, `routes/`, `services/`, `static/`,
  `specs/`, `website/`), except as a deliberate, documented patch you re-apply on upgrade.
