# FinVerify

AI-powered financial report analysis with independent verification.
DevLeague Lab 1 (Experian). Every number cited to its source; every
calculation re-checked deterministically in Python — no `eval`, ever.

## Run

```bash
uv sync
cp .env.example .env        # put your DEEPSEEK_API_KEY in .env
uv run python make_sample.py   # generates sample_report.pdf
uv run python test_backend.py  # 69 local tests, zero API cost
uv run python server.py        # primary UI (FastAPI, http://127.0.0.1:7861)
uv run python app.py           # alternative Gradio UI
```

## Screenshots

![Verified pipeline run](docs/screenshots/verified_run.png)
*A live run: the planted RM 100k mismatch caught, the trend verified at 10.0%, an evidenced risk, and every number pinned to a verbatim source quote.*

## Pipeline

upload → parse (pdfplumber/openpyxl) → PII redaction (local, before any
text reaches the model) → DeepSeek strict-JSON extraction → deterministic
verification (sum/difference/percent_change) → verbatim-quote citation
check → UI.

`DEMO_FALLBACK=1` swaps a failed model call for a cached fixture — the
UI banners it as CACHED and verification still runs for real. Keep it
`0` during development.

## Privacy (PDPA)

Only redacted text leaves the machine, never the file. NRIC (date-
validated), email, MY phone, honorific/patronymic/cue-based names, and
the PDF `/Author` metadata name are masked; per-run counts are shown in
the UI, and the exact transmitted text is inspectable under "What left
this machine". Clear Session deletes the uploaded temp file from disk.
Known limits (stated in-app): bare names without title/patronymic/cue,
and PII inside scanned images.

## Contributing & developer tips

See [CONTRIBUTING.md](CONTRIBUTING.md) — setup in four numbered steps, the
local NDJSON API contract, the six load-bearing rules (each backed by a
test), and the sharp edges worth knowing before your first commit.
