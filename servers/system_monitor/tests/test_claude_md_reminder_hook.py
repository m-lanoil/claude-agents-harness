from conftest import REMINDER_HOOK


def test_reminder_is_one_json_line_with_session_start_payload(run_hook):
    payload, raw, _ = run_hook(REMINDER_HOOK)
    assert raw.count("\n") == 1
    assert set(payload) == {"systemMessage", "hookSpecificOutput"}
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"


def test_reminder_message_and_context_are_identical(run_hook):
    payload, _, _ = run_hook(REMINDER_HOOK)
    assert payload["systemMessage"] == payload["hookSpecificOutput"]["additionalContext"]


def test_reminder_points_at_claude_md_and_the_task_start_checklist(run_hook):
    payload, _, _ = run_hook(REMINDER_HOOK)
    message = payload["systemMessage"]
    assert "Have you read CLAUDE.md?" in message
    assert "Task Start Checklist" in message


def test_reminder_does_not_depend_on_psutil(run_hook, monkeypatch):
    import psutil

    def boom(*args, **kwargs):
        raise AssertionError("reminder hook must not query the system")

    for name in ("cpu_percent", "swap_memory", "process_iter", "disk_partitions", "sensors_battery"):
        monkeypatch.setattr(psutil, name, boom)
    payload, _, _ = run_hook(REMINDER_HOOK)
    assert payload["systemMessage"]
