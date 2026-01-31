import json
import os
import re
import traceback
import urllib.error
import urllib.request

from aqt import gui_hooks, mw
from aqt.addons import ConfigEditor
from aqt.qt import QAction, QMenu
from aqt.utils import showInfo, showWarning

ADDON_NAME = "OpenAI Card Updater"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


def _get_config():
    config = mw.addonManager.getConfig(__name__)
    return config or {}


def _debug_enabled(config):
    return bool(config.get("debug"))


def _log_debug(config, message):
    if _debug_enabled(config):
        print(f"[{ADDON_NAME}] {message}")


def _log_error(config, message):
    print(f"[{ADDON_NAME}] ERROR: {message}")
    if _debug_enabled(config):
        traceback.print_exc()


def _get_api_key(config):
    key = (config.get("openai_api_key") or "").strip()
    if key:
        return key
    env_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if env_key:
        return env_key
    return ""


def _expand_fields(template, note, config):
    if not template:
        return ""

    def replace(match):
        field_name = match.group(1).strip()
        if field_name in note:
            return note[field_name]
        _log_debug(config, f"Prompt field not found in note: {field_name}")
        return ""

    return re.sub(r"{{(.*?)}}", replace, template)


def _ensure_json_instruction(text):
    if "json" in text.lower():
        return text
    if not text:
        return "Return output as JSON."
    return f"{text}\n\nReturn output as JSON."


def _extract_output_text(response_json):
    output_items = response_json.get("output") or []
    texts = []
    for item in output_items:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            ctype = content.get("type")
            if ctype == "output_text":
                texts.append(content.get("text") or "")
            elif ctype == "output_json":
                content_json = content.get("json")
                if content_json is not None:
                    return json.dumps(content_json)
    combined = "\n".join(t for t in texts if t).strip()
    return combined


def _call_openai(config, prompt_id, prompt_version, model, prompt_text):
    def do_request(prompt_key):
        payload = {
            "prompt": {prompt_key: prompt_id},
            "text": {"format": {"type": "json_object"}},
        }
        if prompt_version:
            payload["prompt"]["version"] = prompt_version
        if prompt_text:
            payload["input"] = prompt_text
        if model:
            payload["model"] = model

        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_get_api_key(config)}",
        }
        req = urllib.request.Request(OPENAI_RESPONSES_URL, data=data, headers=headers, method="POST")

        _log_debug(config, f"OpenAI request payload: {payload}")
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8")
            _log_debug(config, f"OpenAI response body: {body}")
            return json.loads(body)

    try:
        return do_request("prompt_id")
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")
        if err.code == 400 and "prompt_id" in body.lower():
            _log_debug(config, "Retrying with prompt.id after prompt_id error.")
            return do_request("id")
        raise


def _handle_response(editor, note_id, button_cfg, response_json, config):
    output_text = _extract_output_text(response_json)
    if not output_text:
        showWarning("OpenAI returned no text output.")
        return

    try:
        result = json.loads(output_text)
    except json.JSONDecodeError:
        _log_error(config, "Failed to parse JSON response.")
        showWarning("OpenAI response was not valid JSON.")
        return

    success = result.get("success")
    if success is not True:
        message = result.get("error") or result.get("message") or "OpenAI reported success=false."
        showWarning(message)
        return

    if editor.note is None or editor.note.id != note_id:
        showWarning("Note changed before response returned; no updates applied.")
        return

    note = editor.note
    field_map = button_cfg.get("field_map") or {}
    updated_fields = []
    missing_fields = []
    missing_keys = []

    for response_key, field_name in field_map.items():
        if response_key not in result:
            missing_keys.append(response_key)
            continue
        if field_name not in note:
            missing_fields.append(field_name)
            continue
        note[field_name] = str(result[response_key])
        updated_fields.append(field_name)

    if updated_fields:
        note.flush()
        try:
            editor.loadNote(note)
        except TypeError:
            editor.loadNote()
        showInfo(f"Updated fields: {', '.join(updated_fields)}")
    else:
        showInfo("No fields were updated.")

    if missing_keys:
        showWarning(f"Missing response keys: {', '.join(missing_keys)}")
    if missing_fields:
        showWarning(f"Missing note fields: {', '.join(missing_fields)}")


def _run_button(editor, button_cfg):
    config = _get_config()
    api_key = _get_api_key(config)
    if not api_key:
        showWarning("OpenAI API key not set. Set openai_api_key in config or OPENAI_API_KEY.")
        return

    prompt_id = (button_cfg.get("prompt_id") or "").strip()
    if not prompt_id:
        showWarning("Button is missing prompt_id.")
        return

    if editor.note is None:
        showWarning("No note is loaded in the editor.")
        return

    prompt_text = _expand_fields(button_cfg.get("prompt") or "", editor.note, config)
    prompt_text = _ensure_json_instruction(prompt_text)
    model = (button_cfg.get("model") or "").strip()
    prompt_version = (button_cfg.get("prompt_version") or "latest").strip()
    note_id = editor.note.id

    def task():
        return _call_openai(config, prompt_id, prompt_version, model, prompt_text)

    def on_done(future):
        try:
            response_json = future.result()
        except urllib.error.HTTPError as err:
            body = err.read().decode("utf-8", errors="replace")
            _log_error(config, f"HTTP error {err.code}: {body}")
            showWarning(f"OpenAI request failed (HTTP {err.code}).")
            return
        except Exception:
            _log_error(config, "OpenAI request failed.")
            showWarning("OpenAI request failed. See console for details.")
            return

        _handle_response(editor, note_id, button_cfg, response_json, config)

    mw.taskman.run_in_background(task, on_done)


def _add_editor_buttons(buttons, editor):
    config = _get_config()
    button_cfgs = config.get("buttons") or []
    for idx, button_cfg in enumerate(button_cfgs):
        label = (button_cfg.get("name") or "").strip() or "OpenAI"
        tooltip = (button_cfg.get("tooltip") or "").strip() or label
        cmd = f"openai_card_updater_{idx}"

        def handler(ed=editor, cfg=button_cfg):
            _run_button(ed, cfg)

        button = editor.addButton(
            icon=None,
            cmd=cmd,
            func=handler,
            tip=tooltip,
            label=label,
            id=cmd,
        )
        buttons.append(button)
    return buttons


def _open_config():
    conf = mw.addonManager.getConfig(__name__)
    if conf is None:
        showInfo("Add-on has no configuration.")
        return
    editor = ConfigEditor(mw, __name__, conf)
    try:
        editor.exec()
    except AttributeError:
        editor.show()


def _setup_menu():
    menu = QMenu(ADDON_NAME, mw)
    action = QAction("Configure...", mw)
    action.setToolTip("Edit add-on config. openai_api_key can be empty if OPENAI_API_KEY is set.")
    action.triggered.connect(_open_config)
    menu.addAction(action)
    mw.form.menubar.addMenu(menu)


_setup_menu()
gui_hooks.editor_did_init_buttons.append(_add_editor_buttons)
