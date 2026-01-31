import json
import os
import re
import threading
import traceback
import urllib.error
import urllib.request

from aqt import gui_hooks, mw
from aqt.addons import ConfigEditor
from aqt.qt import QAction, QMenu, QProgressDialog, Qt
from aqt.utils import showWarning, tooltip

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
    key = (config.get("openai_anki_api_key") or "").strip()
    if key:
        return key
    key = (config.get("openai_api_key") or "").strip()
    if key:
        return key
    env_key = (os.environ.get("OPENAI_ANKI_API_KEY") or "").strip()
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
    payload = {
        "prompt": {"id": prompt_id},
        "text": {"format": {"type": "json_object"}},
    }
    if prompt_version and prompt_version.lower() != "latest":
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

    def after_save():
        try:
            editor.loadNote(note)
        except TypeError:
            editor.loadNote()
        tooltip(f"Updated fields: {', '.join(updated_fields)}", period=3000)
        if missing_keys:
            showWarning(f"Missing response keys: {', '.join(missing_keys)}")
        if missing_fields:
            showWarning(f"Missing note fields: {', '.join(missing_fields)}")

    if updated_fields:
        if note.id:
            note.flush()
            after_save()
        else:
            try:
                editor.saveNow(after_save, True)
            except TypeError:
                try:
                    editor.saveNow(after_save)
                except TypeError:
                    editor.saveNow(True, after_save)
    else:
        tooltip("No fields were updated.", period=3000)
        if missing_keys:
            showWarning(f"Missing response keys: {', '.join(missing_keys)}")
        if missing_fields:
            showWarning(f"Missing note fields: {', '.join(missing_fields)}")


def _run_button(editor, button_cfg):
    config = _get_config()
    api_key = _get_api_key(config)
    if not api_key:
        showWarning("OpenAI API key not set. Set openai_anki_api_key in config or OPENAI_ANKI_API_KEY.")
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
        mw.progress.finish()
        try:
            response_json = future.result()
        except urllib.error.HTTPError as err:
            body = err.read().decode("utf-8", errors="replace")
            _log_error(config, f"HTTP error {err.code}: {body}")
            if _debug_enabled(config):
                showWarning(f"OpenAI request failed (HTTP {err.code}).\n{body}")
            else:
                showWarning(f"OpenAI request failed (HTTP {err.code}).")
            return
        except Exception:
            _log_error(config, "OpenAI request failed.")
            showWarning("OpenAI request failed. See console for details.")
            return

        _handle_response(editor, note_id, button_cfg, response_json, config)

    mw.progress.start(label="OpenAI update in progress…", immediate=True)
    mw.taskman.run_in_background(task, on_done)


