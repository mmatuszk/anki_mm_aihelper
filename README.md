# OpenAI Card Updater (Anki Add-on)

Use provider-driven prompt buttons to update Anki note fields from the editor.

## Features
- Editor toolbar buttons configured through a custom dialog.
- OpenAI support with two modes:
  - `saved_prompt`: saved prompt ID + local user prompt
  - `manual`: system prompt + user prompt
- Schema designed to support future providers such as DeepSeek, Gemini, and Claude.
- Field expansion with `{{FieldName}}` in `system_prompt` and `user_prompt`.
- Field mapping from JSON response keys to Anki fields.
- Bulk update from the Browser for selected notes.
- Configurable request timeout.
- Manual retry for transient single-note failures.
- Automatic retry for transient bulk failures.
- About menu entry showing the installed add-on version.
- Button import/export and full-config import/export.

## Requirements
- Anki 25.09.2 (Python 3.13)
- OpenAI API key in config or `OPENAI_ANKI_API_KEY`

## Install (symlink)
1. In Anki: Tools -> Add-ons -> View Files
2. Create a symlink from your repo to `addons21`:

```bash
ln -s "/Users/marcin/Documents/prg/anki_mm_aihelper" "/Users/marcin/Library/Application Support/Anki2/addons21/anki_mm_aihelper"
```

3. Restart Anki.

## Configuration
Open:
- `Tools -> OpenAI Card Updater -> Configure...`

The config dialog supports:
- Global settings:
  - OpenAI API key
  - debug logging
  - request timeout
- Button management:
  - add
  - duplicate
  - remove
  - reorder
  - import
  - export
- Global import/export:
  - import all
  - export all

### Current provider support
Only OpenAI is implemented in `0.4.0`, but the button schema is now provider-based so future providers can be added without another config redesign.

### Button model
Each button now uses:
- `provider`
- `mode`
- `model`
- `saved_prompt_id`
- `saved_prompt_version`
- `system_prompt`
- `user_prompt`
- `field_map`

Mode behavior:
- `saved_prompt`
  - uses `saved_prompt_id`
  - sends local `user_prompt`
  - `model` is optional
- `manual`
  - sends `system_prompt` + `user_prompt`
  - requires `model`

### Example `config.json`
```json
{
  "providers": {
    "openai_api_key": ""
  },
  "debug": true,
  "request_timeout_seconds": 90,
  "buttons": [
    {
      "name": "Vocabulary",
      "tooltip": "AI Chinese Vocabulary Update",
      "provider": "openai",
      "mode": "saved_prompt",
      "model": "",
      "saved_prompt_id": "pmpt_...",
      "saved_prompt_version": "latest",
      "system_prompt": "",
      "user_prompt": "{{Hanzi}}",
      "field_map": {
        "translation": "English (GT)",
        "notes": "Notes"
      }
    },
    {
      "name": "Manual Example",
      "tooltip": "Manual OpenAI prompt",
      "provider": "openai",
      "mode": "manual",
      "model": "gpt-4.1-mini",
      "saved_prompt_id": "",
      "saved_prompt_version": "latest",
      "system_prompt": "You are a Chinese teacher.",
      "user_prompt": "Explain {{Hanzi}} and return JSON.",
      "field_map": {
        "notes": "Notes"
      }
    }
  ]
}
```

### Response JSON format
Provider responses must be valid JSON and include:

```json
{
  "success": true
}
```

Additional keys can be mapped to Anki fields via `field_map`.

If `success` is `false`, the add-on shows `error` or `message` from the response.

## Import / Export
Supported from the config dialog:
- Export one button
- Import one button
- Export all config
- Import all config

Behavior:
- Exported JSON includes a `schema_version`
- API keys are not exported
- Global import ignores API keys
- Global import asks whether to merge or replace
- Duplicate imported button names are renamed:
  - `CV (Imported)`
  - `CV (Imported 2)`

## Retry and timeout behavior
- `request_timeout_seconds` controls the request timeout
- Single-note requests:
  - show one manual retry option for transient failures
- Bulk requests:
  - retry transient failures once automatically
- Retryable failures include:
  - timeout
  - network error
  - HTTP `429`, `500`, `502`, `503`, `504`

## Notes
- `saved_prompt_version = "latest"` omits the version field in the OpenAI request.
- The add-on ensures the request context mentions JSON.
- When `debug` is enabled, request/response details and retry logs are written to the console.
