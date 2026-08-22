# FinVerify — Demo-Day Runbook

Operations only. For the 4-minute narrative and rehearsed Q&A, see
[docs/PITCH.md](PITCH.md) — do not improvise script content from this file.

Venue: `___`  Slot time: `___`  Backup laptop owner: `___`

## Roles

- **Driver** (types/clicks): `___`
- **Narrator** (talks the pipeline): `___`
- **Clock** (elapsed time, signals 3:00/3:45, reads the pre-stage
  DEMO_FALLBACK check out loud): `___`
- **Judge questions** (defers to Narrator on scoring): `___`
- **DEMO_FALLBACK owner — Member 4** (only one who may touch it): `___`

## T-minus checklist

### Night before

```bash
cd /Users/irfanali/Projects/Hackathon/LabHack
git pull
uv sync
[ -f .env ] || cp .env.example .env   # guarded: never overwrites a live key
uv run python make_sample.py       # regenerate sample_report.pdf fresh
uv run python test_backend.py      # must be fully green on a clean run
grep -F "eval(" backend.py || echo "clean: no eval"
grep DEMO_FALLBACK .env            # confirm it reads 0
```

One live DeepSeek call to prove the key works tonight, not tomorrow:

```bash
uv run python server.py &
curl -s -F "file=@sample_report.pdf" -F "question=What is the revenue trend?" \
     http://127.0.0.1:7861/api/analyze
kill %1
```

Confirm `extract` reads `via LIVE model call`, not `CACHED fixture`. Also:
laptop and phone charged to 100%; backup laptop has the repo cloned,
`uv sync` run, and `.env` with a working key — verified tonight.

### Hour before

- Battery ≥ 90%, charger packed, no auto-sleep.
- Hotspot: battery ≥ 80%, data headroom checked, SSID/password on hand.
- Projector: cable/adapter present, mirrors correctly, done before the
  room fills.
- Fresh `uv run python server.py` (don't reuse an overnight process);
  load `http://127.0.0.1:7861` once to warm caches.

## Connectivity — phone hotspot, not venue wifi

1. Turn venue wifi **off** on the laptop and disable auto-join for any
   known venue SSID, so it cannot silently hop back mid-demo.
2. Connect the laptop to the phone hotspot before entering the room:

   ```bash
   curl -s -o /dev/null -w "%{http_code}\n" https://api.deepseek.com
   ```

   Expect `200`/`404` (reachable), not a timeout.
3. Expected live latency on `extract` over hotspot: roughly **4-6s**.
   Normal — Narrator talks through the pipeline stages during the wait.
4. If the laptop shows it rejoined venue wifi, that's the first thing to
   check when a call unexpectedly fails.

## DEMO_FALLBACK protocol

Stays `0` by default. Only Member 4 may change it, and only when: the
**live call fails during the final on-site rehearsal**, after hotspot and
key are both re-verified. Never flip pre-emptively, and never flip on the
strength of a rehearsal from days earlier — re-test live first.

```bash
# Member 4 only, on-site, after a confirmed live failure in rehearsal:
sed -i '' 's/^DEMO_FALLBACK=0/DEMO_FALLBACK=1/' .env
grep DEMO_FALLBACK .env      # must now read 1
uv run python server.py      # restart so the new value loads
```

On-screen evidence it's honest: an amber `⚠ CACHED — the live model call
failed; the demo fallback answered. Verification below still ran for real
against these facts.` banner, and `SOURCE: CACHED` in amber instead of
`SOURCE: LIVE` in teal. Point at it on stage — it's the "nothing
fabricated" proof, not an embarrassment.

**Before walking on stage**, regardless of rehearsal outcome:

```bash
grep DEMO_FALLBACK .env
```

Must print `0` unless the flip condition above was actually met. The
**Clock** reads this output out loud to the whole team before anyone
leaves for the stage. If it prints `1` without an agreed, witnessed
reason, Member 4 flips it back and the team re-runs the live-call check.
After the demo, Member 4 flips it back to `0` immediately and confirms
with the same command, read out loud again.

## Judge-uploads-own-PDF drill

Rehearse all three with real files beforehand:

- **Encrypted PDF** — `parse` fails (`Could not read that file: ...`),
  later stages `skip`, `release` reports `fail`. Line: *"Encrypted files
  stop us right at parsing — the pipeline halts and shows exactly where,
  rather than guessing at content it can't read."*
- **Scanned PDF** (no text layer) — `parse` reports `No text found. If
  this is a scanned PDF, try a text-based one.` Line: *"We extract text,
  not images — no OCR yet, and that's a stated limit, not a surprise."*
- **Huge PDF** — no enforced size cap in code today; a large file means a
  slower parse/redact pass and a bigger payload to DeepSeek, which can hit
  the provider's own limits or just take longer than the 4-6s norm.
  Rehearse with a real large file so the wait is known, not discovered
  live. Line if slow: *"Larger documents take longer to verify — every
  stage is still running for real."* If `extract` fails outright, treat it
  like the live-timeout row below.
- If `DEMO_FALLBACK` is `1` when a judge uploads their own file, the
  CACHED banner will visibly not match their document (it's the fixed
  fixture). Confirm the toggle is `0` before inviting a judge up.

## Projector check

Do this on the actual projector or an external display beforehand:

- Brightness/contrast: confirm the amber banner, amber badges, and the
  teal/orange severity colors read from the back of the room; adjust the
  projector, not the UI.
- Browser zoom: set to a level readable from the back (start 125-150%,
  Cmd-+), verified in the room.
- Hide the bookmarks bar (Cmd-Shift-B), close every other tab.
- macOS Do Not Disturb: on, for the whole demo window.

## Failure matrix

| Scenario | Audience sees | Presenter does |
|---|---|---|
| Live API timeout mid-demo | `extract` stalls past ~6s then `fail` with error detail | *"The live call just failed — this is the exact failure mode our fallback protocol covers."* Driver checks hotspot signal, retries once. Fails twice → DEMO_FALLBACK decision point above; Member 4 decides. |
| Hotspot dies | No network icon / curl to deepseek.com times out | Confirm hotspot, not just DeepSeek, is dead. Toggle hotspot off/on, retry. Still dead → Member 4 flips `DEMO_FALLBACK=1` per protocol, Narrator explains the amber banner live. Laptop itself has no network at all → move to backup laptop. |
| Laptop dies | Screen dark / app unresponsive | Backup-laptop owner (`___`) swaps in the pre-provisioned backup (repo cloned, `uv sync` run, working key in `.env`, verified night-before). Driver restarts `uv run python server.py`; Narrator keeps talking from docs/PITCH.md during the swap. |

## Rehearsal sign-off

- [ ] `DEMO_FALLBACK` toggled `1` then back to `0`, CACHED banner seen — `___`
- [ ] Non-sample PDF uploaded live, clean result or graceful failure — `___`
- [ ] Dark UI reviewed on a projector/external display — `___`

## Public demo URL (optional, cloudflared)

`bash scripts/tunnel.sh` serves the app on an ephemeral trycloudflare
URL. While it runs, uploads are publicly reachable (unguessable URL, no
auth) — PDPA answer if asked: processing still happens on this machine;
the tunnel only fronts it. Start it for the demo window, Ctrl-C it the
moment the demo ends, and never leave it running unattended.
