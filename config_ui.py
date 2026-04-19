import json
import os
import re

from aqt.qt import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSplitter,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
    Qt,
)
from aqt.utils import tooltip

EXPORT_SCHEMA_VERSION = 1
SUPPORTED_PROVIDERS = [("openai", "OpenAI")]
SUPPORTED_MODES = [
    ("saved_prompt", "Saved Prompt"),
    ("manual", "Manual"),
]
FIELD_PATTERN = re.compile(r"{{(.*?)}}")


BUTTON_DEFAULTS = {
    "name": "",
    "tooltip": "",
    "provider": "openai",
    "mode": "saved_prompt",
    "model": "",
    "saved_prompt_id": "",
    "saved_prompt_version": "latest",
    "system_prompt": "",
    "user_prompt": "",
    "field_map": {},
}

TOP_LEVEL_DEFAULTS = {
    "providers": {
        "openai_api_key": "",
    },
    "debug": False,
    "request_timeout_seconds": 90,
    "buttons": [],
}


def normalize_button(raw):
    raw = dict(raw or {})
    field_map = raw.get("field_map")
    if not isinstance(field_map, dict):
        field_map = {}

    inferred_mode = raw.get("mode")
    if not inferred_mode:
        inferred_mode = "saved_prompt" if raw.get("prompt_id") else "manual"

    button = {
        "name": str(raw.get("name") or ""),
        "tooltip": str(raw.get("tooltip") or ""),
        "provider": str(raw.get("provider") or "openai"),
        "mode": str(inferred_mode),
        "model": str(raw.get("model") or ""),
        "saved_prompt_id": str(raw.get("saved_prompt_id") or raw.get("prompt_id") or ""),
        "saved_prompt_version": str(
            raw.get("saved_prompt_version") or raw.get("prompt_version") or "latest"
        ),
        "system_prompt": str(raw.get("system_prompt") or ""),
        "user_prompt": str(raw.get("user_prompt") or raw.get("prompt") or ""),
        "field_map": {
            str(response_key): str(field_name)
            for response_key, field_name in field_map.items()
        },
    }

    if button["provider"] != "openai":
        button["mode"] = "manual"
    if button["mode"] not in {"saved_prompt", "manual"}:
        button["mode"] = "saved_prompt"
    return button


def normalize_config(raw):
    raw = dict(raw or {})
    providers = raw.get("providers")
    if not isinstance(providers, dict):
        providers = {}

    openai_api_key = str(
        providers.get("openai_api_key")
        or raw.get("openai_anki_api_key")
        or raw.get("openai_api_key")
        or ""
    )

    try:
        timeout = int(raw.get("request_timeout_seconds", TOP_LEVEL_DEFAULTS["request_timeout_seconds"]))
    except (TypeError, ValueError):
        timeout = TOP_LEVEL_DEFAULTS["request_timeout_seconds"]

    buttons = raw.get("buttons")
    if not isinstance(buttons, list):
        buttons = []

    return {
        "providers": {
            "openai_api_key": openai_api_key,
        },
        "debug": bool(raw.get("debug")),
        "request_timeout_seconds": max(10, min(300, timeout)),
        "buttons": [normalize_button(button) for button in buttons],
    }


def exportable_button(button):
    return normalize_button(button)


def exportable_config(config):
    normalized = normalize_config(config)
    return {
        "debug": normalized["debug"],
        "request_timeout_seconds": normalized["request_timeout_seconds"],
        "providers": {},
        "buttons": [exportable_button(button) for button in normalized["buttons"]],
    }


def _known_field_names(mw):
    names = set()
    collection = getattr(mw, "col", None)
    if collection is None:
        return names
    try:
        models = collection.models.all()
    except Exception:
        return names
    for model in models:
        for field in model.get("flds", []):
            name = field.get("name")
            if name:
                names.add(name)
    return names


def _provider_label(provider):
    for value, label in SUPPORTED_PROVIDERS:
        if value == provider:
            return label
    return provider


def _mode_label(mode):
    for value, label in SUPPORTED_MODES:
        if value == mode:
            return label
    return mode


