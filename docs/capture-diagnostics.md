# Capture diagnostics

Running the exporter with `--debug` writes two sidecars in the export directory:

1. A privacy-safe diagnostics report (`Capture_*.diagnostics.json`) explaining parser and matcher decisions.
2. A sanitized UDP payload file (`Capture_*.payloads.json`) suitable for offline decoder replay and debugging.

Both files are also written even if no history page could be exported.

---

## Diagnostics report (`Capture_*.diagnostics.json`)

This sidecar explains what the capture pipeline recognized, rejected, and paired without changing the public export format or record order.

The report contains bounded events, aggregate counters, reason codes, packet positions, payload lengths, history kinds, page numbers, and record counts. It does **not** contain packet payloads, IP addresses, ports, packet timestamps, or user UIDs. The report format is versioned independently as `nte-capture-diagnostics` version 1.

### Useful rejection codes

- `RESPONSE_TOO_SHORT`: a matching inbound packet could not contain a history response;
- `NO_HISTORY_MARKER`: a matching response candidate had no known history marker;
- `HISTORY_MARKER_PARSE_FAILED`: a known marker was present but neither decoder produced records;
- `RESPONSE_KIND_MISMATCH`: decoded data did not match the pending history kind;
- `REQUEST_REPLACED`: a recovery request superseded an unanswered request.

Events are capped at 200 per session. Aggregate counters continue after that limit and `events_omitted` records how many event entries were left out.

---

## Sanitized replay payloads (`Capture_*.payloads.json`)

When running with `--debug`, the exporter records all observed UDP game packets into a sanitized JSON capture file (format `nte-udp-payload-capture` version 1). This enables developers and researchers to reproduce decoding issues offline without running the game client.

### Sanitization rules

To preserve full byte-level replayability while protecting private information, the following scrubs are applied automatically:

- **Local host IP:** mapped to the RFC 5737 documentation address `192.0.2.1`.
- **Remote game servers:** mapped sequentially to `198.51.100.x`.
- **Ports:** mapped consistently per stream (`50000+` for client, `40000+` for server).
- **User UIDs:** all occurrences of the user's account UID (both as a 64-bit little-endian integer and as an ASCII string) are scrubbed to dummy UID `100000000000`.
- **Timestamps:** normalized relative to the start of the capture session (`0.000000s`).
- **Protocols:** restricted to UDP history streams; TCP connection segments (such as login handshakes) are omitted.

### Offline replay and debugging tools

The repository includes standalone tools under `tools/` for working with payload captures:

#### Capturing standalone payload recordings

```powershell
python tools/capture_payloads.py [--out exports/capture.json] [--capture-backend auto|libpcap|raw]
```

Captures live UDP game traffic directly to a sanitized replay JSON file without generating tracker exports.

#### Replaying payload captures offline

```powershell
python tools/replay_payloads.py [exports/Capture_*.payloads.json] [--debug]
```

Replays the captured UDP packets through [`LiveHistorySession`](/src/nte_history_exporter/live_capture/session.py) and the decoders, verifying parser outputs and writing exports or research CSVs offline.
