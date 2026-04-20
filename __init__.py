import json
import os
import re
import socket
import threading
import time
import traceback
import urllib.error
import urllib.request

from aqt import gui_hooks, mw
from aqt.qt import QAction, QMenu, QMessageBox, QProgressDialog, Qt
from aqt.utils import showWarning, tooltip

from .config_ui import OpenAIConfigDialog, normalize_button, normalize_config

ADDON_NAME = "OpenAI Card Updater"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEEPSEEK_CHAT_COMPLETIONS_URL = "https://api.deepseek.com/chat/completions"
MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "manifest.json")
DEFAULT_REQUEST_TIMEOUT_SECONDS = 90
RETRYABLE_HTTP_STATUS_CODES = {429, 500, 502, 503, 504}
SINGLE_NOTE_RETRY_ATTEMPTS = 1
BULK_RETRY_ATTEMPTS = 1
BULK_RETRY_DELAY_SECONDS = 1.5


def _get_config():
    config = mw.addonManager.getConfig(__name__)
    return normalize_config(config or {})


def _get_addon_version():
    try:
        with open(MANIFEST_PATH, "r", encoding="utf-8") as manifest_file:
            manifest = json.load(manifest_file)
    except Exception:
        return "unknown"
    return str(manifest.get("version") or "unknown")


def _debug_enabled(config):
    return bool(config.get("debug"))


def _request_timeout_seconds(config):
    raw_timeout = config.get("request_timeout_seconds", DEFAULT_REQUEST_TIMEOUT_SECONDS)
    try:
        timeout = int(raw_timeout)
    except (TypeError, ValueError):
        timeout = DEFAULT_REQUEST_TIMEOUT_SECONDS
    return max(10, timeout)


def _log_debug(config, message):
    if _debug_enabled(config):
        print(f"[{ADDON_NAME}] {message}")


def _log_error(config, message, include_traceback=True):
    print(f"[{ADDON_NAME}] ERROR: {message}")
    if include_traceback and _debug_enabled(config):
        traceback.print_exc()


def _provider_label(provider):
    if provider == "deepseek":
        return "DeepSeek"
    return "OpenAI"


def _get_provider_api_key(config, provider):
    providers = config.get("providers") or {}
    if provider == "deepseek":
        key = str(providers.get("deepseek_api_key") or "").strip()
        if key:
            return key
        env_key = (os.environ.get("DEEPSEEK_ANKI_API_KEY") or "").strip()
        if env_key:
            return env_key
        return ""

    key = str(providers.get("openai_api_key") or "").strip()
    if key:
        return key
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


def _ensure_json_instruction(system_text, user_text):
    user_lower = (user_text or "").lower()
    if "json" in user_lower:
        return system_text, user_text
    if not user_text:
        return system_text, "Return output as JSON."
    return system_text, f"{user_text}\n\nReturn output as JSON."


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


def _read_http_error_body(err):
    try:
        return err.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def _extract_api_error_message(body):
    if not body:
        return ""
    try:
        payload = json.loads(body)
    except Exception:
        return ""
    error = payload.get("error")
    if not isinstance(error, dict):
        return ""
    message = error.get("message")
    if not message:
        return ""
    return str(message).strip()


def _classify_provider_error(provider, err, timeout_seconds):
    provider_label = _provider_label(provider)
    if isinstance(err, urllib.error.HTTPError):
        body = _read_http_error_body(err)
        api_message = _extract_api_error_message(body)
        retryable = err.code in RETRYABLE_HTTP_STATUS_CODES
        user_message = f"{provider_label} request failed (HTTP {err.code})."
        if err.code == 429:
            user_message = f"{provider_label} rate limit reached (HTTP 429)."
        elif retryable:
            user_message = f"{provider_label} temporary server error (HTTP {err.code})."
        elif api_message:
            user_message = f"{provider_label} error: {api_message}"
        if body:
            log_message = f"HTTP error {err.code}: {body}"
        else:
            log_message = f"HTTP error {err.code}"
        return {
            "retryable": retryable,
            "user_message": user_message,
            "details": body,
            "log_message": log_message,
            "category": "http",
        }

    if isinstance(err, (TimeoutError, socket.timeout)):
        return {
            "retryable": True,
            "user_message": f"{provider_label} request timed out after {timeout_seconds}s.",
            "details": "",
            "log_message": f"{provider_label} request timed out after {timeout_seconds}s.",
            "category": "timeout",
        }

    if isinstance(err, urllib.error.URLError):
        reason = str(getattr(err, "reason", err))
        return {
            "retryable": True,
            "user_message": f"Network error contacting {provider_label}: {reason}",
            "details": reason,
            "log_message": f"Network error contacting {provider_label}: {reason}",
            "category": "network",
        }

    return {
        "retryable": False,
        "user_message": f"{provider_label} request failed. See console for details.",
        "details": "",
        "log_message": f"{provider_label} request failed: {err}",
        "category": "unknown",
    }


