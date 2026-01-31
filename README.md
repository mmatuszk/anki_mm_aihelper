# OpenAI Card Updater (Anki Add-on)

Use OpenAI prompts to update Anki note fields from the editor.

## Features
- Editor toolbar buttons configured via JSON.
- Prompt ID + optional version + optional model override.
- Expands `{{FieldName}}` in the user prompt from the current note.
- Maps JSON response keys to Anki fields.
- Debug logging when enabled.

## Requirements
- Anki 25.09.2 (Python 3.13)
- OpenAI API key in config or `OPENAI_API_KEY` environment variable.

## Install (symlink)
1) In Anki: Tools → Add-ons → View Files.
2) Create a symlink from your repo to `addons21`:

```bash
ln -s "/Users/marcin/Documents/prg/anki_mm_aihelper" "/Users/marcin/Library/Application Support/Anki2/addons21/anki_mm_aihelper"
```

3) Restart Anki.

## Configuration
Edit the add-on config via **OpenAI Card Updater → Configure…**.

Example `config.json`:
```json
{
  "openai_api_key": "",
  "debug": true,
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

## Usage
1) Open a card in the editor.
2) Click the configured button.
3) The add-on updates mapped fields when the response is successful.

## Notes
- If `prompt_version` is `"latest"`, the add-on omits the version field and OpenAI uses the latest prompt version.
- The prompt text is forced to mention JSON if it doesn’t already.
- When `debug` is enabled, request/response details are logged to the console.
