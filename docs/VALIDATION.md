# Validation record

Windows 11; Python 3.12.15; PySide6 6.12.0; google-genai 2.31.0; Lingua 2.2.0;
python-dotenv 1.2.4; PyInstaller 6.22.3. Date: 2026-10-18.

## User-observed live evidence

The user ran the diagnostic in a Dota game, sent both markers themselves, and
shared metadata: 745 payloads and 48 observations of each marker, with game-state
components present. No raw payload or matched field path has been inspected.
Other players' messages and channel metadata are not verified. The user authorized
continuing assuming GSI is usable. This does not make synthetic fixtures live proof.

## Development checks

- 66 tests cover diagnostics, authentication, localhost binding, backups and marker
  privacy; cache persistence/dimensions/pruning; duplicate snapshots and queue
  overflow; malformed input; API errors, retries, rate limits and timeouts;
  response parsing; configurable mappings and missing identities; clipboard guards,
  safe worker cancellation, English skipping and settings backup failures.
  Console SIGINT tests verify deferred shutdown, repeated interrupts and restoration
  of the original handler, without raising KeyboardInterrupt inside Qt callbacks.
- The installed official SDK was tested through in-memory HTTP transport for
  request serialization, structured responses, blocked results and HTTP 429.
  No external API request or paid translation was made.
- A real Qt event loop rendered four demo rows; outgoing demo translation and
  clipboard copy worked, with stale copy disabled after editing.
- Overlay creation, input/focus flags, locking and text were checked offscreen.
  Normal-window output was visually inspected with Windows fonts. Offscreen checks
  do not prove mouse passthrough or keyboard-focus behavior over a live game.
- The PyInstaller Windows build completed and its EXE passed an offline startup/render
  smoke check. No `.env` or receiver token files were bundled. This does not verify
  live Gemini or Dota in the package.

## Local checks still needed

- Select actual chat fields; verify other players' team/all messages, channel
  values, identities, repeats and match transitions.
- Use your Gemini key to verify model availability/quota, translation quality,
  Dota terminology/tone/profanity, English skipping and live failure handling.
- Test overlay visuals/click-through/focus, monitor/DPI behavior, dragging/resizing,
  tray restore and shortcut conflicts over actual borderless/windowed Dota.
- Test opt-in clipboard translation in foreground Dota, changing clipboard/focus
  in flight and manually pasting into the intended channel. No automatic send exists.
- Verify the packaged build locally before relying on it during play.
