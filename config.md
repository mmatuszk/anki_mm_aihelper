OpenAI Card Updater configuration

openai_api_key:
- Optional. If empty, the add-on will use the OPENAI_API_KEY environment variable.

debug:
- true/false. When enabled, logs prompts, errors, and response payloads to the console.

buttons:
- List of button definitions. Each button is added to the card editor.

button fields:
- name: Button label in the editor.
- tooltip: Hover tooltip.
- prompt_id: OpenAI prompt id to use.
- prompt: User input string sent to OpenAI. Supports {{FieldName}} expansion from the current note.
- prompt_version: Optional prompt version string. Defaults to "latest" (the add-on omits the version field in this case).
- model: Optional model override. Leave empty to use the model stored in the prompt.
- field_map: Mapping of JSON response keys to Anki field names.

Response JSON requirements:
- The response must be valid JSON.
- It must include a boolean field named "success".
- If success is false, the add-on will display the "error" or "message" field if present.

Note:
- OpenAI JSON mode requires the word "JSON" to appear in the prompt context. If it is missing from your prompt text, the add-on appends "Return output as JSON."
- The add-on sends your prompt_id to OpenAI as prompt.id and retries with prompt.prompt_id if the API rejects prompt.id.
