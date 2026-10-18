# Dota Chat

Personal Windows desktop translator using Python, PySide6 and your own Gemini key.
No accounts, subscriptions, hosted backend, auto-updater, memory access, injection,
game-traffic interception or game-binary changes.

**Status:** desktop app, offline demo, translation pipeline, configurable GSI input,
overlay and outgoing manual-paste workflow implemented. The user observed their
own team/all test strings in live GSI payloads. Exact chat fields and other players'
incoming messages remain unverified. Development proceeds under the user's requested
assumption that GSI is usable; the app requires selection of the actual chat field
instead of inventing one. No OCR fallback has been substituted.

## Run the demo now

On this machine, dependencies are already installed:

```powershell
cd "$env:TEMP\dota-chat-translator"
.\.venv\Scripts\python.exe app.py --demo
```

OFFLINE DEMO uses labeled Russian, Spanish and Chinese samples with fixed
translations. No Gemini client, GSI receiver or API credits are used. The outgoing
demo supports **Push mid after Roshan** into Russian, Spanish or Chinese. Other
demo input deliberately falls back to the original. Demo cache is separate.

## Fresh Windows setup

Use a durable user-writable folder; Windows may clean `%TEMP%`.
With Python 3.12 (64-bit) and uv:

```powershell
git clone https://github.com/andrewwen164/dota-chat-translator.git
cd dota-chat-translator
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
```

Or use `py -3.12 -m venv .venv`, then
`.\.venv\Scripts\python.exe -m pip install -r requirements.txt`.
Reuse an existing `.venv`; do not clear it. Administrator access is not required.
`requirements-tested.txt` lists the exact direct dependency versions used locally.

## Use your Gemini key

```powershell
Copy-Item .env.example .env
notepad .env
```

Fill in your key locally, save, then run:

```powershell
.\.venv\Scripts\python.exe app.py
```