def _show_provider_error(parent, title, error_info, debug_enabled, offer_retry):
    if callable(parent):
        try:
            parent = parent()
        except Exception:
            parent = None
    parent = parent or mw.app.activeWindow() or mw
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setText(error_info["user_message"])
    if debug_enabled and error_info["details"]:
        box.setDetailedText(error_info["details"])
    if offer_retry:
        box.setInformativeText("Do you want to retry the request?")
        box.setStandardButtons(
            QMessageBox.StandardButton.Retry | QMessageBox.StandardButton.Cancel
        )
        box.setDefaultButton(QMessageBox.StandardButton.Retry)
        box.raise_()
        box.activateWindow()
        return box.exec() == QMessageBox.StandardButton.Retry

    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.raise_()
    box.activateWindow()
    box.exec()
    return False


def _call_openai(config, button_cfg, prompt_values, timeout_seconds):
    mode = button_cfg.get("mode") or "saved_prompt"
    model = (button_cfg.get("model") or "").strip()
    payload = {"text": {"format": {"type": "json_object"}}}

    if mode == "saved_prompt":
        prompt_id = (button_cfg.get("saved_prompt_id") or "").strip()
        prompt_version = (button_cfg.get("saved_prompt_version") or "latest").strip()
        payload["prompt"] = {"id": prompt_id}
        if prompt_version and prompt_version.lower() != "latest":
            payload["prompt"]["version"] = prompt_version
        if prompt_values["user_prompt"]:
            payload["input"] = prompt_values["user_prompt"]
    elif mode == "manual":
        if not model:
            raise ValueError("Model is required for manual mode.")
        payload["model"] = model
        if prompt_values["system_prompt"]:
            payload["instructions"] = prompt_values["system_prompt"]
        if prompt_values["user_prompt"]:
            payload["input"] = prompt_values["user_prompt"]
    else:
        raise ValueError(f"Mode '{mode}' is not supported.")

    if mode == "saved_prompt" and model:
        payload["model"] = model

    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_get_provider_api_key(config, 'openai')}",
    }
    req = urllib.request.Request(OPENAI_RESPONSES_URL, data=data, headers=headers, method="POST")

    _log_debug(config, f"OpenAI request payload: {payload}")
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        body = resp.read().decode("utf-8")
        _log_debug(config, f"OpenAI response body: {body}")
        return json.loads(body)


def _call_deepseek(config, button_cfg, prompt_values, timeout_seconds):
    model = (button_cfg.get("model") or "").strip()
    messages = []
    if prompt_values["system_prompt"]:
        messages.append({"role": "system", "content": prompt_values["system_prompt"]})
    if prompt_values["user_prompt"]:
        messages.append({"role": "user", "content": prompt_values["user_prompt"]})
    if not messages:
        raise ValueError("At least one prompt message is required.")

    payload = {
        "model": model,
        "messages": messages,
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_get_provider_api_key(config, 'deepseek')}",
    }
    req = urllib.request.Request(
        DEEPSEEK_CHAT_COMPLETIONS_URL,
        data=data,
        headers=headers,
        method="POST",
    )

    _log_debug(config, f"DeepSeek request payload: {payload}")
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        body = resp.read().decode("utf-8")
        _log_debug(config, f"DeepSeek response body: {body}")
        return json.loads(body)


