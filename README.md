# Lark Feishu Codex Listener

Listen to Feishu/Lark group messages, and when mentioned, route the question to a local Codex agent (via `@openai/codex-sdk`) and reply in the group, mentioning the asker.

## What It Does

- Listens to messages in a target group (by group name or pinned `chat_id`)
- Only reacts when the bot is mentioned (default mention key in message text: `@_user_1`)
- Replies with Codex answer and `@` the asker
- If Codex creates new files/images under `codex_artifacts/<chat_id>/`, the bot uploads and sends them to the group
- Supports per-group multi-turn conversation by resuming a Codex thread (stored in `.codex_threads.json`)
- Supports switching Codex model by chat command

## Files

- `lark_codex_listener.py`: main listener
- `codex_qa.mjs`: Node helper that runs Codex SDK and returns JSON `{answer, artifacts, threadId, model}`

## Setup

1. Create `.env`:
   - Start from `.env.example`
2. Python deps:
   - This script depends on `pywayne` (not vendored in this repo) and its dependencies.
3. Node deps:
   - `npm ci` (or `npm install`) to install `@openai/codex-sdk`

## Run

```bash
python lark_codex_listener.py
```

## Model Commands (in Feishu, must mention the bot)

- Show current model: `@_user_1 /model`
- Set model: `@_user_1 /model gpt-5-codex-mini`
- Set model and reset thread: `@_user_1 /model-reset gpt-5-codex-mini`

## Notes

- Do not commit `.env` to a public repository.