Environment variables override `.env`. Never share or commit your key. The key is
never displayed in Settings, logged or included in packaging. The default model is
`gemini-3.5-flash-lite`, listed as cost-effective in Google's
[model documentation](https://ai.google.dev/gemini-api/docs/models). Change it in
Settings and restart, or set `GEMINI_MODEL` in `.env`/environment (takes precedence
over Settings). Model availability, quota and cost depend on your Google project.
No paid API request was made during development.

Google's official [`google-genai` SDK](https://googleapis.github.io/python-genai/)
uses async Generate Content with structured JSON output and no tools. Chat is
untrusted translation data, not instructions. The system prompt preserves Dota
names, abbreviations, tone and profanity. Blocked, malformed, truncated or failed
responses show the original message; the model's language quality needs local
verification. Local English detection is conservative; ASCII Spanish is not
assumed to be English. Explicitly mapped chat-wheel flags are skipped.

## Connect Dota

**Stop the diagnostic receiver before launching the desktop app:** both use port
3009. Reuse your existing stage 1 config and `.local/receiver-token.txt`; no config
reinstall is needed on the same port. If you move the project, move `.local`
privately too, or generate/install a new matching config.

For a fresh setup, close Dota and run:

```powershell
.\.venv\Scripts\python.exe diagnostic.py --prepare
.\.venv\Scripts\python.exe diagnostic.py --install 'C:\Program Files (x86)\Steam\steamapps\common\dota 2 beta'
```

Back up your existing Steam launch options, append `-gamestateintegration` if
absent, then restart Dota. The installer backs up any previous app-owned config
before replacing it, leaves other integrations alone, and stops on permission or
backup failure. It never changes Steam options or elevates privileges.
[Stage 1 research and diagnostic guide](docs/STAGE1.md) contains the evidence and
verification procedure.

When status reads **GSI receiving**, send a recognizable message and click
**Inspect GSI chat field**. Select the actual string field containing your chat.
This local preview stays in memory and excludes auth. Selecting the field saves
the mapping and enables capture. Other optional fields must be mapped explicitly:
no sender, hero or team/all channel is inferred.

Settings paths are JSON arrays. Records selects message records from the payload;
the other paths are relative to each record. `"*"` traverses array/object values.
For a **synthetic example only**, records `["example", "*"]` and text `["body"]`
read bodies from that collection. This is not a claimed Dota schema. Leave unknown
identity/channel paths `[]`. Chatwheel skips only a mapped JSON boolean `true`.
Direct arrays of strings currently need a custom adapter; the picker handles
message string fields in objects.

The authenticated receiver binds only **127.0.0.1**. Port changes must match the
generated config and require restarting the app and Dota. A connected receiver
alone does not verify incoming chat.

## Overlay and tray

- Incoming shows original/English text, supplied identity when mapped, and status.
  You can also paste a message manually.
- **Show overlay** enables a transparent, always-on-top overlay for borderless or
  windowed Dota. It starts locked and click-through, without keyboard focus.
- **Ctrl+Alt+T** shows/hides the overlay; **Ctrl+Alt+L** locks/unlocks it. If shortcuts
  are already taken, use the buttons or tray menu.
- Unlock to drag the header or resize the corner; lock again for gameplay.
  Adjust opacity/font in Settings and Save. Position is saved on Save or Quit.
- Closing the main window hides it to the tray when a tray is available. Use
  **Show app** or **Quit** in the tray. Showing the overlay never activates the
  main window. Exclusive fullscreen is not supported.

## Outgoing translation

Enter English in Outgoing, choose Russian/Spanish/Chinese, translate, then click
**Copy result**. Choose team/all chat in Dota yourself, then paste and send manually.
Failed translations show the original and do not enable copying as a success.

The optional clipboard hotkey is **off by default**. Enable it in Settings and
Save; choose the target in Outgoing before returning to Dota:

1. Open the intended team/all chat and type English in Dota yourself.
2. Select/copy your text using Dota's normal controls.
3. Explicitly press **Ctrl+Alt+Y** while `dota2.exe` is foreground.
4. Once translation is copied, paste it yourself into the selected channel and
   send manually. The app never presses keys, pastes or sends on your behalf.

Keep the overlay visible to see "Translating clipboard" and "Outgoing copied"
status without opening or focusing the main app.

If focus or clipboard changes while translating, the clipboard stays untouched
and the result remains in the app. Duplicate triggers are suppressed. Clipboard
formats at trigger time are restored after 30 seconds if unchanged; contents from
before **you** copied from Dota cannot be recovered. The app cannot reliably detect
the active team/all channel, so automatic sending is unavailable. RegisterHotKey
and public foreground-window metadata APIs are used; no keyboard hooks or input
injection, memory reads or administrator access are involved.

## Responsiveness and local data

SDK calls, SQLite, language detection, retries and rate-limit waits run on a
background worker with an asyncio loop. The GUI makes no API requests. Bounds:
64 jobs, two latest GSI snapshots, 20 requests/minute by default, two attempts,
10-second SDK and 12-second outer timeout per attempt. SDK retries are disabled
so application caps remain effective. Queue overflow shows the original text.

SQLite caches successful translations using a hash of exact source text, target,
model and prompt version, with 10,000-entry LRU pruning. Translated text is stored
locally and is not encrypted. Settings provides a cache-clear button. Repeated
snapshots use mapped event IDs plus supplied identity/channel/text, when available.
Without an ID, identical text/identity/channel is suppressed while present and
for 120 seconds after its last observation; this can suppress genuine repeated
messages. Map a verified event ID if available.

Ignored `.local` holds receiver token/config, settings/backup, caches, diagnostics
and `metrics.json`. Metrics contain counts, queue depth and latency, not chat text
or keys. Raw snapshots and field previews are not saved. Never upload `.local`,
`.env`, configuration backups or raw captures to GitHub.

## Check and package

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe app.py --smoke-test
```

The smoke test renders an offline window and exits. Preview PNGs stay ignored in
`.local`. See [validation details](docs/VALIDATION.md) for real versus synthetic
checks and remaining local verification.

After confirming the source app works locally:

```powershell
uv pip install --python .venv\Scripts\python.exe pyinstaller
$packageRoot = Join-Path (Get-Location) ("dist\build-" + (Get-Date -Format yyyyMMdd-HHmmss))
.\.venv\Scripts\python.exe -m PyInstaller --onedir --windowed --distpath $packageRoot --name DotaChat --collect-all lingua --collect-all google.genai app.py
& "$packageRoot\DotaChat\DotaChat.exe" --demo
```

Each build uses a fresh timestamped folder to preserve earlier builds and their
local configuration. Keep the **entire DotaChat folder**,
including `_internal`. For real use, place your private `.env` and matching `.local`
beside the EXE. Never bundle secrets using `--add-data`. The package is unsigned,
has no installer, auto-start, auto-updater or administrator requirement.
