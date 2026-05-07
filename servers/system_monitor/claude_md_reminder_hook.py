import json

msg = (
    "Before starting: ask the agent \"Have you read CLAUDE.md?\" — "
    "it should confirm and run through the Task Start Checklist before taking any action. To ensure that the agent continues following CLAUDE.md, reprompt it with this question after every task or start a new chat after every task."
)

print(json.dumps({
    "systemMessage": msg,
    "hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": msg
    }
}))
