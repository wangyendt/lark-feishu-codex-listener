#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Listen Feishu/Lark messages via `pywayne.lark_bot_listener.LarkBotListener`.
Print incoming messages via `pywayne.tools.wayne_print`, and echo them back.

Env vars:
- LARK_APP_ID / LARK_APPID (required)
- LARK_APP_SECRET / LARK_APPSECRET (required)
- LARK_GROUP_NAME (optional, default: 测试4)  # single group name
- LARK_VALID_GROUP_NAMES (optional, comma-separated)  # multiple group names
- LARK_CHAT_ID / LARK_GROUP_CHAT_ID (optional)  # if set, only handle messages from this chat_id
- LARK_ECHO_PREFIX (optional, default: [复述] )
- LARK_REPLY_AS_POST (optional, 0/1, default: 0)  # echo as post instead of text
- LARK_DEBUG (optional, 0/1, default: 0)
- LARK_CODEX_GROUP_NAME (optional, default: 测试4)  # only in this group, @bot triggers Codex answer
- LARK_CODEX_MENTION_KEY (optional, default: @_user_1)  # mention placeholder in text content
- LARK_CODEX_TIMEOUT_SEC (optional, default: 600)
- LARK_CODEX_MODEL_DEFAULT (optional)  # if set, used as default model for Codex SDK
- OSS_ENDPOINT (optional)
- OSS_BUCKET_NAME / OSS_BUCKETNAME (optional)
- OSS_ACCESS_KEY_ID / OSS_ACCESSKEYID (optional)
- OSS_ACCESS_KEY_SECRET / OSS_ACCESSKEYSECRET (optional)

Run:
  python scripts/lark_codex_listener.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import json
from pathlib import Path
from typing import Iterable, Optional


def _resolve_working_dir(*, default_dir: Path, dotenv_base_dir: Path) -> Path:
    """
    Resolve Codex working directory.

    - If WORKING_DIR is unset/empty: use default_dir (historical behavior).
    - If WORKING_DIR is relative: resolve it relative to dotenv_base_dir (where `.env` lives).
    - Expands `~` and environment variables.
    """
    raw = os.getenv("WORKING_DIR", "").strip()
    if not raw:
        return default_dir

    try:
        p = Path(os.path.expandvars(raw)).expanduser()
        if not p.is_absolute():
            p = (dotenv_base_dir / p).resolve()
        else:
            p = p.resolve()
        if p.is_dir():
            return p
    except Exception:
        p = None  # type: ignore[assignment]

    msg = f"[WARN] Invalid WORKING_DIR={raw!r}; falling back to {str(default_dir)!r}\n"
    try:
        sys.stderr.write(msg)
    except Exception:
        pass
    return default_dir


def _ensure_pywayne_on_sys_path() -> None:
    """
    This repo doesn't vendor the `pywayne` package. On this machine it commonly lives at:
      ../python/wayne_algorithm_lib/pywayne
    We add the containing directory (../python/wayne_algorithm_lib) into sys.path when present.
    """
    try:
        import pywayne  # noqa: F401
        return
    except Exception:
        pass

    this_file = Path(__file__).resolve()
    candidates = []
    for parent in [this_file.parent, *this_file.parents]:
        candidates.append(parent / "python" / "wayne_algorithm_lib")
        candidates.append(parent.parent / "python" / "wayne_algorithm_lib")

    for base in candidates:
        if (base / "pywayne" / "__init__.py").is_file():
            sys.path.insert(0, str(base))
            return


def load_dotenv(dotenv_path: Path, override: bool = False) -> bool:
    """
    Load `KEY=VALUE` lines into `os.environ`.

    Prefers python-dotenv's `load_dotenv` when installed; otherwise uses a tiny fallback
    parser to avoid extra dependencies.
    """
    try:
        from dotenv import load_dotenv as _load_dotenv  # type: ignore

        return bool(_load_dotenv(dotenv_path=str(dotenv_path), override=override))
    except Exception:
        pass

    if not dotenv_path.exists():
        return False

    loaded = False
    for raw in dotenv_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]

        if not override and key in os.environ:
            continue
        os.environ[key] = value
        loaded = True
    return loaded


def _env_any(names: Iterable[str]) -> Optional[str]:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return None


def _require_env_any(names: Iterable[str]) -> str:
    value = _env_any(names)
    if not value:
        raise SystemExit(f"Missing required env vars (any of): {', '.join(names)}")
    return value