def _run_button_bulk(browser, button_cfg):
    config = _get_config()
    api_key = _get_api_key(config)
    if not api_key:
        showWarning("OpenAI API key not set. Set openai_anki_api_key in config or OPENAI_ANKI_API_KEY.")
        return

    prompt_id = (button_cfg.get("prompt_id") or "").strip()
    if not prompt_id:
        showWarning("Button is missing prompt_id.")
        return

    note_ids = browser.selectedNotes()
    if not note_ids:
        tooltip("No notes selected.", period=3000)
        return

    field_map = button_cfg.get("field_map") or {}
    total = len(note_ids)
    cancel_event = threading.Event()
    progress_dialog = QProgressDialog("OpenAI bulk update…", "Cancel", 0, total, browser)
    progress_dialog.setWindowTitle(ADDON_NAME)
    progress_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    progress_dialog.setAutoClose(False)
    progress_dialog.setAutoReset(False)
    progress_dialog.canceled.connect(cancel_event.set)
    progress_dialog.show()

    def task():
        result = {
            "updated": 0,
            "skipped": 0,
            "failed": 0,
            "cancelled": False,
        }
        for idx, note_id in enumerate(note_ids, start=1):
            if cancel_event.is_set():
                result["cancelled"] = True
                break

            note = mw.col.get_note(note_id)

            if not field_map:
                result["skipped"] += 1
                continue

            missing_fields = [f for f in field_map.values() if f not in note]
            if missing_fields:
                _log_debug(config, f"Skipping note {note_id}: missing fields {missing_fields}")
                result["skipped"] += 1
                continue

            prompt_text = _expand_fields(button_cfg.get("prompt") or "", note, config)
            prompt_text = _ensure_json_instruction(prompt_text)
            model = (button_cfg.get("model") or "").strip()
            prompt_version = (button_cfg.get("prompt_version") or "latest").strip()

            try:
                response_json = _call_openai(config, prompt_id, prompt_version, model, prompt_text)
            except urllib.error.HTTPError as err:
                body = err.read().decode("utf-8", errors="replace")
                _log_error(config, f"OpenAI request failed for note {note_id} (HTTP {err.code}): {body}")
                result["failed"] += 1
                continue
            except Exception:
                _log_error(config, f"OpenAI request failed for note {note_id}.")
                result["failed"] += 1
                continue

            output_text = _extract_output_text(response_json)
            if not output_text:
                _log_error(config, f"No output text for note {note_id}.")
                result["failed"] += 1
                continue

            try:
                response = json.loads(output_text)
            except json.JSONDecodeError:
                _log_error(config, f"Invalid JSON for note {note_id}.")
                result["failed"] += 1
                continue

            if response.get("success") is not True:
                _log_debug(config, f"OpenAI success=false for note {note_id}.")
                result["failed"] += 1
                continue

            updated_any = False
            missing_keys = []
            for response_key, field_name in field_map.items():
                if response_key not in response:
                    missing_keys.append(response_key)
                    continue
                note[field_name] = str(response[response_key])
                updated_any = True

            if missing_keys:
                _log_debug(config, f"Missing response keys for note {note_id}: {missing_keys}")

            if updated_any:
                note.flush()
                result["updated"] += 1
            else:
                result["skipped"] += 1

            mw.taskman.run_on_main(
                lambda i=idx: (
                    progress_dialog.setLabelText(f"OpenAI update {i}/{total}"),
                    progress_dialog.setValue(i),
                )
            )

        return result

    def on_done(future):
        try:
            progress_dialog.close()
        except Exception:
            pass
        try:
            result = future.result()
        except Exception:
            _log_error(config, "Bulk update failed.")
            showWarning("Bulk update failed. See console for details.")
            return

        try:
            browser.onReset()
        except Exception:
            pass

        summary = f"Updated: {result['updated']}, Skipped: {result['skipped']}, Failed: {result['failed']}"
        if result.get("cancelled"):
            summary = f"Cancelled. {summary}"
        tooltip(summary, period=4000)

    mw.taskman.run_in_background(task, on_done, uses_collection=True)


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


def _setup_browser_menu(browser):
    menu = QMenu(ADDON_NAME, browser)
    button_cfgs = _get_config().get("buttons") or []
    if not button_cfgs:
        action = QAction("No buttons configured", browser)
        action.setEnabled(False)
        menu.addAction(action)
    else:
        for idx, button_cfg in enumerate(button_cfgs):
            label = (button_cfg.get("name") or f"Button {idx + 1}").strip()
            action = QAction(label, browser)
            action.triggered.connect(
                lambda checked=False, cfg=button_cfg, br=browser: _run_button_bulk(br, cfg)
            )
            menu.addAction(action)

    browser.form.menu_Notes.addMenu(menu)


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
    action.setToolTip("Edit add-on config. openai_anki_api_key can be empty if OPENAI_ANKI_API_KEY is set.")
    action.triggered.connect(_open_config)
    menu.addAction(action)
    mw.form.menubar.addMenu(menu)


_setup_menu()
gui_hooks.editor_did_init_buttons.append(_add_editor_buttons)
gui_hooks.browser_menus_did_init.append(_setup_browser_menu)
