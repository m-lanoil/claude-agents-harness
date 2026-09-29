import json

msg = (
    "Before starting: ask the agent \"Have you read CLAUDE.md?\" — "
    "it should confirm and run through the Task Start Checklist before taking any action."
)

print(json.dumps({
    "systemMessage": msg,
    "hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": msg
    }
}))