def _call_provider(config, button_cfg, prompt_values, timeout_seconds):
    provider = button_cfg.get("provider") or "openai"
    if provider == "deepseek":
        return _call_deepseek(config, button_cfg, prompt_values, timeout_seconds)
    if provider == "openai":
        return _call_openai(config, button_cfg, prompt_values, timeout_seconds)
    raise ValueError(f"Provider '{provider}' is not supported.")


def _extract_provider_output_text(button_cfg, response_json):
    provider = button_cfg.get("provider") or "openai"
    if provider == "deepseek":
        choices = response_json.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        return (message.get("content") or "").strip()
    return _extract_output_text(response_json)


def _validate_button_request(button_cfg):
    provider = button_cfg.get("provider") or "openai"
    mode = button_cfg.get("mode") or "saved_prompt"

    if provider == "openai":
        if mode == "saved_prompt" and not (button_cfg.get("saved_prompt_id") or "").strip():
            return "Button is missing saved_prompt_id."
        if mode == "manual" and not (button_cfg.get("model") or "").strip():
            return "Button is missing model for manual mode."
        return None

    if provider == "deepseek":
        if mode != "manual":
            return "DeepSeek currently supports manual mode only."
        if not (button_cfg.get("model") or "").strip():
            return "Button is missing model for manual mode."
        return None

    return f"Provider '{provider}' is not supported."


def _handle_response(editor, note_id, button_cfg, response_json, config):
    provider = button_cfg.get("provider") or "openai"
    provider_label = _provider_label(provider)
    output_text = _extract_provider_output_text(button_cfg, response_json)
    if not output_text:
        showWarning(f"{provider_label} returned no text output.")
        return

    try:
        result = json.loads(output_text)
    except json.JSONDecodeError:
        _log_error(config, "Failed to parse JSON response.")
        showWarning(f"{provider_label} response was not valid JSON.")
        return

    success = result.get("success")
    if success is not True:
        message = (
            result.get("error")
            or result.get("message")
            or f"{provider_label} reported success=false."
        )
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
    button_cfg = normalize_button(button_cfg)
    provider = button_cfg.get("provider") or "openai"
    provider_label = _provider_label(provider)
    api_key = _get_provider_api_key(config, provider)
    if not api_key:
        if provider == "deepseek":
            showWarning(
                "DeepSeek API key not set. Set providers.deepseek_api_key in config or DEEPSEEK_ANKI_API_KEY."
            )
        else:
            showWarning(
                "OpenAI API key not set. Set providers.openai_api_key in config or OPENAI_ANKI_API_KEY."
            )
        return

    if editor.note is None:
        showWarning("No note is loaded in the editor.")
        return

    system_prompt = _expand_fields(button_cfg.get("system_prompt") or "", editor.note, config)
    user_prompt = _expand_fields(button_cfg.get("user_prompt") or "", editor.note, config)
    system_prompt, user_prompt = _ensure_json_instruction(system_prompt, user_prompt)
    validation_error = _validate_button_request(button_cfg)
    if validation_error:
        showWarning(validation_error)
        return
    note_id = editor.note.id
    timeout_seconds = _request_timeout_seconds(config)

    def start_request(attempt):
        def task():
            return _call_provider(
                config,
                button_cfg,
                {"system_prompt": system_prompt, "user_prompt": user_prompt},
                timeout_seconds,
            )

        def on_done(future):
            mw.progress.finish()

            try:
                response_json = future.result()
            except Exception as err:
                error_info = _classify_provider_error(provider, err, timeout_seconds)
                _log_error(config, error_info["log_message"], include_traceback=False)
                if error_info["retryable"] and attempt <= SINGLE_NOTE_RETRY_ATTEMPTS:
                    if _show_provider_error(
                        getattr(editor, "parentWindow", None),
                        f"{provider_label} Request Failed",
                        error_info,
                        _debug_enabled(config),
                        offer_retry=True,
                    ):
                        start_request(attempt + 1)
                    return
                if not error_info["retryable"] or attempt > SINGLE_NOTE_RETRY_ATTEMPTS:
                    _show_provider_error(
                        getattr(editor, "parentWindow", None),
                        f"{provider_label} Request Failed",
                        error_info,
                        _debug_enabled(config),
                        offer_retry=False,
                    )
                    return

            _handle_response(editor, note_id, button_cfg, response_json, config)

        mw.progress.start(
            label=f"{provider_label} update in progress... (timeout {timeout_seconds}s)",
            immediate=True,
        )
        mw.taskman.run_in_background(task, on_done)

    start_request(1)


