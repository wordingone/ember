# Ad hoc receipt: plain-chat input race (referenced by BROKEN #8 / VERIFIED-LIVE #11)

Three follow-up probes run against `ember-cockpit-195.exe` at 213x35 after the main 21-step drive
pass showed step 21/22 (a plain, non-slash chat message) producing zero visible effect.

## Test 1 — character-by-character typing (control, succeeds)

Wrote `h`, then `i` as two separate `write()` calls 150ms apart, waited, then wrote `\r` as its own
call 500ms later.

Capture immediately before Enter (input row only):
```
❯ hi
```

Capture ~1.5s after Enter (transcript rows):
```
You
hi
```
(followed by a spinner glyph a moment later) — the message round-tripped correctly.

## Test 2 — full line + Enter in ONE write() call (fails silently)

Wrote `"Reply with exactly the single word: PONG\r"` as a single `ptyProcess.write()` call.

Capture ~800ms and ~1.5s after: no new transcript row, no spinner, no error, input row shows empty
`❯ ` — as if nothing was ever typed or submitted. Reproduced twice (main drive-pass step 21/22, and
independently below).

## Test 3 — full line and Enter as TWO separate write() calls (succeeds — isolates the cause)

Wrote `"Reply with exactly the single word: PONG"` (no trailing `\r`) as one call, waited 600ms,
confirmed it appeared correctly in the input row:
```
❯ Reply with exactly the single word: PONG
```
then wrote `\r` alone as a second call. ~1.5s later:
```
You
Reply with exactly the single word: PONG
```
— submitted correctly.

## Conclusion

The failure is specific to delivering the full text **and** the Enter keypress within the same
synchronous input burst — not to message length, word count, or the presence of spaces (multi-word
slash commands like `/finetune start` and `/model unload`, sent as single-burst writes throughout
the main drive pass, worked correctly). Splitting the burst so Enter arrives as its own event
avoids the bug entirely. This is consistent with a stale-closure race in the keyboard input hook
(the Enter handler reading an input-state value captured before the preceding characters' state
updates had committed) rather than anything specific to slash-command parsing.
