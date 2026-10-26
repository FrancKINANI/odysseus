# Security updates — 2026-10-22

Hardening of the unattended shell actions, plus removal of an unused,
unsandboxed shell facade.

## 1. Shell actions are now allowlisted

`run_local`, `run_script`, and `ssh_command` execute arbitrary strings with
`shell=True` / `bash -c` and are reachable from scheduled tasks. They were
protected only by the admin gate on task creation, which is not enough for a
cron job that runs unattended.

- New env var: **`ODYSSEUS_SHELL_ALLOWLIST`** — comma-separated regular
  expressions matched against the **entire** command with `re.fullmatch`.
- **Default deny**: unset or empty means all three actions refuse to run.
- Invalid entries are logged and skipped, so a typo fails closed.
- Enforcement lives in `src/builtin_actions.py`
  (`_shell_allowlist_patterns`, `shell_action_denied_reason`) and runs before
  any subprocess is created, including before the SSH branch.
- A denied call returns `("Blocked: …", False)`.

Example:

```bash
ODYSSEUS_SHELL_ALLOWLIST='git status( .*)?,git pull --ff-only,ls( .*)?,df -h'
```

The variable is forwarded to the container by `docker-compose.yml` and both GPU
overrides, and documented in `.env.example` (compose only passes variables it
explicitly lists). Restart the app after changing it. Keep the list narrow: a
regex such as `.*` restores the previous unrestricted behaviour.

## 2. `ShellService` removed

`services/shell/service.py` exposed `ShellService.execute()` /
`ShellService.stream()`: `asyncio.create_subprocess_shell` on an arbitrary
command, `cwd` defaulting to `$HOME`, no allowlist, no sandbox, and a docstring
claiming “safe command execution”. It had no callers outside its own module,
the `services` package re-export, and one test.

Removed:

- `services/shell/service.py`, `services/shell/__init__.py`
- `tests/test_shell_service.py`
- the `ShellService` / `ShellResult` re-export in `services/__init__.py`

`specs/shell-mcp.md` was updated to record the removal and to document the
allowlist under “Security And Provenance”.

## Verification

```text
python -m pytest tests/test_shell_action_allowlist.py \
                  tests/test_builtin_actions_nonstring.py \
                  tests/test_builtin_actions_owner_scope.py
-> 12 passed
```

New tests (`tests/test_shell_action_allowlist.py`) cover: default deny, allowed
match, non-matching command, SSH denial before any subprocess, and invalid
regex failing closed.

## Deployment (2026-10-22)

The local image was rebuilt (`docker compose build`, tag
`ghcr.io/odysseus-dev/odysseus:latest`) and the stack started with
`docker compose up -d`: `odysseus`, `chromadb`, `searxng`, `ntfy`. The app
answers `302` on `http://127.0.0.1:7000` (login), and `ODYSSEUS_SHELL_ALLOWLIST`
is present but empty, so the shell actions are denied until an allowlist is set.

## Still worth doing

- `routes/shell_routes.py` (`/api/shell/exec`, `/api/shell/stream`) remains
  admin-only with a cross-site check, but `_require_admin()` is a no-op when no
  auth manager exists. Keep `APP_BIND=127.0.0.1` or set `AUTH_ENABLED=true`
  before exposing the app.
- The allowlist governs the task actions only; the interactive agent `bash`
  tool has its own admin/approval path and is unchanged.
