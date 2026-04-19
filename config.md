OpenAI Card Updater configuration

The add-on edits this configuration through the custom dialog in:
Tools -> OpenAI Card Updater -> Configure...

Top-level fields:

providers:
- Provider credentials.
- Current supported field:
  - openai_api_key: Optional. If empty, the add-on uses OPENAI_ANKI_API_KEY.

debug:
- true/false. When enabled, logs requests, responses, retries, and errors to the console.

request_timeout_seconds:
- Integer timeout for each provider request. Defaults to 90 seconds.

buttons:
- List of button definitions.
- Buttons are global and appear in the editor toolbar and browser bulk menu.

Button fields:
- name: Button label in the editor/browser.
- tooltip: Hover tooltip.
- provider: Current supported value is "openai".
- mode:
  - "saved_prompt": Use an OpenAI saved prompt ID plus a local user prompt.
  - "manual": Send system prompt + user prompt directly. Requires model.
- model:
  - Optional in saved_prompt mode.
  - Required in manual mode.
- saved_prompt_id: Used only in saved_prompt mode.
- saved_prompt_version: Optional in saved_prompt mode. Defaults to "latest".
- system_prompt: Used in manual mode. Supports {{FieldName}} expansion.
- user_prompt: Supports {{FieldName}} expansion.
- field_map: Mapping of JSON response keys to Anki field names.

Response JSON requirements:
- The response must be valid JSON.
- It must include a boolean field named "success".
- If success is false, the add-on will display the "error" or "message" field if present.

Retry behavior:
- Single-note requests offer one manual retry for transient failures like timeouts, network errors, and HTTP 429/5xx responses.
- Bulk requests automatically retry transient failures once with a short delay.

Import/export:
- Button export/import is supported from the config dialog.
- Global export/import is supported from the config dialog.
- Exported files do not include API keys.
- Global import ignores API keys and asks whether to merge or replace.
- Duplicate imported button names are renamed with an "(Imported)" suffix.
