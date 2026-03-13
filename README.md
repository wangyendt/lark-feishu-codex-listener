# Lark Feishu Codex Listener

Listen to Feishu/Lark group messages, and when mentioned, route the question to a local Codex agent (via `@openai/codex-sdk`) and reply in the group, mentioning the asker.

## What It Does

- Listens to messages in a target group (by group name or pinned `chat_id`)
- Only reacts when the target bot is mentioned (recommended: match by `mentions[].name`, e.g. `algo_bot_conan`)
- Adds a `Get` reaction to the original mention immediately, then removes that reaction after the reply is finished
- Replies immediately with an orange placeholder card, then updates the same card to the final green result
- If Codex creates new files/images under `codex_artifacts/<chat_id>/`, the bot uploads and sends them to the group
- Supports per-group multi-turn conversation by resuming a Codex thread (stored in `.codex_threads.json`)
- Supports switching Codex model by chat command

## Files

- `lark_codex_listener.py`: main listener
- `codex_qa.mjs`: Node helper that runs Codex SDK and returns JSON `{answer, artifacts, threadId, model}`

## Setup

1. Create `.env`:
   - Start from `.env.example`
   - Optional: set `WORKING_DIR` to run Codex against a different project directory (and store `.codex_threads.json`/`codex_artifacts/` there)
2. Python deps:
   - This script depends on `pywayne` (not vendored in this repo) and its dependencies.
3. Node deps:
   - `npm ci` (or `npm install`) to install `@openai/codex-sdk`

## Run

```bash
python lark_codex_listener.py
```

## Model Commands (in Feishu, must mention the bot)

- Show current model: `@algo_bot_conan /model`
- Start a fresh thread for this chat: `@algo_bot_conan /new`
- Set model: `@algo_bot_conan /model gpt-5-codex-mini`
- Set model and reset thread: `@algo_bot_conan /model-reset gpt-5-codex-mini`

## Notes

- Do not commit `.env` to a public repository.
- Optional env vars:
  - `LARK_CODEX_ACK_REACTION`: reaction code candidates, comma-separated, default `Get,GET,OK`
  - `LARK_CODEX_RESET_THREADS_ON_START`: if `1`, clear saved `threadId`s on startup but keep per-chat models