def _export_canonical_env() -> None:
    """
    Map common `.env` naming variants onto canonical keys so downstream code can use one set.
    """
    app_id = _env_any(["LARK_APP_ID", "LARK_APPID"])
    if app_id:
        os.environ["LARK_APP_ID"] = app_id

    app_secret = _env_any(["LARK_APP_SECRET", "LARK_APPSECRET"])
    if app_secret:
        os.environ["LARK_APP_SECRET"] = app_secret

    bucket = _env_any(["OSS_BUCKET_NAME", "OSS_BUCKETNAME"])
    if bucket:
        os.environ["OSS_BUCKET_NAME"] = bucket

    key_id = _env_any(["OSS_ACCESS_KEY_ID", "OSS_ACCESSKEYID"])
    if key_id:
        os.environ["OSS_ACCESS_KEY_ID"] = key_id

    key_secret = _env_any(["OSS_ACCESS_KEY_SECRET", "OSS_ACCESSKEYSECRET"])
    if key_secret:
        os.environ["OSS_ACCESS_KEY_SECRET"] = key_secret


def main() -> None:
    _ensure_pywayne_on_sys_path()

    try:
        from pywayne.lark_bot_listener import LarkBotListener
        from pywayne.lark_bot import PostContent
        from pywayne.tools import wayne_print
    except Exception as e:
        raise SystemExit(
            "Failed to import pywayne modules.\n"
            "If you have pywayne in ../python/wayne_algorithm_lib, this script will auto-add it.\n"
            "Otherwise, make sure `pywayne` is importable and required deps are installed "
            "(lark-oapi, opencv-python, matplotlib, PyYAML, filelock, Pillow).\n"
            f"Import error: {e}"
        )

    script_dir = Path(__file__).resolve().parent
    # `.env` is loaded from the current working directory (where you run the script),
    # not from the script directory.
    run_dir = Path.cwd().resolve()
    dotenv_path = run_dir / ".env"
    if not dotenv_path.exists():
        # Backward-compatible fallback (non-fatal): allow running from elsewhere.
        fallback = script_dir / ".env"
        if fallback.exists():
            dotenv_path = fallback
    load_dotenv(dotenv_path, override=False)
    _export_canonical_env()

    # WORKING_DIR only affects the Codex thread's working directory.
    working_dir = _resolve_working_dir(default_dir=run_dir, dotenv_base_dir=dotenv_path.parent)

    app_id = _require_env_any(["LARK_APP_ID", "LARK_APPID"])
    app_secret = _require_env_any(["LARK_APP_SECRET", "LARK_APPSECRET"])

    # OSS env vars are also loaded/mapped into os.environ for any downstream usage
    # (not required for echo-only), e.g. `pywayne.aliyun_oss.OssManager`.

    default_group_name = os.getenv("LARK_GROUP_NAME", "测试4").strip() or "测试4"
    valid_group_names_env = os.getenv("LARK_VALID_GROUP_NAMES", "").strip()
    if valid_group_names_env:
        valid_group_names = {x.strip() for x in valid_group_names_env.split(",") if x.strip()}
    else:
        valid_group_names = {default_group_name}

    debug = (os.getenv("LARK_DEBUG", "0").strip().lower() in {"1", "true", "yes", "y"})
    echo_prefix = os.getenv("LARK_ECHO_PREFIX", "[复述] ")
    reply_as_post = (os.getenv("LARK_REPLY_AS_POST", "0").strip().lower() in {"1", "true", "yes", "y"})
    target_chat_id = _env_any(["LARK_CHAT_ID", "LARK_GROUP_CHAT_ID"])

    listener = LarkBotListener(app_id=app_id, app_secret=app_secret)

    # If unset/empty: enable Codex answering in any listened group (still requires mention key).
    codex_group_name = os.getenv("LARK_CODEX_GROUP_NAME", "").strip() or None
    codex_mention_key = os.getenv("LARK_CODEX_MENTION_KEY", "@_user_1").strip() or "@_user_1"
    codex_timeout_sec = int(os.getenv("LARK_CODEX_TIMEOUT_SEC", "600").strip() or "600")
    codex_model_default = os.getenv("LARK_CODEX_MODEL_DEFAULT", "").strip() or None
    codex_script = (script_dir / "codex_qa.mjs")
    codex_state = {"workers": {}}  # chat_id -> {"queue": asyncio.Queue, "task": asyncio.Task}
    codex_map_path = working_dir / ".codex_threads.json"

    async def _ask_codex(question: str, conv_key: str) -> dict:
        question = (question or "").strip()
        if not question:
            return {"answer": "", "artifacts": []}
        if not codex_script.exists():
            return {"answer": f"codex helper missing: {codex_script}", "artifacts": []}

        # Ensure Node resolves `@openai/codex-sdk` from scripts/node_modules.
        proc = await asyncio.create_subprocess_exec(
            "node",
            str(codex_script),
            "--key",
            str(conv_key),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(working_dir),
            env={**os.environ, **({"CODEX_MODEL_DEFAULT": codex_model_default} if codex_model_default else {})},
        )
        try:
            out_b, err_b = await asyncio.wait_for(
                proc.communicate(input=question.encode("utf-8")),
                timeout=codex_timeout_sec,
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return {"answer": f"Codex timed out after {codex_timeout_sec}s.", "artifacts": []}

        out = (out_b or b"").decode("utf-8", errors="ignore").strip()
        err = (err_b or b"").decode("utf-8", errors="ignore").strip()
        if err:
            if len(err) > 1200:
                err = err[-1200:]
            return {"answer": f"Codex error: {err}", "artifacts": []}
        if out:
            try:
                obj = json.loads(out)
                if isinstance(obj, dict) and "answer" in obj:
                    if "artifacts" not in obj or not isinstance(obj["artifacts"], list):
                        obj["artifacts"] = []
                    return obj
            except Exception:
                return {"answer": out, "artifacts": []}
        return {"answer": "Codex returned empty output.", "artifacts": []}

    def _read_codex_map() -> dict:
        try:
            if codex_map_path.exists():
                return json.loads(codex_map_path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _write_codex_map(obj: dict) -> None:
        try:
            codex_map_path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception:
            pass

    def _get_chat_model(chat_id: str) -> Optional[str]:
        obj = _read_codex_map()
        v = obj.get(chat_id)
        if isinstance(v, dict):
            model = v.get("model")
            if isinstance(model, str) and model.strip():
                return model.strip()
        return None

    def _set_chat_model(chat_id: str, model: str, *, reset_thread: bool = False) -> None:
        obj = _read_codex_map()
        v = obj.get(chat_id)
        entry = {}
        if isinstance(v, str) and v.strip():
            entry["threadId"] = v.strip()
        elif isinstance(v, dict):
            # Support both {threadId: "..."} and historical shapes.
            for k in ("threadId", "thread_id"):
                if isinstance(v.get(k), str) and v[k].strip():
                    entry["threadId"] = v[k].strip()
                    break

        entry["model"] = model
        if reset_thread and "threadId" in entry:
            del entry["threadId"]
        obj[chat_id] = entry
        _write_codex_map(obj)

    def _parse_model_cmd(question: str) -> Optional[dict]:
        q = (question or "").strip()
        if not q:
            return None

        # Query current model
        if q in {"模型", "当前模型", "model", "/model"}:
            return {"action": "show"}

        # Set model
        reset = False
        name = None
        if q.startswith("/model-reset "):
            reset = True
            name = q[len("/model-reset "):].strip()
        elif q.startswith("/model "):
            name = q[len("/model "):].strip()
        elif q.startswith("切换模型 "):
            name = q[len("切换模型 "):].strip()
        else:
            for sep in ("模型=", "模型:", "模型："):
                if q.startswith(sep):
                    name = q[len(sep):].strip()
                    break

        if name:
            if name.endswith(" reset"):
                reset = True
                name = name[:-len(" reset")].strip()
            if name:
                return {"action": "set", "model": name, "reset": reset}

        return None

    def _send_artifacts_to_chat(chat_id: str, artifacts: list):
        for art in artifacts or []:
            try:
                p = art.get("path") if isinstance(art, dict) else None
                kind = art.get("kind") if isinstance(art, dict) else None
                if not p:
                    continue
                if kind == "image":
                    image_key = listener.bot.upload_image(p)
                    if image_key:
                        listener.bot.send_image_to_chat(chat_id, image_key)
                else:
                    file_key = listener.bot.upload_file(p, file_type="stream")
                    if file_key:
                        listener.bot.send_file_to_chat(chat_id, file_key)
            except Exception:
                continue

    async def _ensure_codex_worker(chat_id: str):
        if chat_id in codex_state["workers"]:
            return

        q: asyncio.Queue = asyncio.Queue()

        def _send_codex_answer(chat_id: str, user_open_id: str, md_text: str) -> None:
            md_text = (md_text or "").strip()
            if not md_text:
                return

            post = PostContent(title="")
            # First line: @ the asker
            if user_open_id:
                post.add_contents_in_new_line([post.make_at_content(user_open_id), post.make_text_content(" ")])
            post.add_markdown(md_text, table_as="code_block", max_chunk_bytes=8_000)
            listener.bot.send_post_to_chat(chat_id, post.get_content())

        async def worker():
            while True:
                item = await q.get()
                try:
                    question, user_open_id, user_name = item
                    resp = await _ask_codex(question, conv_key=chat_id)
                    answer = (resp.get("answer") or "").strip()
                    artifacts = resp.get("artifacts") or []

                    if answer:
                        _send_codex_answer(chat_id, user_open_id, answer)
                    if artifacts:
                        wayne_print({"artifacts": artifacts}, color="yellow", verbose=1)
                        _send_artifacts_to_chat(chat_id, artifacts)
                finally:
                    q.task_done()

        codex_state["workers"][chat_id] = {"queue": q, "task": asyncio.create_task(worker())}

    @listener.listen(message_type="text")
    async def handle_text(ctx):
        chat_id = ctx.chat_id
        is_group = ctx.is_group
        user_open_id = ctx.user_id
        text = (ctx.content or "").strip()

        group_name = ""
        user_name = ""
        try:
            group_name, user_name = listener.bot.get_chat_and_user_name(chat_id, user_open_id)
        except Exception:
            pass

        if debug:
            wayne_print(
                {
                    "recv": True,
                    "text": text,
                    "chat_id": chat_id,
                    "is_group": is_group,
                    "group_name": group_name,
                    "user_name": user_name,
                    "user_open_id": user_open_id,
                },
                color="magenta",
                verbose=1,
            )

        if not is_group:
            return
        if target_chat_id and chat_id != target_chat_id:
            return
        if not target_chat_id:
            if group_name not in valid_group_names:
                return
        if not text:
            return
        if text.startswith(echo_prefix):
            return

        # Only react when the bot is mentioned.
        if codex_mention_key not in text:
            return

        codex_enabled_here = (codex_group_name is None) or (group_name == codex_group_name)

        # If user @mentions the bot, answer via Codex SDK (optionally restricted by group name).
        if codex_enabled_here:
            question = text.replace(codex_mention_key, "").strip()
            if not question:
                return

            cmd = _parse_model_cmd(question)
            if cmd:
                if cmd["action"] == "show":
                    current = _get_chat_model(chat_id) or codex_model_default or "(Codex 默认配置)"
                    listener.bot.send_text_to_chat(chat_id=chat_id, text=f"当前模型：{current}")
                    return
                if cmd["action"] == "set":
                    model = cmd["model"]
                    reset = bool(cmd.get("reset"))
                    _set_chat_model(chat_id, model, reset_thread=reset)
                    suffix = "（并已重置对话）" if reset else ""
                    listener.bot.send_text_to_chat(chat_id=chat_id, text=f"已切换模型为：{model}{suffix}")
                    return

            await _ensure_codex_worker(chat_id)
            q = codex_state["workers"][chat_id]["queue"]
            qsize = q.qsize()

            # Quick ACK so users don't think the bot missed the message.
            try:
                listener.bot.send_text_to_chat(chat_id, text="收到，处理中...")
            except Exception:
                pass

            wayne_print(
                f"[Codex] enqueued question from {group_name} - {user_name} (q={qsize}): {question}",
                color="blue",
                verbose=1,
            )
            await q.put((question, user_open_id, user_name))
            return

        wayne_print(
            f"收到消息: {text} from {group_name} - {user_name} (chat_id={chat_id})",
            color="cyan",
            verbose=1,
        )

        if reply_as_post:
            post = PostContent(title="复述")
            echo_text = text.replace(codex_mention_key, "").strip()
            post.add_content_in_new_line(post.make_text_content(f"{echo_prefix}{echo_text}"))
            listener.bot.send_post_to_chat(chat_id, post.get_content())
        else:
            echo_text = text.replace(codex_mention_key, "").strip()
            listener.bot.send_text_to_chat(chat_id=chat_id, text=f"{echo_prefix}{echo_text}")

    wayne_print(
        {
            "listening": True,
            "valid_group_names": sorted(valid_group_names),
            "echo_prefix": echo_prefix,
            "debug": debug,
            "reply_as_post": reply_as_post,
            "codex_group_name": codex_group_name or "(any listened group)",
            "codex_mention_key": codex_mention_key,
            "codex_timeout_sec": codex_timeout_sec,
            "codex_model_default": codex_model_default,
            "codex_script": str(codex_script),
        },
        color="green",
        bold=True,
    )
    listener.run()


if __name__ == "__main__":
    main()
