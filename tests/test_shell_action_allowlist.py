import asyncio

from src import builtin_actions


def _run(coro):
    return asyncio.run(coro)


def test_shell_actions_denied_without_allowlist(monkeypatch):
    monkeypatch.delenv(builtin_actions.SHELL_ALLOWLIST_ENV, raising=False)

    output, ok = _run(builtin_actions.action_run_local("owner", script="ls -la"))

    assert ok is False
    assert "disabled" in output


def test_shell_action_allowed_by_matching_regex(monkeypatch):
    monkeypatch.setenv(builtin_actions.SHELL_ALLOWLIST_ENV, r"ls( .*)?")
    calls = {}

    async def fake_run(argv, **kwargs):
        calls["argv"] = argv
        return "ok", True

    monkeypatch.setattr(builtin_actions, "_run_subprocess", fake_run)

    output, ok = _run(builtin_actions.action_run_local("owner", script="ls -la"))

    assert (output, ok) == ("ok", True)
    assert calls["argv"] == "ls -la"


def test_shell_action_denied_when_command_does_not_match(monkeypatch):
    monkeypatch.setenv(builtin_actions.SHELL_ALLOWLIST_ENV, r"ls( .*)?")

    output, ok = _run(builtin_actions.action_run_local("owner", script="rm -rf /"))

    assert ok is False
    assert "not allowed" in output


def test_ssh_command_denied_before_any_subprocess(monkeypatch):
    monkeypatch.delenv(builtin_actions.SHELL_ALLOWLIST_ENV, raising=False)

    async def must_not_run(*args, **kwargs):
        raise AssertionError("_run_subprocess must not run for a denied command")

    monkeypatch.setattr(builtin_actions, "_run_subprocess", must_not_run)

    output, ok = _run(
        builtin_actions.action_ssh_command("owner", command="id", host="example.com")
    )

    assert ok is False
    assert "Blocked" in output


def test_invalid_allowlist_entry_fails_closed(monkeypatch):
    monkeypatch.setenv(builtin_actions.SHELL_ALLOWLIST_ENV, "([")

    output, ok = _run(builtin_actions.action_run_local("owner", script="ls"))

    assert ok is False
    assert "disabled" in output
