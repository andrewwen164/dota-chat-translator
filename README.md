# Personal Dota chat translator — stage 1

Current deliverable: a localhost GSI diagnostic, **not yet a working chat translator**.
Python 3.12 is recommended for the eventual PySide6 desktop application. No
compatibility problem requiring a different GUI framework has been found.
This stage uses only Python's standard library; no Gemini key or API calls.

## Implementation plan and gates

1. **In progress:** establish input access using real Dota payloads. Run the
   receiver below and test distinct team/all-chat markers. Automated fixtures
   check the receiver only. Do not infer chat support from them.
2. After the input decision: implement Google's current official Gemini Python
   SDK, configurable inexpensive model, SQLite cache keyed by text/target/model/
   prompt version, bounded asynchronous work, timeouts/rate limits/capped retries,
   response validation and original-text fallback. Secrets come from the
   environment or ignored `.env`; metadata-only metrics by default. Treat every
   message as untrusted translation data, preserve Dota language/tone/profanity,
   and skip identifiable English and chat-wheel messages.
3. Check a normal PySide6 message window first, then a non-focusing, transparent,
   click-through overlay with unlock/move/resize, font/opacity settings, tray,
   hide/show shortcut and clear connection/queue/API status.
4. Check English-to-target translation and copy in an app text box first. Then
   consider an opt-in hotkey with foreground-Dota checks and duplicate guards.
   If the current team/all channel cannot be verified, require manual pasting;
   never guess the channel or synthesize identities.
5. Provide labeled offline sample chat, focused cache/API/parser/duplicate tests,
   Windows setup and a verified PyInstaller command after the app works.

The input gate is deliberate. No OCR, memory access, injection, traffic
interception, game-binary changes, input automation, or hosted service is used.

## Evidence so far (2026-10-18)

