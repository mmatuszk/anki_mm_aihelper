# OpenAI Card Updater (Anki Add-on)

Use OpenAI prompts to update Anki note fields from the editor.

## Features
- Editor toolbar buttons configured via JSON.
- Prompt ID + optional version + optional model override.
- Expands `{{FieldName}}` in the user prompt from the current note.
- Maps JSON response keys to Anki fields.
- Cancel button for bulk OpenAI requests.
- About menu entry showing the installed add-on version.
- Configurable OpenAI request timeout, manual retry for single-note requests, and automatic retry for bulk transient failures.
- Debug logging when enabled.

## Requirements
- Anki 25.09.2 (Python 3.13)
- OpenAI API key in config or `OPENAI_ANKI_API_KEY` environment variable.

## Install (symlink)
1) In Anki: Tools → Add-ons → View Files.
2) Create a symlink from your repo to `addons21`:

```bash
ln -s "/Users/marcin/Documents/prg/anki_mm_aihelper" "/Users/marcin/Library/Application Support/Anki2/addons21/anki_mm_aihelper"
```

3) Restart Anki.

## Configuration
Edit the add-on config via **OpenAI Card Updater → Configure…**.

The add-on provides a dedicated configuration dialog for global settings, button definitions, and response-field mappings. Changes are saved explicitly with `Save`, and editor/browser windows may need to be reopened for button list changes to appear.

### Config UI
- Global settings: `openai_anki_api_key`, `debug`, and `request_timeout_seconds`
- Button management: add, duplicate, remove, reorder
- Button fields: `name`, `tooltip`, `prompt_id`, `prompt`
- Field mappings: one row per JSON response key to Anki field mapping
- Advanced fields: optional `prompt_version` and `model`

Validation in the dialog:
- Blocks save for blank button names, blank prompt IDs, incomplete mapping rows, and duplicate response keys
- Warns for unknown Anki field names, unknown `{{FieldName}}` prompt references, duplicate button names, and missing API key/env var

Example `config.json`:
```json
{
  "openai_anki_api_key": "",
  "debug": true,
  "request_timeout_seconds": 90,
  "buttons": [
    {
      "name": "Update Vocabulary",
      "tooltip": "Call OpenAI to update this note",
      "prompt_id": "pmpt_...",
      "prompt": "{{Hanzi}}",
      "prompt_version": "latest",
      "model": "",
      "field_map": {
        "translation": "English (GT)",
        "notes": "Notes",
        "example_hanzi": "Example",
        "example_pinyin": "Example_Pinyin",
        "example_translation": "Example_Translation"
      }
    },
    {
      "name": "M2",
      "tooltip": "AI Chinese Grammar Update",
      "prompt_id": "pmpt_...",
      "prompt": "{{Hanzi}}",
      "prompt_version": "latest",
      "model": "",
      "field_map": {
        "english_translation": "English (GT)",
        "notes": "Notes",
        "pinyin": "Pinyin"
      }
    }
  ]
}
```

### Response JSON format
OpenAI must return valid JSON with a `success` boolean:
```json
{
  "success": true,
  "translation": "...",
  "notes": "...",
  "example_hanzi": "...",
  "example_pinyin": "...",
  "example_translation": "..."
}
```

If `success` is `false`, the add-on shows `error` or `message` from the response.

## Planned Refactor
The next major config/schema change is planned to remove the current OpenAI-only `prompt_id`-centric design in favor of a provider-based button model. Backward compatibility is not a goal for that refactor.

Planned button model:
- `provider`: for example `openai` or `deepseek`
- `mode`: `saved_prompt` or `manual`
- `model`
- `saved_prompt_id`
- `saved_prompt_version`
- `system_prompt`
- `user_prompt`
- `field_map`

Planned behavior:
- OpenAI `saved_prompt` mode: use `saved_prompt_id` plus local `user_prompt`
- OpenAI `manual` mode: send `system_prompt` plus `user_prompt`
- DeepSeek `manual` mode: send `system_prompt` plus `user_prompt`
- `{{FieldName}}` expansion in both `system_prompt` and `user_prompt`

Planned provider config:
- top-level `providers` block instead of a single provider-specific key
- separate credentials for providers such as OpenAI and DeepSeek

Planned import/export:
- export/import for a single button
- export/import for the full config
- JSON export format with explicit `schema_version`
- API keys excluded from export by default
- import merges into the current config instead of replacing it
- duplicate imported button names will be renamed, for example `CV (Imported)` then `CV (Imported 2)`

Planned UI changes:
- provider selector per button
- mode selector per button
- conditional fields based on provider + mode
- button-level `Import` / `Export`
- global `Import All` / `Export All`

## Usage
1) Open a card in the editor.
2) Click the configured button.
3) The add-on updates mapped fields when the response is successful.

## Notes
- If `prompt_version` is `"latest"`, the add-on omits the version field and OpenAI uses the latest prompt version.
- The prompt text is forced to mention JSON if it doesn’t already.
- Single-note requests offer one manual retry for transient failures like timeouts, network errors, and HTTP 429/5xx responses.
- Bulk requests automatically retry transient failures once with a short delay.
- When `debug` is enabled, request/response details are logged to the console.
