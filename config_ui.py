import os
import re

from aqt.qt import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
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
    QSizePolicy,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
    Qt,
)
from aqt.utils import tooltip

BUTTON_DEFAULTS = {
    "name": "",
    "tooltip": "",
    "prompt_id": "",
    "prompt": "",
    "prompt_version": "latest",
    "model": "",
    "field_map": {},
}

TOP_LEVEL_DEFAULTS = {
    "openai_anki_api_key": "",
    "debug": False,
    "buttons": [],
}

FIELD_PATTERN = re.compile(r"{{(.*?)}}")


def normalize_button(raw):
    button = dict(raw or {})
    for key, value in BUTTON_DEFAULTS.items():
        if key == "field_map":
            field_map = button.get("field_map")
            if not isinstance(field_map, dict):
                button["field_map"] = {}
            else:
                button["field_map"] = {
                    str(response_key): str(field_name)
                    for response_key, field_name in field_map.items()
                }
            continue
        current = button.get(key)
        if current is None:
            button[key] = value
        else:
            button[key] = str(current) if isinstance(value, str) else current
    return button


def normalize_config(raw):
    config = dict(raw or {})
    for key, value in TOP_LEVEL_DEFAULTS.items():
        if key == "buttons":
            buttons = config.get("buttons")
            if not isinstance(buttons, list):
                config["buttons"] = []
            else:
                config["buttons"] = [normalize_button(button) for button in buttons]
            continue
        current = config.get(key)
        if key == "debug":
            config[key] = bool(current) if current is not None else value
        elif current is None:
            config[key] = value
        else:
            config[key] = str(current)

    legacy_key = config.get("openai_api_key")
    if not config.get("openai_anki_api_key") and isinstance(legacy_key, str):
        config["openai_anki_api_key"] = legacy_key
    return config


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
        self.resize(1100, 720)

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
        self.add_button.clicked.connect(self._add_button)
        self.duplicate_button.clicked.connect(self._duplicate_button)
        self.remove_button.clicked.connect(self._remove_button)
        self.move_up_button.clicked.connect(lambda: self._move_button(-1))
        self.move_down_button.clicked.connect(lambda: self._move_button(1))
        button_actions.addWidget(self.add_button, 0, 0)
        button_actions.addWidget(self.duplicate_button, 0, 1)
        button_actions.addWidget(self.remove_button, 1, 0)
        button_actions.addWidget(self.move_up_button, 1, 1)
        button_actions.addWidget(self.move_down_button, 2, 0, 1, 2)
        left_layout.addLayout(button_actions)

        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)

        global_group = QGroupBox("Global Settings")
        global_form = QFormLayout(global_group)
        api_key_row = QWidget()
        api_key_layout = QHBoxLayout(api_key_row)
        api_key_layout.setContentsMargins(0, 0, 0, 0)
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.toggle_api_key_button = QToolButton()
        self.toggle_api_key_button.setText("Show")
        self.toggle_api_key_button.setCheckable(True)
        self.toggle_api_key_button.toggled.connect(self._toggle_api_key_visibility)
        api_key_layout.addWidget(self.api_key_input, 1)
        api_key_layout.addWidget(self.toggle_api_key_button)
        global_form.addRow("API Key", api_key_row)
        helper = QLabel("Optional. If empty, OPENAI_ANKI_API_KEY will be used.")
        helper.setWordWrap(True)
        helper.setStyleSheet("color: palette(mid);")
        global_form.addRow("", helper)
        self.debug_checkbox = QCheckBox("Enable debug logging")
        global_form.addRow("", self.debug_checkbox)
        right_layout.addWidget(global_group)

        details_group = QGroupBox("Button Details")
        details_form = QFormLayout(details_group)
        self.name_input = QLineEdit()
        self.name_input.textChanged.connect(self._on_button_name_changed)
        self.tooltip_input = QLineEdit()
        self.prompt_id_input = QLineEdit()
        self.prompt_input = QPlainTextEdit()
        self.prompt_input.setMinimumHeight(120)
        prompt_helper = QLabel("Supports {{FieldName}} expansion from the current note.")
        prompt_helper.setWordWrap(True)
        prompt_helper.setStyleSheet("color: palette(mid);")
        details_form.addRow("Name", self.name_input)
        details_form.addRow("Tooltip", self.tooltip_input)
        details_form.addRow("Prompt ID", self.prompt_id_input)
        details_form.addRow("Prompt", self.prompt_input)
        details_form.addRow("", prompt_helper)
        right_layout.addWidget(details_group)

        mappings_group = QGroupBox("Field Mappings")
        mappings_layout = QVBoxLayout(mappings_group)
        mapping_header = QLabel(
            "Each row maps one JSON response key from OpenAI to one Anki field."
        )
        mapping_header.setWordWrap(True)
        mapping_header.setStyleSheet("color: palette(windowText);")
        mappings_layout.addWidget(mapping_header)

        mapping_subheader = QLabel(
            "Left: response key returned by OpenAI. Right: Anki field to update."
        )
        mapping_subheader.setWordWrap(True)
        mapping_subheader.setStyleSheet("color: palette(windowText);")
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

        advanced_group = QGroupBox("Advanced")
        advanced_layout = QVBoxLayout(advanced_group)
        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setText("Show Advanced")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        advanced_layout.addWidget(self.advanced_toggle, 0, Qt.AlignmentFlag.AlignLeft)

        self.advanced_content = QWidget()
        advanced_form = QFormLayout(self.advanced_content)
        self.prompt_version_input = QLineEdit()
        self.prompt_version_input.setPlaceholderText("latest")
        self.model_input = QLineEdit()
        advanced_form.addRow("Prompt Version", self.prompt_version_input)
        advanced_form.addRow("Model Override", self.model_input)
        advanced_layout.addWidget(self.advanced_content)
        self.advanced_content.hide()
        right_layout.addWidget(advanced_group)

        right_layout.addStretch(1)
        right_scroll.setWidget(right_container)

        splitter.addWidget(left_panel)
        splitter.addWidget(right_scroll)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 780])

        self.editor_sections = [
            details_group,
            mappings_group,
            advanced_group,
        ]

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self._save)
        button_box.rejected.connect(self.reject)
        root.addWidget(button_box)

    def _toggle_api_key_visibility(self, checked):
        self.api_key_input.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )
        self.toggle_api_key_button.setText("Hide" if checked else "Show")

    def _toggle_advanced(self, checked):
        self.advanced_content.setVisible(checked)
        self.advanced_toggle.setText("Hide Advanced" if checked else "Show Advanced")

    def _set_button_editor_enabled(self, enabled):
        for widget in self.editor_sections:
            widget.setEnabled(enabled)
        self.duplicate_button.setEnabled(enabled)
        self.remove_button.setEnabled(enabled)
        self.move_up_button.setEnabled(enabled and self.current_button_index > 0)
        self.move_down_button.setEnabled(
            enabled and 0 <= self.current_button_index < len(self.working_config["buttons"]) - 1
        )

    def _load_global_fields(self):
        self.api_key_input.setText(self.working_config.get("openai_anki_api_key", ""))
        self.debug_checkbox.setChecked(bool(self.working_config.get("debug")))

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
        self.prompt_id_input.clear()
        self.prompt_input.clear()
        self.prompt_version_input.clear()
        self.model_input.clear()
        self._clear_mapping_rows()

    def _store_current_button(self):
        if self.current_button_index < 0:
            return
        button = self.working_config["buttons"][self.current_button_index]
        button["name"] = self.name_input.text().strip()
        button["tooltip"] = self.tooltip_input.text().strip()
        button["prompt_id"] = self.prompt_id_input.text().strip()
        button["prompt"] = self.prompt_input.toPlainText()
        prompt_version = self.prompt_version_input.text().strip()
        button["prompt_version"] = prompt_version or "latest"
        button["model"] = self.model_input.text().strip()
        button["field_map"] = self._mapping_rows_to_dict()
        self._update_list_item(self.current_button_index)

    def _load_button(self, index):
        if index < 0 or index >= len(self.working_config["buttons"]):
            self._set_button_editor_enabled(False)
            self._clear_button_fields()
            return

        button = self.working_config["buttons"][index]
        self.name_input.setText(button.get("name", ""))
        self.tooltip_input.setText(button.get("tooltip", ""))
        self.prompt_id_input.setText(button.get("prompt_id", ""))
        self.prompt_input.setPlainText(button.get("prompt", ""))
        prompt_version = button.get("prompt_version", "latest")
        self.prompt_version_input.setText("" if prompt_version == "latest" else prompt_version)
        self.model_input.setText(button.get("model", ""))
        self._load_mapping_rows(button.get("field_map", {}))
        self._set_button_editor_enabled(True)

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
        self.working_config["buttons"].insert(self.current_button_index + 1, normalize_button(original))
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
        config = dict(self.working_config)
        config["openai_anki_api_key"] = self.api_key_input.text().strip()
        config["debug"] = self.debug_checkbox.isChecked()
        config["buttons"] = [normalize_button(button) for button in self.working_config["buttons"]]
        return config

    def _validate(self, config):
        blocking = []
        warnings = []
        seen_button_names = {}

        if not config.get("openai_anki_api_key") and not os.environ.get("OPENAI_ANKI_API_KEY"):
            warnings.append(
                "API key is blank and OPENAI_ANKI_API_KEY is not currently set in the environment."
            )

        for index, button in enumerate(config.get("buttons", []), start=1):
            label = f"Button {index}"
            name = button.get("name", "").strip()
            prompt_id = button.get("prompt_id", "").strip()
            field_map = button.get("field_map", {})

            if not name:
                blocking.append(f"{label}: name is required.")
            else:
                seen_button_names.setdefault(name, 0)
                seen_button_names[name] += 1

            if not prompt_id:
                blocking.append(f"{label}: prompt_id is required.")

            seen_response_keys = set()
            duplicate_fields = []
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

            for field_name in set(mapped_targets):
                if mapped_targets.count(field_name) > 1:
                    duplicate_fields.append(field_name)
            if duplicate_fields:
                warnings.append(
                    f"{label}: multiple response keys map to the same Anki field: {', '.join(sorted(duplicate_fields))}."
                )

            prompt = button.get("prompt", "")
            unknown_prompt_fields = sorted(
                {
                    match.group(1).strip()
                    for match in FIELD_PATTERN.finditer(prompt)
                    if match.group(1).strip() and match.group(1).strip() not in self.known_fields
                }
            )
            if unknown_prompt_fields:
                warnings.append(
                    f"{label}: prompt references unknown fields: {', '.join(unknown_prompt_fields)}."
                )

        duplicate_names = sorted(name for name, count in seen_button_names.items() if count > 1)
        if duplicate_names:
            warnings.append(
                f"Duplicate button names found: {', '.join(duplicate_names)}."
            )

        return blocking, warnings

    def _save(self):
        config = self._collect_config()
        blocking, warnings = self._validate(config)

        if blocking:
            QMessageBox.warning(
                self,
                "Fix Configuration Errors",
                "\n".join(blocking),
            )
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

        tooltip("Configuration saved. Reopen editor/browser windows to refresh button lists.", period=5000)
        self.accept()