- Reviewed the [reference repository](https://github.com/sc0rebreaker/dota-translator-releases).
  Its published web assets are not implementation evidence for GSI chat.
- Valve's [March 11, 2022 patch note](https://www.dota2.com/newsentry/4491783379124370818?l=ukrainian)
  states that GSI requires `-gamestateintegration` and may affect frame performance.
  This is a primary source for enabling GSI, not a payload schema.
- The [Valve Developer Community GSI page](https://developer.valvesoftware.com/wiki/Counter-Strike:_Global_Offensive_Game_State_Integration)
  returned HTTP 403 in this research environment. It concerns Counter-Strike;
  it cannot establish a Dota chat schema. No authoritative current Dota chat
  field specification was located.
- Inspected installed configuration files under
  `C:\Program Files (x86)\Steam\steamapps\common\dota 2 beta\game\dota\cfg\gamestate_integration`.
  Existing integrations request components including provider/map/player/hero/
  abilities/items/events. They do not request chat. These configs establish
  local setup conventions, **not the contents of actual emitted payloads**.
  Existing files have not been changed or copied into this project.
- [First-person GSI setup reports in Valve's issue tracker](https://github.com/ValveSoftware/Dota-2/issues/2333)
  provide a broader component list and show setup can fail. Reports are not an
  official schema or evidence that this machine receives chat.
- **Actual Dota payloads received/inspected: none yet. Team chat: unverified.
  All chat: unverified.** No undocumented `chat` field or configuration flag is
  invented. An absent marker is only evidence about the tested configuration,
  build, match type and time window; it is not proof of universal absence.

## Windows PowerShell: run stage 1

Move/copy this folder to a durable writable project location if desired. It was
created under `%TEMP%` because this session could not write directly in the
provided home workspace. Temporary files can be cleaned by Windows.

With Python 3.12 installed:

```powershell
Set-Location "$env:TEMP\dota-chat-translator"
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe diagnostic.py --prepare
```

On this machine, Python 3.12 is already managed by uv. If `py` is unavailable:

```powershell
uv venv --python 3.12 .venv
.\.venv\Scripts\python.exe diagnostic.py --prepare
```

`--prepare` creates an ignored `.local` receiver token and config. Do not share
either file. This is unrelated to the Gemini API key. No Dota settings change.

Close Dota before installing. To install only this application's GSI config:

```powershell
.\.venv\Scripts\python.exe diagnostic.py --install 'C:\Program Files (x86)\Steam\steamapps\common\dota 2 beta'
```

The installer validates `game/dota/cfg`, leaves other apps' configs alone, and
backs up any previous file with this app's exact filename to a timestamped
`.bak` in that directory **before** replacement. It stops on permission/backup
failure; administrator access is not assumed. If Windows denies access, do not
change ACLs automatically; install in a user-writable Steam library or resolve
the single-file permission locally. Keep any `.bak` private: it can contain the
old receiver token. Restoring a backup or deleting only the newly added app config
reverses installation. Restart Dota after configuration changes.

In Steam > Dota 2 > Properties > General > Launch Options, first record the exact
existing options locally as a backup, then append `-gamestateintegration` if
absent. Preserve all existing options. This program never changes Steam options.

Start the receiver **before launching Dota**:

```powershell
.\.venv\Scripts\python.exe diagnostic.py --team-marker 'D2TEAM_7319' --all-marker 'D2ALL_8426'
```

It binds only `127.0.0.1:3009`, authenticates posts, limits request size/nesting,
and uses a bounded serial HTTP receiver with read deadlines. It never sends
data externally. Use distinct markers for each new session; avoid putting a
secret in the marker. If choosing another port, use the same `--port` for both
`--prepare` and the receiver, then reinstall the regenerated config.

## Real-session verification checklist

1. Use a private lobby with a consenting friend so you can exercise both channels.
   Record Dota build, match type, receiver command (without secrets), and times.
2. Confirm `received=` increases during play. Zero posts means the GSI connection
   is unverified, **not** that chat is absent. Check launch option, config path,
   restart, port conflict, token/config consistency, and application firewall.
   Do not open a LAN firewall rule for this loopback-only receiver.
3. Send exactly `D2TEAM_7319` to **team** and `D2ALL_8426` to **all** using Dota's
   own UI. Confirm each is visible in the intended channel. Have the friend send
   markers too: incoming and own-message visibility can differ. Note which
   participant/channel sent each phrase. Do not assume a successful own-message
   test establishes incoming chat.
4. Keep the receiver running through several state updates after each message.
   A marker hit means an exact substring was found in a JSON **string value**
   anywhere outside the root auth object. This does not assume any field names.
   Inspecting the full schema and attributing player/channel will require a
   follow-up controlled local payload inspection if hits occur. No identities
   or channels are inferred by this diagnostic.
5. Ctrl+C saves `.local/evidence-report.json`. It contains counts, presence counts
   for known configured components (such as map/player), UTC receipt
   time and redacted structural paths. No chat text, marker text, player names,
   IDs, payload values or auth tokens are saved. The receiver holds only a
   digest/counters after each post, not raw payloads. HTTP origin cannot prove
   the sending process is Dota: correlate with your own observed game session.
6. Share the metadata report and observations, not the token/config or `.env`.
   Mark both channel results separately. Do not call HTTP tests live verification.

If game state arrives but neither incoming marker appears, GSI is not a usable
chat feed in that tested setup. The practical proposed alternative is **local
OCR of a user-selected visible chat region**, using offline Russian, Spanish,
Chinese and English recognition. Only extracted message text would go to Gemini;
screenshots stay local. OCR can miss fading/wrapped lines and misread identities
or channels, so it needs line matching, bounded duplicate suppression and a local
visual check. This approach has **not** been selected or implemented; it requires
the user's decision, and outgoing chat would still use manual paste unless the
channel can be determined reliably.

## Automated checks

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

These tests use explicitly synthetic arbitrary JSON to exercise malformed input,
auth, localhost binding, marker scanning, duplicate counts, Unicode, privacy of
reports, and backup-before-replacement. They do not test Dota integration,
Gemini, PySide6, an overlay or outgoing input. No paid API is called.

Dependencies for stage 1: Python standard library only. `pyproject.toml` reserves
an optional PySide6 dependency for the desktop stage. `.env.example` is a
placeholder for stage 2; do not paste a Gemini key into commands, issues, or logs.
Validation in this environment: 18 unittest cases passed on Python 3.12.15;
`--prepare`, `--help` and byte compilation also checked. Only synthetic HTTP
requests were used. No real Dota match, payload, chat feed or GUI was tested.

The demo UI, translation tests and PyInstaller packaging command are intentionally
pending their implementation stages; a functioning desktop app is not claimed.