def _make_imported_name(existing_names, requested_name):
    base = requested_name.strip() or "Imported Button"
    if base not in existing_names:
        return base

    candidate = f"{base} (Imported)"
    if candidate not in existing_names:
        return candidate

    index = 2
    while True:
        candidate = f"{base} (Imported {index})"
        if candidate not in existing_names:
            return candidate
        index += 1


class MappingRowWidget(QWidget):
    def __init__(self, field_names, response_key="", field_name="", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.response_key = QLineEdit(response_key)
        self.response_key.setPlaceholderText("response key")
        layout.addWidget(self.response_key, 1)

        self.field_name = QComboBox()
        self.field_name.setEditable(True)
        self.field_name.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.field_name.addItems(sorted(field_names))
        self.field_name.setCurrentText(field_name)
        completer = QCompleter(sorted(field_names), self.field_name)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.field_name.setCompleter(completer)
        layout.addWidget(self.field_name, 1)

        self.remove_button = QPushButton("Remove")
        self.remove_button.setFixedWidth(80)
        layout.addWidget(self.remove_button)

    def values(self):
        return self.response_key.text().strip(), self.field_name.currentText().strip()


class OpenAIConfigDialog(QDialog):
    def __init__(self, mw, addon_name, config):
        super().__init__(mw)
        self.mw = mw
        self.addon_name = addon_name
        self.known_fields = _known_field_names(mw)
        self.working_config = normalize_config(config)
        self.current_button_index = -1
        self.mapping_rows = []

        self.setWindowTitle("OpenAI Card Updater Configuration")
        self.resize(1160, 780)

        self._build_ui()
        self._load_global_fields()
        self._refresh_button_list()
        if self.working_config["buttons"]:
            self.button_list.setCurrentRow(0)
        else:
            self._set_button_editor_enabled(False)

    def _build_ui(self):
        root = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        root.addWidget(splitter, 1)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.addWidget(QLabel("Buttons"))

        self.button_list = QListWidget()
        self.button_list.currentRowChanged.connect(self._on_button_selected)
        left_layout.addWidget(self.button_list, 1)

        button_actions = QGridLayout()
        self.add_button = QPushButton("Add Button")
        self.duplicate_button = QPushButton("Duplicate Button")
        self.remove_button = QPushButton("Remove Button")
        self.move_up_button = QPushButton("Move Up")
        self.move_down_button = QPushButton("Move Down")
        self.import_button = QPushButton("Import Button")
        self.export_button = QPushButton("Export Button")

        self.add_button.clicked.connect(self._add_button)
        self.duplicate_button.clicked.connect(self._duplicate_button)
        self.remove_button.clicked.connect(self._remove_button)
        self.move_up_button.clicked.connect(lambda: self._move_button(-1))
        self.move_down_button.clicked.connect(lambda: self._move_button(1))
        self.import_button.clicked.connect(self._import_button)
        self.export_button.clicked.connect(self._export_button)

        button_actions.addWidget(self.add_button, 0, 0)
        button_actions.addWidget(self.duplicate_button, 0, 1)
        button_actions.addWidget(self.remove_button, 1, 0)
        button_actions.addWidget(self.move_up_button, 1, 1)
        button_actions.addWidget(self.move_down_button, 2, 0, 1, 2)
        button_actions.addWidget(self.import_button, 3, 0)
        button_actions.addWidget(self.export_button, 3, 1)
        left_layout.addLayout(button_actions)

        global_transfer_group = QGroupBox("Global Import / Export")
        global_transfer_layout = QVBoxLayout(global_transfer_group)
        self.import_all_button = QPushButton("Import All")
        self.export_all_button = QPushButton("Export All")
        self.import_all_button.clicked.connect(self._import_all)
        self.export_all_button.clicked.connect(self._export_all)
        global_transfer_layout.addWidget(self.import_all_button)
        global_transfer_layout.addWidget(self.export_all_button)
        left_layout.addWidget(global_transfer_group)

        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)

        global_group = QGroupBox("Global Settings")
        global_form = QFormLayout(global_group)
        api_key_row = QWidget()
        api_key_layout = QHBoxLayout(api_key_row)
        api_key_layout.setContentsMargins(0, 0, 0, 0)
        self.openai_api_key_input = QLineEdit()
        self.openai_api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.toggle_api_key_button = QToolButton()
        self.toggle_api_key_button.setText("Show")
        self.toggle_api_key_button.setCheckable(True)
        self.toggle_api_key_button.toggled.connect(self._toggle_api_key_visibility)
        api_key_layout.addWidget(self.openai_api_key_input, 1)
        api_key_layout.addWidget(self.toggle_api_key_button)
        global_form.addRow("OpenAI API Key", api_key_row)
        helper = QLabel("Optional. If empty, OPENAI_ANKI_API_KEY will be used.")
        helper.setWordWrap(True)
        global_form.addRow("", helper)
        self.debug_checkbox = QCheckBox("Enable debug logging")
        global_form.addRow("", self.debug_checkbox)
        self.request_timeout_input = QSpinBox()
        self.request_timeout_input.setMinimum(10)
        self.request_timeout_input.setMaximum(300)
        self.request_timeout_input.setSuffix(" s")
        global_form.addRow("Request Timeout", self.request_timeout_input)
        right_layout.addWidget(global_group)

        details_group = QGroupBox("Button Details")
        details_form = QFormLayout(details_group)
        self.name_input = QLineEdit()
        self.name_input.textChanged.connect(self._on_button_name_changed)
        self.tooltip_input = QLineEdit()
        self.provider_input = QComboBox()
        for value, label in SUPPORTED_PROVIDERS:
            self.provider_input.addItem(label, value)
        self.provider_input.currentIndexChanged.connect(self._update_prompt_mode_ui)
        self.mode_input = QComboBox()
        for value, label in SUPPORTED_MODES:
            self.mode_input.addItem(label, value)
        self.mode_input.currentIndexChanged.connect(self._update_prompt_mode_ui)
        details_form.addRow("Name", self.name_input)
        details_form.addRow("Tooltip", self.tooltip_input)
        details_form.addRow("Provider", self.provider_input)
        details_form.addRow("Mode", self.mode_input)
        right_layout.addWidget(details_group)

        prompt_group = QGroupBox("Prompt Configuration")
        prompt_layout = QGridLayout(prompt_group)
        self.mode_helper_label = QLabel("")
        self.mode_helper_label.setWordWrap(True)
        prompt_layout.addWidget(self.mode_helper_label, 0, 0, 1, 2)

        self.saved_prompt_id_label = QLabel("Saved Prompt ID")
        self.saved_prompt_id_input = QLineEdit()
        prompt_layout.addWidget(self.saved_prompt_id_label, 1, 0)
        prompt_layout.addWidget(self.saved_prompt_id_input, 1, 1)

        self.saved_prompt_version_label = QLabel("Saved Prompt Version")
        self.saved_prompt_version_input = QLineEdit()
        self.saved_prompt_version_input.setPlaceholderText("latest")
        prompt_layout.addWidget(self.saved_prompt_version_label, 2, 0)
        prompt_layout.addWidget(self.saved_prompt_version_input, 2, 1)

        self.model_label = QLabel("Model")
        self.model_input = QLineEdit()
        prompt_layout.addWidget(self.model_label, 3, 0)
        prompt_layout.addWidget(self.model_input, 3, 1)

        self.system_prompt_label = QLabel("System Prompt")
        self.system_prompt_input = QPlainTextEdit()
        self.system_prompt_input.setMinimumHeight(90)
        prompt_layout.addWidget(self.system_prompt_label, 4, 0, Qt.AlignmentFlag.AlignTop)
        prompt_layout.addWidget(self.system_prompt_input, 4, 1)

        self.user_prompt_label = QLabel("User Prompt")
        self.user_prompt_input = QPlainTextEdit()
        self.user_prompt_input.setMinimumHeight(120)
        prompt_layout.addWidget(self.user_prompt_label, 5, 0, Qt.AlignmentFlag.AlignTop)
        prompt_layout.addWidget(self.user_prompt_input, 5, 1)

        prompt_helper = QLabel(
            "Both System Prompt and User Prompt support {{FieldName}} expansion from the current note."
        )
        prompt_helper.setWordWrap(True)
        prompt_layout.addWidget(prompt_helper, 6, 0, 1, 2)
        right_layout.addWidget(prompt_group)

        mappings_group = QGroupBox("Field Mappings")
        mappings_layout = QVBoxLayout(mappings_group)
        mapping_header = QLabel(
            "Each row maps one JSON response key from the provider response to one Anki field."
        )
        mapping_header.setWordWrap(True)
        mappings_layout.addWidget(mapping_header)

        mapping_subheader = QLabel(
            "Left: response key returned by the provider. Right: Anki field to update."
        )
        mapping_subheader.setWordWrap(True)
        mappings_layout.addWidget(mapping_subheader)

        mapping_labels = QWidget()
        mapping_labels_layout = QHBoxLayout(mapping_labels)
        mapping_labels_layout.setContentsMargins(0, 0, 0, 0)
        mapping_labels_layout.setSpacing(6)
        response_label = QLabel("Response key")
        response_label.setMinimumWidth(220)
        field_label = QLabel("Anki field")
        field_label.setMinimumWidth(220)
        remove_label = QLabel("")
        remove_label.setFixedWidth(80)
        mapping_labels_layout.addWidget(response_label, 1)
        mapping_labels_layout.addWidget(field_label, 1)
        mapping_labels_layout.addWidget(remove_label)
        mappings_layout.addWidget(mapping_labels)

        self.mapping_container = QWidget()
        self.mapping_layout = QVBoxLayout(self.mapping_container)
        self.mapping_layout.setContentsMargins(0, 0, 0, 0)
        self.mapping_layout.setSpacing(6)
        mappings_layout.addWidget(self.mapping_container)

        self.add_mapping_button = QPushButton("Add Mapping")
        self.add_mapping_button.clicked.connect(lambda: self._add_mapping_row())
        mappings_layout.addWidget(self.add_mapping_button, 0, Qt.AlignmentFlag.AlignLeft)
        right_layout.addWidget(mappings_group)

        right_layout.addStretch(1)
        right_scroll.setWidget(right_container)

        splitter.addWidget(left_panel)
        splitter.addWidget(right_scroll)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 860])

        self.editor_sections = [
            details_group,
            prompt_group,
            mappings_group,
        ]

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self._save)
        button_box.rejected.connect(self.reject)
        root.addWidget(button_box)

    def _toggle_api_key_visibility(self, checked):
        self.openai_api_key_input.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )
        self.toggle_api_key_button.setText("Hide" if checked else "Show")

    def _button_provider(self):
        return self.provider_input.currentData()

    def _button_mode(self):
        return self.mode_input.currentData()

    def _set_row_visible(self, label_widget, field_widget, visible):
        label_widget.setVisible(visible)
        field_widget.setVisible(visible)

    def _update_prompt_mode_ui(self):
        provider = self._button_provider()
        mode = self._button_mode()

        self.mode_input.blockSignals(True)
        if provider != "openai":
            self.mode_input.setCurrentIndex(self.mode_input.findData("manual"))
            mode = "manual"
        self.mode_input.blockSignals(False)

        saved_prompt_visible = provider == "openai" and mode == "saved_prompt"
        manual_visible = mode == "manual"

        self._set_row_visible(self.saved_prompt_id_label, self.saved_prompt_id_input, saved_prompt_visible)
        self._set_row_visible(
            self.saved_prompt_version_label,
            self.saved_prompt_version_input,
            saved_prompt_visible,
        )
        self._set_row_visible(self.system_prompt_label, self.system_prompt_input, manual_visible)

        if saved_prompt_visible:
            self.mode_helper_label.setText(
                "Use an OpenAI saved prompt ID plus a local User Prompt."
            )
        else:
            self.mode_helper_label.setText(
                "Send System Prompt + User Prompt directly. Model is required in manual mode."
            )

    def _set_button_editor_enabled(self, enabled):
        for widget in self.editor_sections:
            widget.setEnabled(enabled)
        self.duplicate_button.setEnabled(enabled)
        self.remove_button.setEnabled(enabled)
        self.export_button.setEnabled(enabled)
        self.move_up_button.setEnabled(enabled and self.current_button_index > 0)
        self.move_down_button.setEnabled(
            enabled and 0 <= self.current_button_index < len(self.working_config["buttons"]) - 1
        )

    def _load_global_fields(self):
        providers = self.working_config.get("providers", {})
        self.openai_api_key_input.setText(providers.get("openai_api_key", ""))
        self.debug_checkbox.setChecked(bool(self.working_config.get("debug")))
        self.request_timeout_input.setValue(
            int(self.working_config.get("request_timeout_seconds", 90))
        )

    def _refresh_button_list(self):
        self.button_list.blockSignals(True)
        self.button_list.clear()
        for button in self.working_config["buttons"]:
            name = (button.get("name") or "").strip() or "Unnamed Button"
            self.button_list.addItem(QListWidgetItem(name))
        self.button_list.blockSignals(False)

        has_buttons = bool(self.working_config["buttons"])
        if not has_buttons:
            self.current_button_index = -1
            self._clear_button_fields()
        self._set_button_editor_enabled(has_buttons)

    def _clear_button_fields(self):
        self.name_input.clear()
        self.tooltip_input.clear()
        self.provider_input.setCurrentIndex(self.provider_input.findData("openai"))
        self.mode_input.setCurrentIndex(self.mode_input.findData("saved_prompt"))
        self.saved_prompt_id_input.clear()
        self.saved_prompt_version_input.clear()
        self.model_input.clear()
        self.system_prompt_input.clear()
        self.user_prompt_input.clear()
        self._clear_mapping_rows()
        self._update_prompt_mode_ui()

    def _store_current_button(self):
        if self.current_button_index < 0:
            return
        button = self.working_config["buttons"][self.current_button_index]
        button["name"] = self.name_input.text().strip()
        button["tooltip"] = self.tooltip_input.text().strip()
        button["provider"] = str(self.provider_input.currentData() or "openai")
        button["mode"] = str(self.mode_input.currentData() or "saved_prompt")
        button["saved_prompt_id"] = self.saved_prompt_id_input.text().strip()
        saved_prompt_version = self.saved_prompt_version_input.text().strip()
        button["saved_prompt_version"] = saved_prompt_version or "latest"
        button["model"] = self.model_input.text().strip()
        button["system_prompt"] = self.system_prompt_input.toPlainText()
        button["user_prompt"] = self.user_prompt_input.toPlainText()
        button["field_map"] = self._mapping_rows_to_dict()
        self.working_config["buttons"][self.current_button_index] = normalize_button(button)
        self._update_list_item(self.current_button_index)

    def _load_button(self, index):
        if index < 0 or index >= len(self.working_config["buttons"]):
            self._set_button_editor_enabled(False)
            self._clear_button_fields()
            return

        button = normalize_button(self.working_config["buttons"][index])
        self.name_input.setText(button["name"])
        self.tooltip_input.setText(button["tooltip"])
        self.provider_input.setCurrentIndex(self.provider_input.findData(button["provider"]))
        self.mode_input.setCurrentIndex(self.mode_input.findData(button["mode"]))
        self.saved_prompt_id_input.setText(button["saved_prompt_id"])
        version = button.get("saved_prompt_version", "latest")
        self.saved_prompt_version_input.setText("" if version == "latest" else version)
        self.model_input.setText(button["model"])
        self.system_prompt_input.setPlainText(button["system_prompt"])
        self.user_prompt_input.setPlainText(button["user_prompt"])
        self._load_mapping_rows(button["field_map"])
        self._set_button_editor_enabled(True)
        self._update_prompt_mode_ui()

    def _on_button_selected(self, row):
        if row == self.current_button_index:
            return
        self._store_current_button()
        self.current_button_index = row
        self._load_button(row)

    def _update_list_item(self, index):
        if index < 0 or index >= self.button_list.count():
            return
        item = self.button_list.item(index)
        button = self.working_config["buttons"][index]
        item.setText((button.get("name") or "").strip() or "Unnamed Button")
        self._set_button_editor_enabled(True)

    def _add_button(self):
        self._store_current_button()
        self.working_config["buttons"].append(normalize_button({}))
        self._refresh_button_list()
        self.button_list.setCurrentRow(len(self.working_config["buttons"]) - 1)

    def _duplicate_button(self):
        if self.current_button_index < 0:
            return
        self._store_current_button()
        original = dict(self.working_config["buttons"][self.current_button_index])
        original["field_map"] = dict(original.get("field_map", {}))
        base_name = (original.get("name") or "Unnamed Button").strip() or "Unnamed Button"
        if base_name.endswith(" Copy"):
            copy_name = f"{base_name} 2"
        else:
            copy_name = f"{base_name} Copy"
        original["name"] = copy_name
        self.working_config["buttons"].insert(
            self.current_button_index + 1,
            normalize_button(original),
        )
        self._refresh_button_list()
        self.button_list.setCurrentRow(self.current_button_index + 1)

    def _remove_button(self):
        if self.current_button_index < 0:
            return
        button = self.working_config["buttons"][self.current_button_index]
        name = (button.get("name") or "").strip() or "Unnamed Button"
        response = QMessageBox.question(
            self,
            "Remove Button",
            f"Remove button '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if response != QMessageBox.StandardButton.Yes:
            return
        del self.working_config["buttons"][self.current_button_index]
        next_index = min(self.current_button_index, len(self.working_config["buttons"]) - 1)
        self.current_button_index = -1
        self._refresh_button_list()
        if next_index >= 0:
            self.button_list.setCurrentRow(next_index)

    def _move_button(self, offset):
        if self.current_button_index < 0:
            return
        self._store_current_button()
        new_index = self.current_button_index + offset
        if new_index < 0 or new_index >= len(self.working_config["buttons"]):
            return
        buttons = self.working_config["buttons"]
        buttons[self.current_button_index], buttons[new_index] = (
            buttons[new_index],
            buttons[self.current_button_index],
        )
        self.current_button_index = -1
        self._refresh_button_list()
        self.button_list.setCurrentRow(new_index)

    def _on_button_name_changed(self, text):
        if self.current_button_index < 0:
            return
        self.working_config["buttons"][self.current_button_index]["name"] = text.strip()
        self._update_list_item(self.current_button_index)

    def _clear_mapping_rows(self):
        while self.mapping_layout.count():
            item = self.mapping_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.mapping_rows = []

    def _add_mapping_row(self, response_key="", field_name=""):
        row = MappingRowWidget(self.known_fields, response_key, field_name, self.mapping_container)
        row.remove_button.clicked.connect(lambda: self._remove_mapping_row(row))
        self.mapping_rows.append(row)
        self.mapping_layout.addWidget(row)

    def _remove_mapping_row(self, row):
        if row in self.mapping_rows:
            self.mapping_rows.remove(row)
        row.setParent(None)
        row.deleteLater()

    def _load_mapping_rows(self, field_map):
        self._clear_mapping_rows()
        if not field_map:
            self._add_mapping_row()
            return
        for response_key, field_name in field_map.items():
            self._add_mapping_row(response_key, field_name)

    def _mapping_rows_to_dict(self):
        field_map = {}
        for row in self.mapping_rows:
            response_key, field_name = row.values()
            if not response_key and not field_name:
                continue
            field_map[response_key] = field_name
        return field_map

    def _collect_config(self):
        self._store_current_button()
        return {
            "providers": {
                "openai_api_key": self.openai_api_key_input.text().strip(),
            },
            "debug": self.debug_checkbox.isChecked(),
            "request_timeout_seconds": self.request_timeout_input.value(),
            "buttons": [normalize_button(button) for button in self.working_config["buttons"]],
        }

    def _validate(self, config):
        blocking = []
        warnings = []
        seen_button_names = {}

        providers = config.get("providers", {})
        if not providers.get("openai_api_key") and not os.environ.get("OPENAI_ANKI_API_KEY"):
            warnings.append(
                "OpenAI API key is blank and OPENAI_ANKI_API_KEY is not currently set in the environment."
            )

        for index, button in enumerate(config.get("buttons", []), start=1):
            label = f"Button {index}"
            name = button.get("name", "").strip()
            provider = button.get("provider", "").strip()
            mode = button.get("mode", "").strip()
            field_map = button.get("field_map", {})

            if not name:
                blocking.append(f"{label}: name is required.")
            else:
                seen_button_names.setdefault(name, 0)
                seen_button_names[name] += 1

            if provider not in {value for value, _label in SUPPORTED_PROVIDERS}:
                blocking.append(f"{label}: unsupported provider '{provider}'.")

            if mode == "saved_prompt":
                if not button.get("saved_prompt_id", "").strip():
                    blocking.append(f"{label}: saved_prompt_id is required in saved prompt mode.")
            elif mode == "manual":
                if not button.get("model", "").strip():
                    blocking.append(f"{label}: model is required in manual mode.")
                if not button.get("system_prompt", "").strip():
                    blocking.append(f"{label}: system_prompt is required in manual mode.")
                if not button.get("user_prompt", "").strip():
                    blocking.append(f"{label}: user_prompt is required in manual mode.")
            else:
                blocking.append(f"{label}: unsupported mode '{mode}'.")

            seen_response_keys = set()
            mapped_targets = []
            for response_key, field_name in field_map.items():
                response_key = (response_key or "").strip()
                field_name = (field_name or "").strip()
                if not response_key or not field_name:
                    blocking.append(
                        f"{label}: every mapping row must include both a response key and a target field."
                    )
                    continue
                if response_key in seen_response_keys:
                    blocking.append(f"{label}: duplicate response key '{response_key}'.")
                seen_response_keys.add(response_key)
                mapped_targets.append(field_name)
                if field_name not in self.known_fields:
                    warnings.append(f"{label}: target field '{field_name}' is not a known field name.")

            for field_name in sorted(set(mapped_targets)):
                if mapped_targets.count(field_name) > 1:
                    warnings.append(
                        f"{label}: multiple response keys map to the same Anki field '{field_name}'."
                    )

            prompt_fields = []
            if mode == "manual":
                prompt_fields.append(("system_prompt", button.get("system_prompt", "")))
            prompt_fields.append(("user_prompt", button.get("user_prompt", "")))
            for field_name, prompt_text in prompt_fields:
                unknown_prompt_fields = sorted(
                    {
                        match.group(1).strip()
                        for match in FIELD_PATTERN.finditer(prompt_text)
                        if match.group(1).strip()
                        and match.group(1).strip() not in self.known_fields
                    }
                )
                if unknown_prompt_fields:
                    warnings.append(
                        f"{label}: {field_name} references unknown fields: {', '.join(unknown_prompt_fields)}."
                    )

        duplicate_names = sorted(name for name, count in seen_button_names.items() if count > 1)
        if duplicate_names:
            warnings.append(f"Duplicate button names found: {', '.join(duplicate_names)}.")

        return blocking, warnings

    def _save(self):
        config = self._collect_config()
        blocking, warnings = self._validate(config)

        if blocking:
            QMessageBox.warning(self, "Fix Configuration Errors", "\n".join(blocking))
            return

        if warnings:
            response = QMessageBox.warning(
                self,
                "Configuration Warnings",
                "\n".join(warnings) + "\n\nSave anyway?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if response != QMessageBox.StandardButton.Save:
                return

        try:
            self.mw.addonManager.writeConfig(self.addon_name, config)
        except Exception as err:
            QMessageBox.critical(self, "Save Failed", f"Could not save configuration:\n{err}")
            return

        tooltip(
            "Configuration saved. Reopen editor/browser windows to refresh button lists.",
            period=5000,
        )
        self.accept()

    def _import_json_file(self, expected_type):
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Import JSON",
            "",
            "JSON Files (*.json)",
        )
        if not path:
            return None
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception as err:
            QMessageBox.warning(self, "Import Failed", f"Could not read file:\n{err}")
            return None

        if not isinstance(payload, dict):
            QMessageBox.warning(self, "Import Failed", "Imported file must contain a JSON object.")
            return None
        if payload.get("schema_version") != EXPORT_SCHEMA_VERSION:
            QMessageBox.warning(
                self,
                "Import Failed",
                f"Unsupported schema_version: {payload.get('schema_version')}",
            )
            return None
        if payload.get("type") != expected_type:
            QMessageBox.warning(
                self,
                "Import Failed",
                f"Expected import type '{expected_type}', got '{payload.get('type')}'.",
            )
            return None
        return payload

    def _export_json_file(self, default_name, payload):
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export JSON",
            default_name,
            "JSON Files (*.json)",
        )
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
        except Exception as err:
            QMessageBox.warning(self, "Export Failed", f"Could not write file:\n{err}")
            return
        tooltip("Export complete.", period=3000)

    def _export_button(self):
        if self.current_button_index < 0:
            return
        self._store_current_button()
        button = exportable_button(self.working_config["buttons"][self.current_button_index])
        payload = {
            "schema_version": EXPORT_SCHEMA_VERSION,
            "type": "button",
            "button": button,
        }
        default_name = f"{button['name'] or 'button'}.json"
        self._export_json_file(default_name, payload)

    def _import_button(self):
        payload = self._import_json_file("button")
        if not payload:
            return

        imported_button = normalize_button(payload.get("button"))
        self._store_current_button()
        existing_names = {button["name"] for button in self.working_config["buttons"]}
        original_name = imported_button["name"]
        imported_button["name"] = _make_imported_name(existing_names, original_name)
        self.working_config["buttons"].append(imported_button)
        self._refresh_button_list()
        self.button_list.setCurrentRow(len(self.working_config["buttons"]) - 1)
        if imported_button["name"] != original_name:
            tooltip(f"Imported as '{imported_button['name']}' to avoid a duplicate name.", period=4000)
        else:
            tooltip("Button imported.", period=3000)

    def _export_all(self):
        config = self._collect_config()
        payload = {
            "schema_version": EXPORT_SCHEMA_VERSION,
            "type": "config",
            "config": exportable_config(config),
        }
        self._export_json_file("openai-card-updater-config.json", payload)

    def _ask_global_import_mode(self):
        box = QMessageBox(self)
        box.setWindowTitle("Import Configuration")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText("How should the imported configuration be applied?")
        merge_button = box.addButton("Merge", QMessageBox.ButtonRole.AcceptRole)
        replace_button = box.addButton("Replace", QMessageBox.ButtonRole.DestructiveRole)
        cancel_button = box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(merge_button)
        box.exec()
        clicked = box.clickedButton()
        if clicked == merge_button:
            return "merge"
        if clicked == replace_button:
            return "replace"
        if clicked == cancel_button:
            return None
        return None

    def _import_all(self):
        payload = self._import_json_file("config")
        if not payload:
            return

        mode = self._ask_global_import_mode()
        if mode is None:
            return

        imported_config = normalize_config(payload.get("config"))
        current_config = self._collect_config()
        current_providers = dict(current_config.get("providers", {}))

        renamed = 0
        imported_buttons = []
        existing_names = set()
        if mode == "merge":
            existing_names = {button["name"] for button in current_config["buttons"]}

        for button in imported_config["buttons"]:
            imported_button = normalize_button(button)
            requested_name = imported_button["name"]
            imported_button["name"] = _make_imported_name(existing_names, requested_name)
            if imported_button["name"] != requested_name:
                renamed += 1
            existing_names.add(imported_button["name"])
            imported_buttons.append(imported_button)

        if mode == "replace":
            new_config = {
                "providers": current_providers,
                "debug": imported_config["debug"],
                "request_timeout_seconds": imported_config["request_timeout_seconds"],
                "buttons": imported_buttons,
            }
        else:
            new_config = {
                "providers": current_providers,
                "debug": imported_config["debug"],
                "request_timeout_seconds": imported_config["request_timeout_seconds"],
                "buttons": current_config["buttons"] + imported_buttons,
            }

        self.working_config = normalize_config(new_config)
        self.current_button_index = -1
        self._load_global_fields()
        self._refresh_button_list()
        if self.working_config["buttons"]:
            self.button_list.setCurrentRow(0)
        message = f"Imported {len(imported_buttons)} button(s)."
        if renamed:
            message += f" Renamed {renamed} duplicate import(s)."
        tooltip(message, period=4000)