def _run_button_bulk(browser, button_cfg):
    config = _get_config()
    button_cfg = normalize_button(button_cfg)
    provider = button_cfg.get("provider") or "openai"
    provider_label = _provider_label(provider)
    api_key = _get_provider_api_key(config, provider)
    if not api_key:
        if provider == "deepseek":
            showWarning(
                "DeepSeek API key not set. Set providers.deepseek_api_key in config or DEEPSEEK_ANKI_API_KEY."
            )
        else:
            showWarning(
                "OpenAI API key not set. Set providers.openai_api_key in config or OPENAI_ANKI_API_KEY."
            )
        return
    validation_error = _validate_button_request(button_cfg)
    if validation_error:
        showWarning(validation_error)
        return

    note_ids = browser.selectedNotes()
    if not note_ids:
        tooltip("No notes selected.", period=3000)
        return

    field_map = button_cfg.get("field_map") or {}
    total = len(note_ids)
    timeout_seconds = _request_timeout_seconds(config)
    cancel_event = threading.Event()
    progress_dialog = QProgressDialog(f"{provider_label} bulk update...", "Cancel", 0, total, browser)
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
            "retried": 0,
            "timed_out": 0,
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

            system_prompt = _expand_fields(button_cfg.get("system_prompt") or "", note, config)
            user_prompt = _expand_fields(button_cfg.get("user_prompt") or "", note, config)
            system_prompt, user_prompt = _ensure_json_instruction(system_prompt, user_prompt)

            response_json = None
            for attempt in range(BULK_RETRY_ATTEMPTS + 1):
                try:
                    response_json = _call_provider(
                        config,
                        button_cfg,
                        {"system_prompt": system_prompt, "user_prompt": user_prompt},
                        timeout_seconds,
                    )
                    break
                except Exception as err:
                    error_info = _classify_provider_error(provider, err, timeout_seconds)
                    _log_error(
                        config,
                        f"{provider_label} request failed for note {note_id}. {error_info['log_message']}",
                        include_traceback=False,
                    )
                    if attempt < BULK_RETRY_ATTEMPTS and error_info["retryable"]:
                        result["retried"] += 1
                        _log_debug(
                            config,
                            f"Retrying note {note_id} after {BULK_RETRY_DELAY_SECONDS}s due to {error_info['category']} error.",
                        )
                        time.sleep(BULK_RETRY_DELAY_SECONDS)
                        continue
                    if error_info["category"] == "timeout":
                        result["timed_out"] += 1
                    result["failed"] += 1
                    response_json = None
                    break

            if response_json is None:
                continue

            output_text = _extract_provider_output_text(button_cfg, response_json)
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
                _log_debug(config, f"{provider_label} success=false for note {note_id}.")
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
                    progress_dialog.setLabelText(f"{provider_label} update {i}/{total}"),
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

        summary = (
            f"Updated: {result['updated']}, Skipped: {result['skipped']}, "
            f"Failed: {result['failed']}, Retried: {result['retried']}"
        )
        if result["timed_out"]:
            summary += f", Timeouts: {result['timed_out']}"
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
    dialog = OpenAIConfigDialog(mw, __name__, conf)
    dialog.exec()


def _show_about():
    version = _get_addon_version()
    QMessageBox.information(
        mw,
        "About OpenAI Card Updater",
        f"{ADDON_NAME}\nVersion {version}",
    )


def _setup_menu():
    menu = QMenu(ADDON_NAME, mw)
    configure_action = QAction("Configure...", mw)
    configure_action.setToolTip(
        "Edit add-on config. Provider API keys can be blank if matching environment variables are set."
    )
    configure_action.triggered.connect(_open_config)
    menu.addAction(configure_action)
    about_action = QAction("About", mw)
    about_action.triggered.connect(_show_about)
    menu.addAction(about_action)
    mw.form.menuTools.addMenu(menu)


_setup_menu()
gui_hooks.editor_did_init_buttons.append(_add_editor_buttons)
gui_hooks.browser_menus_did_init.append(_setup_browser_menu)
