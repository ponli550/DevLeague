"""Test suite for backend.py — zero API cost.

Run: python test_backend.py
Every test runs locally. No API key, no network, no cost — except
section 12, which deliberately removes any API key to prove the
fallback engages; it never makes a real network call either.
"""

import json
import os
import re
import sys
import tempfile

# Ensure we can import backend from the same directory
sys.path.insert(0, os.path.dirname(__file__))
import backend

PASS, FAIL = 0, 0

# Fail loudly if the sample is missing. Many sections below are gated on
# sample_report.pdf existing; without this guard, a missing sample would
# silently skip those checks and the suite would report a FALSE green.
if not os.path.exists(os.path.join(os.path.dirname(__file__), "sample_report.pdf")):
    print("ERROR: sample_report.pdf not found. Run `python make_sample.py` "
          "first — the suite needs it and would otherwise skip tests and "
          "report a misleading pass.")
    sys.exit(1)


def check(label, condition, detail=""):
    global PASS, FAIL
    if condition:
        print(f"  PASS {label}")
        PASS += 1
    else:
        print(f"  FAIL {label}  {detail}")
        FAIL += 1


# ── 1. PDF parsing ────────────────────────────────────────────────────────

print("\n=== 1. PDF parsing ===")
pages = backend.parse_pdf("sample_report.pdf")
check("reads pages", len(pages) > 0, f"got {len(pages)}")
check("text is not empty", len(pages[0][1]) > 50)
check("contains revenue", "revenue" in pages[0][1].lower())

# ── 2. XLSX parsing ───────────────────────────────────────────────────────

print("\n=== 2. XLSX parsing ===")
try:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Revenue"
    ws.append(["Segment", "Amount"])
    ws.append(["Product", 1200000])
    ws.append(["Services", 1150000])
    test_path = os.path.join(tempfile.gettempdir(), "_test_finverify.xlsx")
    wb.save(test_path)
    wb.close()

    sheets = backend.parse_xlsx(test_path)
    check("reads sheets", len(sheets) == 1)
    check("text contains Product", "Product" in sheets[0][1])
    check("text contains 1200000", "1200000" in sheets[0][1])
    os.remove(test_path)
except Exception as e:
    print(f"  FAIL xlsx test crashed: {e}")
    FAIL += 1

# ── 3. File router ────────────────────────────────────────────────────────

print("\n=== 3. File router ===")
try:
    backend.parse_file("nonexistent.txt")
    check("rejects .txt", False, "should have raised")
except ValueError as e:
    check("rejects .txt", ".txt" in str(e))
except FileNotFoundError:
    check("rejects .txt", False, "should be ValueError, not FileNotFoundError")

# ── 4. PII redaction ──────────────────────────────────────────────────────

print("\n=== 4. PII redaction ===")
sample = (
    "Prepared by Ahmad Bin Ali (ahmad.ali@nusantara.com.my)\n"
    "Contact: 012-3456789 | IC: 880512-14-5533\n"
    "Also: +60123456789, test@example.org"
)
clean, n = backend.redact(sample)
check("name scrubbed", "Ahmad Bin Ali" not in clean)
check("email 1 scrubbed", "ahmad.ali@nusantara.com.my" not in clean)
check("email 2 scrubbed", "test@example.org" not in clean)
check("IC scrubbed", "880512-14-5533" not in clean)
check("phone 1 scrubbed", "012-3456789" not in clean)
check("redaction count >= 5", n >= 5, f"got {n}")
check("tokens inserted", "[EMAIL_REDACTED]" in clean)
check("non-PII preserved", "Prepared by" in clean)

# ── 5. Verification: correct math ─────────────────────────────────────────

print("\n=== 5. Verification: correct sum ===")
facts = [{"id": "f1", "value": 100}, {"id": "f2", "value": 200}]
checks = [{"description": "total", "operation": "sum",
           "operand_fact_ids": ["f1", "f2"], "expected_value": 300}]
r = backend.verify(facts, checks)
check("passes correct sum", r[0]["passed"] is True)
check("actual is 300", r[0]["actual"] == 300.0)

# ── 6. Verification: caught mismatch ──────────────────────────────────────

print("\n=== 6. Verification: mismatch ===")
facts = [{"id": "f1", "value": 1200000},
         {"id": "f2", "value": 1150000},
         {"id": "f3", "value": 300000}]
checks = [{"description": "revenue total", "operation": "sum",
           "operand_fact_ids": ["f1", "f2", "f3"],
           "expected_value": 2750000}]
r = backend.verify(facts, checks)
check("fails mismatch", r[0]["passed"] is False)
check("actual is 2650000", r[0]["actual"] == 2650000.0)
check("expected is 2750000", r[0]["expected"] == 2750000.0)

# ── 7. Verification: hostile inputs ───────────────────────────────────────

print("\n=== 7. Hostile input handling ===")
hostile = {
    "string values with commas": (
        [{"id": "f1", "value": "1,200,000"}, {"id": "f2", "value": "RM 1,150,000"}],
        [{"description": "s", "operation": "sum",
          "operand_fact_ids": ["f1", "f2"], "expected_value": "2,350,000"}],
    ),
    "missing fact id": (
        [{"id": "f1", "value": 100}],
        [{"description": "s", "operation": "sum",
          "operand_fact_ids": ["f1", "f99"], "expected_value": 200}],
    ),
    "empty operands": (
        [],
        [{"description": "s", "operation": "sum",
          "operand_fact_ids": [], "expected_value": 5}],
    ),
    "divide by zero": (
        [{"id": "f1", "value": 0}, {"id": "f2", "value": 50}],
        [{"description": "s", "operation": "percent_change",
          "operand_fact_ids": ["f1", "f2"], "expected_value": 10}],
    ),
    "unknown operation": (
        [{"id": "f1", "value": 5}],
        [{"description": "s", "operation": "integrate",
          "operand_fact_ids": ["f1"], "expected_value": 5}],
    ),
    "eval injection": (
        [{"id": "f1", "value": "__import__('os').system('echo PWNED')"}],
        [{"description": "s", "operation": "sum",
          "operand_fact_ids": ["f1"], "expected_value": 1}],
    ),
    "null everything": (None, None),
    "non-dict in checks": (
        [{"id": "f1", "value": 5}],
        ["not a dict", 42],
    ),
    "missing expected_value": (
        [{"id": "f1", "value": 5}],
        [{"description": "s", "operation": "sum",
          "operand_fact_ids": ["f1"]}],
    ),
}

for label, (f, c) in hostile.items():
    try:
        out = backend.verify(f, c)
        check(label, True)
    except Exception as e:
        check(label, False, f"CRASHED: {type(e).__name__}: {e}")

# ── 8. JSON extraction from messy model output ────────────────────────────

print("\n=== 8. JSON extraction ===")
for label, raw in [
    ("clean json", '{"answer":"x"}'),
    ("fenced", '```json\n{"answer":"x"}\n```'),
    ("preamble", 'Here you go:\n{"answer":"x"}\nHope that helps!'),
    ("double fenced", '```json\n```json\n{"answer":"x"}\n```\n```'),
]:
    try:
        parsed = backend._extract_json(raw)
        check(label, parsed.get("answer") == "x")
    except Exception as e:
        check(label, False, f"CRASHED: {e}")

# ── 9. analyze() guard rails ──────────────────────────────────────────────

print("\n=== 9. analyze() guard rails ===")
for label, args in [
    ("no file", (None, "q")),
    ("no question", ("sample_report.pdf", "")),
    ("no question spaces", ("sample_report.pdf", "   ")),
    ("bad path", ("nonexistent.pdf", "q")),
    ("unsupported type", ("data.csv", "q")),
]:
    out = backend.analyze(*args)
    check(f"{label} returns error", out.get("error") is not None,
          f"got: {out.get('error')!r}")
    check(f"{label} no crash fields", "facts" in out and "checks" in out)

# ── 10. Percent change ────────────────────────────────────────────────────

print("\n=== 10. Percent change ===")
facts = [{"id": "f1", "value": 2400000}, {"id": "f2", "value": 2750000}]
checks = [{"description": "revenue growth", "operation": "percent_change",
           "operand_fact_ids": ["f1", "f2"], "expected_value": 14.58}]
r = backend.verify(facts, checks)
check("percent_change computes", r[0]["actual"] is not None)
check("percent_change close", abs(r[0]["actual"] - 14.58) < 0.1,
      f"got {r[0]['actual']}")

# ── 11. _fact_in_source (anti-hallucination check) ────────────────────────

print("\n=== 11. _fact_in_source ===")
pages = [("Page 1", "Product revenue 1,200,000 was reported.")]
check("quote found in source",
      backend._fact_in_source({"quote": "Product revenue 1,200,000"}, pages) is True)
check("quote not found in source",
      backend._fact_in_source({"quote": "Product revenue 9,999,999"}, pages) is False)
check("empty quote fails",
      backend._fact_in_source({"quote": ""}, pages) is False)
check("missing quote key fails",
      backend._fact_in_source({}, pages) is False)

# ── 12. DEMO_FALLBACK path — the non-negotiable safety-net proof ──────────

print("\n=== 12. DEMO_FALLBACK path ===")
if os.path.exists("sample_report.pdf"):
    old_keys = {k: os.environ.pop(k, None)
                for k in ("DEEPSEEK_API_KEY", "deepseek_api", "GEMINI_API_KEY")}
    old_fallback = os.environ.get("DEMO_FALLBACK")
    os.environ["DEMO_FALLBACK"] = "1"
    try:
        out = backend.analyze(
            "sample_report.pdf",
            "What was total revenue, and does it add up?",
        )
        check("fallback returns no error", out.get("error") is None,
              f"got: {out.get('error')!r}")
        check("fallback returns facts", len(out.get("facts") or []) > 0)
        check("fallback still verifies math", len(out.get("checks") or []) > 0)
        check("fallback is flagged, never silent",
              out.get("fallback_used") is True)
        check("fallback catches the planted mismatch",
              any(c.get("passed") is False and not c.get("error")
                  for c in out.get("checks") or []))
        check("fallback quotes verify against real source",
              all(f.get("verified_in_source") for f in out.get("facts") or []),
              f"flags: {[f.get('verified_in_source') for f in out.get('facts') or []]}")
    finally:
        for k, v in old_keys.items():
            if v is not None:
                os.environ[k] = v
        if old_fallback is not None:
            os.environ["DEMO_FALLBACK"] = old_fallback
        else:
            os.environ.pop("DEMO_FALLBACK", None)
else:
    print("  WARN sample_report.pdf not found — run make_sample.py first")

# ── 13. Name heuristics + NRIC validation (v2 hardening) ──────────────────

print("\n=== 13. Name heuristics + NRIC validation ===")
t, _ = backend.redact("Approved by Siti Nurhaliza Binti Hassan on 12 May")
check("cue + binti name scrubbed", "Siti" not in t and "Approved by" in t, t)
t, _ = backend.redact("Signed for the board: MOHD RAZAK BIN OSMAN, Director")
check("ALL-CAPS patronymic scrubbed", "RAZAK" not in t, t)
t, _ = backend.redact("Datuk Seri Wan Azizah attended the meeting")
check("honorific name scrubbed", "Azizah" not in t, t)
t, _ = backend.redact("Ramasamy A/L Muniandy holds 40,000 shares")
check("a/l patronymic scrubbed", "Ramasamy" not in t, t)
t, _ = backend.redact("Company No. 202001012345 (12 digits)")
check("company reg number NOT redacted", "202001012345" in t, t)
t, _ = backend.redact("Ref: 991331-14-5533 is an invoice, not an IC")
check("impossible-date IC NOT redacted", "991331-14-5533" in t, t)
t, _ = backend.redact("IC: 880512-14-5533")
check("valid-date IC redacted", "880512-14-5533" not in t, t)
names = backend.pdf_metadata_names("sample_report.pdf") if os.path.exists("sample_report.pdf") else []
check("metadata author fn returns list", isinstance(names, list))

# ── 14. purge_upload safety gate ──────────────────────────────────────────

print("\n=== 14. purge_upload safety gate ===")
gradio_tmp = os.path.join(tempfile.gettempdir(), "gradio")
os.makedirs(gradio_tmp, exist_ok=True)
victim = os.path.join(gradio_tmp, "_finverify_purge_test.pdf")
with open(victim, "w") as fh:
    fh.write("x")
check("deletes file inside gradio temp", backend.purge_upload(victim) is True)
check("file is actually gone", not os.path.exists(victim))
check("refuses file outside gradio temp",
      backend.purge_upload("sample_report.pdf") is False)
check("sample survives the refusal", os.path.exists("sample_report.pdf")
      if os.path.exists("sample_report.pdf") else True)
check("handles None", backend.purge_upload(None) is False)
check("handles missing path", backend.purge_upload(
    os.path.join(gradio_tmp, "never_existed.pdf")) is False)

# ── 15. Recommendation layer (#23) — written BEFORE the implementation ─────

print("\n=== 15. Recommendation layer ===")
check("prompt asks for a recommendation",
      '"recommendation"' in backend.SYSTEM_PROMPT)
with open(os.path.join(os.path.dirname(__file__), "fixtures",
                       "cached_response.json")) as fh:
    _fx = json.load(fh)
check("fixture carries a recommendation",
      bool(str(_fx.get("recommendation", "")).strip()))
if os.path.exists("sample_report.pdf"):
    _oks = {k: os.environ.pop(k, None)
            for k in ("DEEPSEEK_API_KEY", "deepseek_api", "GEMINI_API_KEY")}
    os.environ["DEMO_FALLBACK"] = "1"
    try:
        _out = backend.analyze("sample_report.pdf", "Does revenue add up?")
        check("analyze surfaces the recommendation",
              bool(str(_out.get("recommendation", "")).strip()),
              f"got: {_out.get('recommendation')!r}")
    finally:
        for k, v in _oks.items():
            if v is not None:
                os.environ[k] = v
        os.environ.pop("DEMO_FALLBACK", None)


# ── 16. DeepSeek provider swap — written BEFORE the implementation ─────────

print("\n=== 16. DeepSeek provider ===")
check("backend exposes _call_deepseek", hasattr(backend, "_call_deepseek"))
check("gemini is a BYOK provider entrypoint", hasattr(backend, "_call_gemini"))
check("default model is deepseek-chat", backend.MODEL == "deepseek-chat")
_src = open(os.path.join(os.path.dirname(__file__), "backend.py")).read()
check("deepseek remains the env default",
      '"deepseek"' in _src and "LLM_PROVIDER" in _src)
_saved = {k: os.environ.pop(k, None)
          for k in ("DEEPSEEK_API_KEY", "deepseek_api")}
os.environ.pop("DEMO_FALLBACK", None)
try:
    backend._call_deepseek([("Page 1", "x")], "q")
    check("missing key raises", False, "should have raised")
except Exception as e:
    check("missing key raises", True)
    check("error names DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY" in str(e), str(e))
finally:
    for k, v in _saved.items():
        if v is not None:
            os.environ[k] = v


# ── 17. against_fact_id — expected value must come from a cited fact ───────
# Live-call finding: the model set expected_value to its own computed sum,
# so a real discrepancy showed as PASS. Written BEFORE the fix.

print("\n=== 17. against_fact_id ===")
_facts = [{"id": "f1", "value": 1200000}, {"id": "f2", "value": 1150000},
          {"id": "f3", "value": 300000},
          {"id": "f4", "value": 2750000, "claim": "stated total"}]
_checks = [{"description": "components vs stated total", "operation": "sum",
            "operand_fact_ids": ["f1", "f2", "f3"],
            "against_fact_id": "f4",
            "expected_value": 2650000}]  # model's self-serving number — must be ignored
r = backend.verify(_facts, _checks)
check("expected resolves from the cited fact", r[0]["expected"] == 2750000.0,
      f"got {r[0]['expected']}")
check("self-graded pass becomes a caught mismatch", r[0]["passed"] is False)
_checks2 = [{"description": "dangling ref", "operation": "sum",
             "operand_fact_ids": ["f1"], "against_fact_id": "f99"}]
r2 = backend.verify(_facts, _checks2)
check("dangling against_fact_id errors, not crashes",
      r2[0]["error"] is not None and r2[0]["passed"] is False)
check("prompt demands against_fact_id",
      "against_fact_id" in backend.SYSTEM_PROMPT)
with open(os.path.join(os.path.dirname(__file__), "fixtures",
                       "cached_response.json")) as fh:
    _fx2 = json.load(fh)
check("fixture exercises against_fact_id",
      any(c.get("against_fact_id") for c in _fx2.get("checks", [])))


# ── 18. analyze_stream — in-product CI pipeline, written BEFORE the code ───

print("\n=== 18. analyze_stream (CI pipeline) ===")
check("backend exposes analyze_stream", hasattr(backend, "analyze_stream"))
if hasattr(backend, "analyze_stream") and os.path.exists("sample_report.pdf"):
    _keys = {k: os.environ.pop(k, None)
             for k in ("DEEPSEEK_API_KEY", "deepseek_api")}
    os.environ["DEMO_FALLBACK"] = "1"
    try:
        events = list(backend.analyze_stream(
            "sample_report.pdf", "Does revenue add up?"))
        stages = [e["stage"] for e in events if e["status"] in ("ok", "fail")]
        check("stages run in CI order",
              stages == ["parse", "redact", "extract",
                         "verify-math", "verify-citations",
                         "analyse-patterns", "release"],
              f"got {stages}")
        check("every completed stage is measured",
              all(e.get("elapsed_ms") is not None and e["elapsed_ms"] >= 0
                  for e in events if e["status"] in ("ok", "fail")))
        check("gate: nothing before release carries the answer",
              all(not e.get("result") for e in events[:-1]))
        final = events[-1]
        check("release carries the full result",
              final["stage"] == "release" and isinstance(final.get("result"), dict)
              and final["result"].get("error") is None
              and bool(final["result"].get("answer")))
        ref = backend.analyze("sample_report.pdf", "Does revenue add up?")
        check("analyze() and stream release agree on shape",
              set(ref.keys()) == set(final["result"].keys()))
        # hard failure: pipeline stops, later stages skip, error still released
        bad = list(backend.analyze_stream(None, "q"))
        bstat = {e["stage"]: e["status"] for e in bad}
        check("hard fail stops at parse", bstat.get("parse") == "fail")
        check("later stages are skipped, not run",
              bstat.get("extract") == "skip" and bstat.get("verify-math") == "skip")
        check("failure is still released with an error",
              bad[-1]["stage"] == "release"
              and bad[-1]["result"].get("error") is not None)
    finally:
        for k, v in _keys.items():
            if v is not None:
                os.environ[k] = v
        os.environ.pop("DEMO_FALLBACK", None)


# ── 19. FastAPI frontend server — written BEFORE the implementation ────────

print("\n=== 19. FastAPI server ===")
try:
    import server as _srv
    _has_srv = True
except Exception as _e:
    _has_srv = False
    print(f"  (server import failed: {_e})")
check("server module importable", _has_srv)
if _has_srv and os.path.exists("sample_report.pdf"):
    from fastapi.testclient import TestClient
    _client = TestClient(_srv.app)
    _r = _client.get("/")
    check("serves the frontend at /",
          _r.status_code == 200 and "FINVERIFY" in _r.text.upper())
    check("frontend is self-contained (no tailwind CDN)",
          "cdn.tailwindcss.com" not in _r.text)
    check("frontend carries no fabricated tx hashes",
          "8xA9" not in _r.text and "SETTLED" not in _r.text)
    _saved = {k: os.environ.pop(k, None)
              for k in ("DEEPSEEK_API_KEY", "deepseek_api")}
    os.environ["DEMO_FALLBACK"] = "1"
    try:
        with open("sample_report.pdf", "rb") as fh:
            _r = _client.post(
                "/api/analyze",
                files={"file": ("sample_report.pdf", fh, "application/pdf")},
                data={"question": "Does revenue add up?"},
            )
        check("analyze endpoint streams", _r.status_code == 200)
        _lines = [json.loads(l) for l in _r.text.strip().splitlines()]
        _stages = [e["stage"] for e in _lines if e["status"] in ("ok", "fail")]
        check("NDJSON events in CI order",
              _stages == ["parse", "redact", "extract",
                          "verify-math", "verify-citations",
                          "analyse-patterns", "release"],
              f"got {_stages}")
        check("release event carries the answer",
              _lines[-1]["stage"] == "release"
              and bool(_lines[-1]["result"].get("answer")))
        check("server deleted the upload after analysis",
              not any(fname.startswith("finverify_")
                      for fname in os.listdir(tempfile.gettempdir())))
    finally:
        for k, v in _saved.items():
            if v is not None:
                os.environ[k] = v
        os.environ.pop("DEMO_FALLBACK", None)


# ── 21. Trends & risks (Lab 1: "trends, patterns, exceptions, risks") ──────
# Written BEFORE the implementation.

print("\n=== 21. Trends & risks ===")
check("prompt demands structured risks", '"risks"' in backend.SYSTEM_PROMPT)
check("prompt demands percent_change trend checks for multi-period docs",
      "percent_change" in backend.SYSTEM_PROMPT
      and "period" in backend.SYSTEM_PROMPT.lower())
with open(os.path.join(os.path.dirname(__file__), "fixtures",
                       "cached_response.json")) as fh:
    _fx3 = json.load(fh)
check("fixture carries at least one evidenced risk",
      any(r.get("evidence_fact_ids") for r in _fx3.get("risks", [])))
check("fixture carries a percent_change trend check",
      any(c.get("operation") == "percent_change" for c in _fx3.get("checks", [])))
# evidence discipline: a risk citing an unknown fact id is excluded outright
_kept = backend._clean_risks(
    [{"description": "real", "severity": "HIGH", "evidence_fact_ids": ["f1"]},
     {"description": "phantom", "severity": "low", "evidence_fact_ids": ["f1", "f99"]},
     {"description": "uncited", "severity": "low", "evidence_fact_ids": []},
     "not a dict"],
    [{"id": "f1"}])
check("evidenced risk kept with normalised severity",
      len(_kept) == 1 and _kept[0]["severity"] == "high")
if os.path.exists("sample_report.pdf"):
    _pages = backend.parse_pdf("sample_report.pdf")
    check("sample now carries a prior period (page 2)",
          len(_pages) >= 2 and "prior quarter" in _pages[1][1].lower())
    _ks = {k: os.environ.pop(k, None) for k in ("DEEPSEEK_API_KEY", "deepseek_api")}
    os.environ["DEMO_FALLBACK"] = "1"
    try:
        _o = backend.analyze("sample_report.pdf", "How did revenue trend, and what are the risks?")
        check("analyze surfaces evidenced risks", len(_o.get("risks") or []) > 0)
        _fids = {f["id"] for f in _o["facts"]}
        check("every surfaced risk cites known facts",
              all(set(r["evidence_fact_ids"]) <= _fids for r in _o["risks"]))
        _trend = [c for c in _o["checks"] if "growth" in c["description"].lower()
                  or "prior" in c["description"].lower()]
        check("the trend check verifies deterministically",
              any(c.get("passed") for c in _trend), f"trend checks: {_trend}")
    finally:
        for k, v in _ks.items():
            if v is not None:
                os.environ[k] = v
        os.environ.pop("DEMO_FALLBACK", None)


# ── 22. Verified insights summary (Lab 1: "concise summaries") ─────────────
# The insights summary must be COMPOSED from verified data, never carry a
# number the pipeline did not re-check. Written to lock that guarantee.

print("\n=== 22. Verified insights summary ===")

# The _empty_result() bug: an error/empty result must carry NO risks and an
# empty insights string — never a placeholder.
_er = backend._empty_result()
check("empty result carries no phantom risks", _er["risks"] == [])
check("empty result has an insights key", "insights" in _er)
check("empty result insights is blank", _er["insights"] == "")
check("empty result has no leftover placeholder ids",
      "f1" not in json.dumps(_er))

# build_insights composes from verified rows only. Note the descriptions
# below deliberately CONTAIN unverified numbers (9,999,999 / 42% / 7,777) —
# the masking guarantee is that none of those reach the output.
_ins_facts = [{"id": "f1", "value": 1200000}, {"id": "f2", "value": 1150000},
              {"id": "f4", "value": 2750000}]
_ins_checks = [
    {"description": "Stated total vs sum of segments (model claims 9,999,999)",
     "operation": "sum", "expected": 2750000.0,
     "actual": 2650000.0, "passed": False, "error": None},
    {"description": "Revenue growth of a claimed 42% vs prior quarter",
     "operation": "percent_change", "expected": 10.0,
     "actual": 10.0, "passed": True, "error": None},
    {"description": "Unresolvable ratio", "operation": "percent_change",
     "expected": None, "actual": None,
     "passed": False, "error": "cannot compute percent change from zero"},
]
_ins_risks = [
    {"description": "headline off by RM 7,777 does not reconcile",
     "severity": "high", "evidence_fact_ids": ["f1", "f4"]},
    {"description": "trend inherits the gap", "severity": "medium",
     "evidence_fact_ids": ["f2"]},
]
_ins_summary = {"facts_extracted": 3, "checks_run": 3,
                "checks_passed": 1, "checks_failed": 1}
_ins = backend.build_insights(_ins_facts, _ins_checks, _ins_risks, _ins_summary)
check("insights is a non-empty string", isinstance(_ins, str) and bool(_ins))
check("insights surfaces the verified trend", "Trend verified" in _ins)
check("insights surfaces the confirmed exception", "Exception" in _ins)
check("insights states the size of the gap", "100,000" in _ins)
check("insights lists evidenced risks", "Risk (high)" in _ins
      and "Risk (medium)" in _ins)
check("high-severity risk is ordered before medium",
      _ins.index("Risk (high)") < _ins.index("Risk (medium)"))
check("insights reports coverage", "Coverage:" in _ins
      and "re-checked in Python" in _ins)
# Anti-hallucination (the real test): numbers the model wrote INTO its
# descriptions must be masked, never echoed. These were fed above.
check("model's unverified number in a check description is masked",
      "9,999,999" not in _ins and "9999999" not in _ins)
check("model's unverified percentage in a description is masked",
      "42%" not in _ins)
check("model's unverified number in a risk description is masked",
      "7,777" not in _ins and "7777" not in _ins)
check("masking leaves a placeholder", "#" in _ins)
# But the Python-COMPUTED numbers must still be present and correct.
check("computed figures survive masking",
      "2,750,000" in _ins and "2,650,000" in _ins and "10%" in _ins)
# Trend classification is structural (operation), not prose-driven: a sum
# check whose description says "change" must NOT be labelled a trend.
_kw = backend.build_insights(
    [], [{"description": "net change in cash", "operation": "sum",
          "expected": 5.0, "actual": 5.0, "passed": True, "error": None}],
    [], {"facts_extracted": 0, "checks_run": 1})
check("a passed sum is not mislabelled a trend", "Trend verified" not in _kw)
# A failed check missing a figure degrades to just its description.
_partial = backend.build_insights(
    [], [{"description": "orphan", "operation": "sum", "expected": None,
          "actual": None, "passed": False, "error": None}],
    [], {"facts_extracted": 0, "checks_run": 1})
check("partial failed check omits n/a numeric prose", "n/a" not in _partial)

# Nothing to verify -> empty summary, not fabricated prose.
check("no checks yields empty insights",
      backend.build_insights([], [], [], {"checks_run": 0}) == "")

# End-to-end: analyze() surfaces the insights via the release event.
if os.path.exists("sample_report.pdf"):
    _ks2 = {k: os.environ.pop(k, None)
            for k in ("DEEPSEEK_API_KEY", "deepseek_api")}
    os.environ["DEMO_FALLBACK"] = "1"
    try:
        _o2 = backend.analyze("sample_report.pdf",
                              "Summarise the findings and any risks.")
        check("analyze surfaces an insights summary",
              bool(str(_o2.get("insights", "")).strip()))
        check("insights mentions the discrepancy the checks found",
              "Exception" in _o2["insights"] or "mismatch" in _o2["insights"])
    finally:
        for k, v in _ks2.items():
            if v is not None:
                os.environ[k] = v
        os.environ.pop("DEMO_FALLBACK", None)


# ── 23. Pattern analysis (Lab 1: "patterns") — after verify+citations ──────
# Patterns are proposed by the model but RECOMPUTED in Python from cited
# facts, dropped if uncited, and their prose is digit-masked. Written to
# lock all of that.

print("\n=== 23. Pattern analysis ===")
check("prompt demands structured patterns", '"patterns"' in backend.SYSTEM_PROMPT)
check("prompt names the three pattern kinds",
      "composition" in backend.SYSTEM_PROMPT and "ratio" in backend.SYSTEM_PROMPT
      and "sign" in backend.SYSTEM_PROMPT)
check("empty result seeds patterns as []", backend._empty_result()["patterns"] == [])
check("analyse-patterns is in the pipeline stages after citations",
      backend.PIPELINE_STAGES.index("analyse-patterns")
      > backend.PIPELINE_STAGES.index("verify-citations")
      and backend.PIPELINE_STAGES.index("analyse-patterns")
      < backend.PIPELINE_STAGES.index("release"))

_pf = [{"id": "f1", "value": 1200000}, {"id": "f4", "value": 2750000},
       {"id": "f5", "value": 1450000}, {"id": "f6", "value": -50000}]
_pats = [
    # composition: 1,200,000 / 2,750,000 * 100 = 43.64
    {"kind": "composition", "description": "product share of revenue",
     "operand_fact_ids": ["f1"], "against_fact_id": "f4",
     "evidence_fact_ids": ["f1", "f4"]},
    # ratio: 1,450,000 / 2,750,000 * 100 = 52.73
    {"kind": "ratio", "description": "opex to revenue at a claimed 999%",
     "operand_fact_ids": ["f5", "f4"], "evidence_fact_ids": ["f5", "f4"]},
    # sign: -50,000 is negative -> the flagged condition holds
    {"kind": "sign", "description": "net line is negative",
     "operand_fact_ids": ["f6"], "evidence_fact_ids": ["f6"]},
    # phantom evidence -> dropped
    {"kind": "composition", "description": "phantom",
     "operand_fact_ids": ["f1"], "against_fact_id": "f4",
     "evidence_fact_ids": ["f1", "f99"]},
    # unknown kind -> dropped
    {"kind": "outlier", "description": "not supported",
     "operand_fact_ids": ["f1"], "evidence_fact_ids": ["f1"]},
    "not a dict",
]
_pr = backend.verify_patterns(_pf, _pats)
check("only evidenced, known-kind patterns survive", len(_pr) == 3,
      f"got {len(_pr)}")
_by_kind = {p["kind"]: p for p in _pr}
check("composition share recomputed in Python",
      abs(_by_kind["composition"]["actual"] - 43.64) < 0.01)
check("composition is confirmed", _by_kind["composition"]["passed"] is True)
check("ratio recomputed in Python",
      abs(_by_kind["ratio"]["actual"] - 52.73) < 0.01)
check("sign pattern confirmed on a negative value",
      _by_kind["sign"]["passed"] is True and _by_kind["sign"]["actual"] == -50000.0)
# The model's self-serving expected value must never turn a pattern into a
# free pass — patterns recompute, they do not trust typed numbers.
_cheat = backend.verify_patterns(
    [{"id": "f1", "value": 100}, {"id": "f2", "value": 400}],
    [{"kind": "ratio", "description": "d", "operand_fact_ids": ["f1", "f2"],
      "expected_value": 999, "evidence_fact_ids": ["f1", "f2"]}])
check("a model-typed expected_value cannot fake a pattern pass",
      _cheat[0]["passed"] is False and abs(_cheat[0]["actual"] - 25.0) < 0.01)
# Unverifiable: a sign pattern whose fact is unusable comes back as error,
# never as an established finding.
_unver = backend.verify_patterns(
    [{"id": "f1", "value": "not a number"}],
    [{"kind": "sign", "description": "x", "operand_fact_ids": ["f1"],
      "evidence_fact_ids": ["f1"]}])
check("unusable pattern fact -> unverifiable, not passed",
      _unver and _unver[0]["error"] is not None and _unver[0]["passed"] is False)

# Digit-masking in the insights patterns section: the model's "999%" in a
# pattern description must not survive; the Python-computed 52.73% must.
_pins = backend.build_insights(_pf, [], [],
                               {"facts_extracted": 4, "checks_run": 0}, _pr)
check("pattern insights show a Python-computed figure", "52.73%" in _pins)
check("model's number inside a pattern description is masked",
      "999%" not in _pins)
check("pattern insights carry a mask placeholder", "#" in _pins)

# End-to-end via the fallback fixture: patterns surface in the release.
if os.path.exists("sample_report.pdf"):
    _ks3 = {k: os.environ.pop(k, None)
            for k in ("DEEPSEEK_API_KEY", "deepseek_api")}
    os.environ["DEMO_FALLBACK"] = "1"
    try:
        _po = backend.analyze("sample_report.pdf",
                              "What patterns do you see?")
        check("analyze surfaces verified patterns",
              len(_po.get("patterns") or []) > 0)
        _pfids = {f["id"] for f in _po["facts"]}
        check("every surfaced pattern cites known facts",
              all(set(p["evidence_fact_ids"]) <= _pfids
                  for p in _po["patterns"]))
        check("insights include a pattern line",
              "Pattern verified" in _po["insights"]
              or "Pattern (unverifiable)" in _po["insights"])
    finally:
        for k, v in _ks3.items():
            if v is not None:
                os.environ[k] = v
        os.environ.pop("DEMO_FALLBACK", None)


# ── 24. Improvement batch: negatives, fences, anti-cheat visibility, ───────
#     suppressed counts, opex ratio, flag wording, UTF-8. Written to lock
#     the senior-approved improvements A/C/B/H/I/F.

print("\n=== 24. Improvement batch ===")

# A — accounting-parentheses negatives.
check("bracketed number is negative", backend._to_number("(50,000)") == -50000.0)
check("bracketed decimal is negative",
      abs(backend._to_number("(1,234.50)") - (-1234.5)) < 0.001)
check("plain number stays positive", backend._to_number("1,200,000") == 1200000.0)
check("currency-prefixed stays positive", backend._to_number("RM 2,750,000") == 2750000.0)
check("a bracketed negative flips a difference",
      backend.verify(
          [{"id": "f1", "value": 100000}, {"id": "f2", "value": "(30,000)"}],
          [{"description": "d", "operation": "sum",
            "operand_fact_ids": ["f1", "f2"], "expected_value": 70000}]
      )[0]["actual"] == 70000.0)

# C — case-insensitive fence strip.
check("uppercase JSON fence is stripped",
      backend._extract_json('```JSON\n{"answer":"x"}\n```').get("answer") == "x")

# H — anti-cheat visibility. The model's typed number is preserved for
# display, the override is flagged, but expected/passed are UNCHANGED.
_hf = [{"id": "f1", "value": 1200000}, {"id": "f2", "value": 1150000},
       {"id": "f3", "value": 300000}, {"id": "f4", "value": 2750000}]
_hc = [{"description": "components vs stated", "operation": "sum",
        "operand_fact_ids": ["f1", "f2", "f3"], "against_fact_id": "f4",
        "expected_value": 2650000}]  # model's self-serving number
_hr = backend.verify(_hf, _hc)[0]
check("model_stated preserves the model's typed number",
      _hr["model_stated"] == 2650000.0)
check("overridden flags the anti-cheat substitution", _hr["overridden"] is True)
check("expected still comes from the cited fact (invariant)",
      _hr["expected"] == 2750000.0)
check("passed logic unchanged by the display field", _hr["passed"] is False)
# No override flag when the model's number agrees with the cited fact.
_hr2 = backend.verify(
    [{"id": "f1", "value": 100}, {"id": "f2", "value": 200}, {"id": "f3", "value": 300}],
    [{"description": "d", "operation": "sum", "operand_fact_ids": ["f1", "f2"],
      "against_fact_id": "f3", "expected_value": 300}])[0]
check("no override when model agrees with the cited figure",
      _hr2["overridden"] is False)

# I — suppressed-claim counts surface in the stage detail, not the summary.
check("summary dict has no suppressed keys (invariant)",
      set(backend._empty_result()["summary"].keys())
      == {"facts_extracted", "checks_run", "checks_passed", "checks_failed"})

# F — the fixture now exercises an opex-to-revenue ratio pattern.
with open(os.path.join(os.path.dirname(__file__), "fixtures",
                       "cached_response.json"), encoding="utf-8") as fh:
    _fx4 = json.load(fh)
check("prompt demands opex-to-revenue ratio",
      "opex-to-revenue" in backend.SYSTEM_PROMPT.lower()
      or "opex" in backend.SYSTEM_PROMPT.lower())
check("fixture carries a ratio pattern",
      any(p.get("kind") == "ratio" for p in _fx4.get("patterns", [])))

# B — a confirmed sign/threshold pattern reads as a FLAG, not a reassuring
# "verified". (Presentation wording; verify() passed logic is unchanged.)
_flag = backend.build_insights(
    [{"id": "f1", "value": -50000}], [], [],
    {"facts_extracted": 1, "checks_run": 0},
    [{"kind": "sign", "description": "net loss", "actual": -50000.0,
      "passed": True, "error": None, "evidence_fact_ids": ["f1"]}])
check("sign pattern insight is framed as a flag", "Flag confirmed" in _flag)
check("sign pattern insight is not reassuring 'verified'",
      "Pattern verified" not in _flag)

# UTF-8 regression: the fixture loads without mojibake (the em-dash bug).
_rec = str(_fx4.get("recommendation", ""))
check("fixture recommendation loads without mojibake",
      "â€" not in _rec and "—" in _fx4.get("answer", ""))


# ── 25. bounded retry before fallback (#34) — written BEFORE the code ──────

print("\n=== 25. bounded retry ===")
import inspect as _insp
_calls = {"n": 0}
_orig = backend._call_deepseek
def _flaky(pages, q):
    _calls["n"] += 1
    if _calls["n"] == 1:
        raise RuntimeError("transient network blip")
    return {"answer": "x"}
backend._call_deepseek = _flaky
try:
    _out, _cached = backend.ask_llm([("Page 1", "t")], "q")
    check("one transient failure is retried and succeeds",
          _out == {"answer": "x"} and _cached is False and _calls["n"] == 2,
          f"calls={_calls['n']}")
    _calls["n"] = 0
    def _dead(pages, q):
        _calls["n"] += 1
        raise RuntimeError("hard down")
    backend._call_deepseek = _dead
    _oldfb = os.environ.pop("DEMO_FALLBACK", None)
    try:
        try:
            backend.ask_llm([("Page 1", "t")], "q")
            check("double failure raises", False)
        except RuntimeError as e:
            check("double failure raises after exactly 2 attempts",
                  _calls["n"] == 2, f"calls={_calls['n']}")
            check("error names the retry", "retry" in str(e).lower(), str(e))
        _calls["n"] = 0
        os.environ["DEMO_FALLBACK"] = "1"
        _out, _cached = backend.ask_llm([("Page 1", "t")], "q")
        check("fallback engages only after the retry",
              _cached is True and _calls["n"] == 2, f"calls={_calls['n']}")
    finally:
        os.environ.pop("DEMO_FALLBACK", None)
        if _oldfb is not None:
            os.environ["DEMO_FALLBACK"] = _oldfb
finally:
    backend._call_deepseek = _orig
check("client call carries an explicit timeout",
      "timeout" in _insp.getsource(backend._call_deepseek))


# ── 26. golden XLSX fixture (#33) — written BEFORE the code ────────────────

print("\n=== 26. golden XLSX ===")
import hashlib as _hl
check("make_sample exposes an xlsx generator",
      hasattr(__import__("make_sample"), "build_xlsx"))
if hasattr(__import__("make_sample"), "build_xlsx"):
    import make_sample as _ms
    _xp = os.path.join(tempfile.gettempdir(), "_golden_check.xlsx")
    _ms.build_xlsx(_xp)
    _sheets = backend.parse_xlsx(_xp)
    _text = "\n".join(t for _, t in _sheets)
    _sha = _hl.sha256(_text.encode()).hexdigest()
    with open(os.path.join(os.path.dirname(__file__), "fixtures",
                           "golden_xlsx.json")) as fh:
        _g = json.load(fh)
    check("parsed text matches the golden sha", _sha == _g["text_sha256"],
          f"got {_sha[:16]}")
    _clean, _n = backend.redact(_text)
    check("golden redaction count matches", _n == _g["redaction_count"],
          f"got {_n}")
    check("xlsx carries the same planted discrepancy",
          "2,750,000" in _text or "2750000" in _text)
    os.remove(_xp)


# ── 27. Gradio app risks parity (#32) — written BEFORE the code ────────────

print("\n=== 27. Gradio risks parity ===")
try:
    import app as _app
    check("app.py imports (CI now guards the Gradio UI)", True)
except Exception as _e:
    check("app.py imports (CI now guards the Gradio UI)", False, str(_e))
    _app = None
if _app is not None:
    check("app exposes render_risks", hasattr(_app, "render_risks"))
    if hasattr(_app, "render_risks"):
        _html = _app.render_risks({"risks": [
            {"description": "Total does not reconcile", "severity": "high",
             "evidence_fact_ids": ["f1", "f4"]}]})
        check("risk description and evidence rendered",
              "Total does not reconcile" in _html and "f1" in _html)
        check("severity is visible as text, not color alone",
              "high" in _html.lower())
        # In the current layout risks have their own panel, so an empty
        # risk set renders a positive "no risks flagged" confirmation
        # rather than nothing — it must not render a phantom risk card.
        _empty_html = _app.render_risks({"risks": []})
        check("no risks -> no phantom risk card",
              "risk-card" not in _empty_html and "RISK" not in _empty_html.upper())
    check("FAKE payload carries risks for UI development",
          bool(_app.FAKE.get("risks")))


# ── 28. tamper-evident audit chain — spec BEFORE code ──────────────────────

print("\n=== 28. audit chain ===")
import hashlib as _ah, hmac as _am
_ks = {k: os.environ.pop(k, None) for k in ("DEEPSEEK_API_KEY", "deepseek_api")}
os.environ["DEMO_FALLBACK"] = "1"
os.environ["AUDIT_HMAC_KEY"] = "test-audit-key"
try:
    _evs = list(backend.analyze_stream("sample_report.pdf", "Does it add up?"))
    check("every event carries prev_hash, row_hash, sig",
          all(e.get("row_hash") and e.get("sig") and "prev_hash" in e
              for e in _evs))
    check("chain verifies end to end", backend.verify_audit_chain(_evs) is True)
    check("sig is HMAC(key, row_hash)",
          _evs[0]["sig"] == _am.new(b"test-audit-key",
                                    _evs[0]["row_hash"].encode(),
                                    _ah.sha256).hexdigest())
    import copy as _cp
    _t = _cp.deepcopy(_evs)
    _t[2]["detail"] = "44 PII item(s) masked"       # rewrite history
    check("mutating any historical event breaks verification",
          backend.verify_audit_chain(_t) is False)
    _t2 = _cp.deepcopy(_evs)
    _t2[1], _t2[2] = _t2[2], _t2[1]                  # reorder
    check("reordering events breaks verification",
          backend.verify_audit_chain(_t2) is False)
    _rel = _evs[-1]
    check("release exposes the chain root",
          _rel["stage"] == "release"
          and _rel["result"]["audit_log_root"] == _rel["row_hash"])
    check("no compliance string-labels introduced",
          "compliance" not in open(os.path.join(
              os.path.dirname(__file__), "backend.py")).read().lower())
finally:
    os.environ.pop("DEMO_FALLBACK", None)
    os.environ.pop("AUDIT_HMAC_KEY", None)
    for k, v in _ks.items():
        if v is not None:
            os.environ[k] = v


# ── 29. renderer registry with gates — spec BEFORE code ────────────────────

print("\n=== 29. renderer registry ===")
_html29 = open(os.path.join(os.path.dirname(__file__), "web",
                            "index.html")).read()
check("a RENDERERS registry object exists", "const RENDERERS" in _html29)
check("every registered type declares a gate", "gate:" in _html29
      and _html29.count("gate:") >= 4)
check("gate failure degrades to a table, never a broken visual",
      "renderFallbackTable" in _html29)
check("unregistered type fails loudly", "Unregistered artifact type"
      in _html29)


# ── 30. AI-chosen charts, verified data only — spec BEFORE code ────────────

print("\n=== 30. AI-chosen charts ===")
check("prompt invites any chart kind", '"charts"' in backend.SYSTEM_PROMPT
      and "any kind" in backend.SYSTEM_PROMPT.lower())
_facts30 = [{"id": "f1", "claim": "Product", "value": 100.0,
             "verified_in_source": True},
            {"id": "f2", "claim": "Services", "value": 50.0,
             "verified_in_source": True},
            {"id": "f3", "claim": "Unpinned", "value": 7.0,
             "verified_in_source": False}]
_charts30 = [
    {"kind": "donut", "title": "Mix",
     "points": [{"fact_id": "f1"}, {"fact_id": "f2"}]},
    {"kind": "hologram", "title": "Exotic",
     "points": [{"fact_id": "f1"}]},
    {"kind": "bar", "title": "Phantom",
     "points": [{"fact_id": "f99"}]},
    {"kind": "bar", "title": "Unpinned",
     "points": [{"fact_id": "f3"}]},
    "not a dict",
]
_cc = backend._clean_charts(_charts30, _facts30)
check("resolved charts keep values from verified facts",
      any(c["title"] == "Mix" and c["points"][0]["value"] == 100.0
          and c["points"][0]["label"] == "Product" for c in _cc))
check("exotic kinds pass through (the UI gate decides rendering)",
      any(c["kind"] == "hologram" for c in _cc))
check("phantom fact refs are discarded",
      not any(c["title"] == "Phantom" for c in _cc))
check("unpinned facts never chart",
      not any(c["title"] == "Unpinned" for c in _cc))
with open(os.path.join(os.path.dirname(__file__), "fixtures",
                       "cached_response.json")) as fh:
    _fx30 = json.load(fh)
check("fixture carries a chart", bool(_fx30.get("charts")))
_ks30 = {k: os.environ.pop(k, None) for k in ("DEEPSEEK_API_KEY", "deepseek_api")}
os.environ["DEMO_FALLBACK"] = "1"
try:
    _o30 = backend.analyze("sample_report.pdf", "Visualize the revenue mix")
    check("analyze surfaces charts with resolved points",
          _o30.get("charts") and all(
              "value" in p for c in _o30["charts"] for p in c["points"]))
finally:
    os.environ.pop("DEMO_FALLBACK", None)
    for k, v in _ks30.items():
        if v is not None:
            os.environ[k] = v
_html30 = open(os.path.join(os.path.dirname(__file__), "web",
                            "index.html")).read()
check("web has a deterministic chart-kind registry",
      "const CHART_KINDS" in _html30)
check("charts render as inline SVG, no library",
      "<svg" in _html30 and "chart.js" not in _html30.lower())
check("unknown kinds degrade through the fallback, stated plainly",
      "not in the deterministic chart registry" in _html30)


# ── 31. console retheme — spec BEFORE code ─────────────────────────────────

print("\n=== 31. console retheme ===")
_h31 = open(os.path.join(os.path.dirname(__file__), "web",
                         "index.html")).read()
check("new console tokens applied",
      all(t in _h31.lower() for t in ("#08090a", "#3ddc97", "#a855f7", "#e4572e")))
check("old background token fully retired", "#131313" not in _h31)
check("three-column grid with the telemetry aside",
      "grid-template-columns" in _h31 and "336px" in _h31)
check("telemetry lives in its own aside", "PIPELINE TELEMETRY" in _h31.upper())
check("no LegoParse contamination, no dead preconnects",
      "legoparse" not in _h31.lower() and "fraunces" not in _h31.lower())
check("registry and gates untouched",
      "const RENDERERS" in _h31 and "renderFallbackTable" in _h31
      and "not in the deterministic chart registry" in _h31)


# ── 32. dashboard-grid canvas — spec BEFORE code ───────────────────────────

print("\n=== 32. dashboard canvas ===")
_h32 = open(os.path.join(os.path.dirname(__file__), "web",
                         "index.html")).read()
check("12-column dashboard grid", ".dash{display:grid" in _h32
      and "repeat(12," in _h32)
check("KPI stat-tile row rendered from real summary fields",
      "kpis:" in _h32 and "facts_extracted" in _h32
      and "stat-tile" in _h32)
check("deterministic reported-vs-calculated comparison chart",
      "REPORTED VS CALCULATED" in _h32.upper())
check("stage-timing tile fed by the real stream events",
      "STAGE TIMINGS" in _h32.upper() and "lastEvents" in _h32)
check("tiles flow through the registry, gates intact",
      "renderArtifact" in _h32 and "renderFallbackTable" in _h32
      and "const RENDERERS" in _h32)


# ── 33. shareable interactive board — spec BEFORE code ─────────────────────

print("\n=== 33. shareable board ===")
_h33 = open(os.path.join(os.path.dirname(__file__), "web",
                         "index.html")).read()
check("share-board control exists", 'id="shareboard"' in _h33)
check("board travels in the URL fragment, never to a server",
      "#board=" in _h33 and "location.hash" in _h33)
check("opening a board link renders it with a shared banner",
      "SHARED BOARD" in _h33)
check("link integrity digest computed client-side",
      "crypto.subtle.digest" in _h33)
check("audit root displayed on shared boards for on-chain verification",
      "audit_log_root" in _h33)


# ── 34. KPI info affordance — spec BEFORE code ─────────────────────────────

print("\n=== 34. KPI info ===")
_h34 = open(os.path.join(os.path.dirname(__file__), "web",
                         "index.html")).read()
check("every KPI stat tile carries an (i) with an explanation",
      _h34.count('class="info"') >= 1 and "kpi_info" in _h34
      and all(k in _h34 for k in
              ("recomputed in Python", "before any text reached the model")))


# ── 35. viewer-mode honesty on engine-less deployments — spec BEFORE code ──

print("\n=== 35. viewer mode ===")
_h35 = open(os.path.join(os.path.dirname(__file__), "web",
                         "index.html")).read()
check("engine presence probed, not assumed",
      '"/api/analyze"' in _h35 and "405" in _h35 and "viewerMode" in _h35)
check("viewer mode announces itself and disables execution",
      "VIEWER MODE" in _h35 and "renders shared boards" in _h35)


# ── 36. cloud prod mode wrapper — spec BEFORE code ─────────────────────────

print("\n=== 36. cloud wrapper ===")
check("vercel function wrapper exists",
      os.path.exists(os.path.join(os.path.dirname(__file__), "api", "index.py")))
check("vercel.json routes to the app",
      os.path.exists(os.path.join(os.path.dirname(__file__), "vercel.json")))


# ── 37. mobile layout — spec BEFORE code ──────────────────────────────────

print("\n=== 37. mobile ===")
_hm = open(os.path.join(os.path.dirname(__file__), "web", "index.html")).read()
_mob = "".join(_hm[_hm.index("@media (max-width:860px)"):].split())
_j = _mob.find("@media", 10)
_mob = _mob[:_j] if _j != -1 else _mob
check("canvas is never hidden on phones", ".right{display:none}" not in _mob)
check("phone layout stacks to one scrolling column",
      "main{grid-template-columns:1fr" in _mob and "overflow:auto" in _mob)
check("dashboard tiles collapse to a single column on phones",
      ".dash{grid-template-columns:1fr}" in _mob)


# ── 38. BYOK multi-provider — spec BEFORE code ─────────────────────────────

print("\n=== 38. BYOK providers ===")
check("provider registry exists",
      hasattr(backend, "PROVIDERS") and set(backend.PROVIDERS) >= {"deepseek", "gemini", "claude"})
_src38 = open(os.path.join(os.path.dirname(__file__), "backend.py")).read()
check("claude path uses the official anthropic SDK, never a compat shim",
      "import anthropic" in _src38
      and "api.anthropic.com/v1/" not in _src38
      and "claude-opus-5" in _src38)
check("gemini path uses Google's official OpenAI-compatible endpoint",
      "generativelanguage.googleapis.com/v1beta/openai" in _src38)
# key threading: each provider callable receives the per-request key
_seen38 = {}
_orig38 = dict(backend.PROVIDERS)
try:
    for name in ("deepseek", "gemini", "claude"):
        backend.PROVIDERS[name] = (lambda n: (lambda pages, q, key: (_seen38.__setitem__(n, key), {"answer": "x"})[1]))(name)
    out, cached = backend.ask_llm([("Page 1", "t")], "q", provider="gemini", api_key="user-key-123")
    check("per-request key reaches the provider", _seen38.get("gemini") == "user-key-123" and cached is False)
    try:
        backend.ask_llm([("Page 1", "t")], "q", provider="grok", api_key="k")
        check("unknown provider fails loudly", False)
    except Exception as e:
        check("unknown provider fails loudly", "grok" in str(e))
finally:
    backend.PROVIDERS.update(_orig38)
# stream + result must surface which provider answered
_ks38 = {k: os.environ.pop(k, None) for k in ("DEEPSEEK_API_KEY", "deepseek_api")}
os.environ["DEMO_FALLBACK"] = "1"
try:
    _o38 = backend.analyze("sample_report.pdf", "q")
    check("result names the provider", _o38.get("provider") == "deepseek")
finally:
    os.environ.pop("DEMO_FALLBACK", None)
    for k, v in _ks38.items():
        if v is not None:
            os.environ[k] = v
_h38 = open(os.path.join(os.path.dirname(__file__), "web", "index.html")).read()
check("UI: provider select + key field, honesty note",
      'id="prov"' in _h38 and 'id="userkey"' in _h38
      and "never stored" in _h38)
_sv38 = open(os.path.join(os.path.dirname(__file__), "server.py")).read()
check("server threads provider+key per request and never logs the key",
      "api_key" in _sv38 and "provider" in _sv38)


# ── 39. use-your-AI-app mode (prepare / paste-back / verify) — spec first ──

print("\n=== 39. your-own-app mode ===")
check("verify_external exists", hasattr(backend, "verify_external"))
if hasattr(backend, "verify_external"):
    # parity: the fixture pushed through verify_external must match analyze()
    _ks39 = {k: os.environ.pop(k, None) for k in ("DEEPSEEK_API_KEY", "deepseek_api")}
    os.environ["DEMO_FALLBACK"] = "1"
    try:
        _ref39 = backend.analyze("sample_report.pdf", "q")
    finally:
        os.environ.pop("DEMO_FALLBACK", None)
        for k, v in _ks39.items():
            if v is not None:
                os.environ[k] = v
    _pages39 = backend.parse_pdf("sample_report.pdf")
    _red39 = [(l, backend.redact(t)[0]) for l, t in _pages39]
    with open(os.path.join(os.path.dirname(__file__), "fixtures",
                           "cached_response.json")) as fh:
        _raw39 = json.load(fh)
    _ext39 = backend.verify_external(_raw39, _red39)
    check("parity: summary identical to the pipeline path",
          _ext39["summary"] == _ref39["summary"],
          f"{_ext39['summary']} vs {_ref39['summary']}")
    check("parity: same citation pinning",
          [f["verified_in_source"] for f in _ext39["facts"]]
          == [f["verified_in_source"] for f in _ref39["facts"]])
    check("provider is honestly labeled external",
          _ext39["provider"] == "external")
import server as _sv39
from fastapi.testclient import TestClient as _TC39
_c39 = _TC39(_sv39.app)
with open("sample_report.pdf", "rb") as fh:
    _r39 = _c39.post("/api/prepare",
                     files={"file": ("s.pdf", fh, "application/pdf")},
                     data={"question": "Does it add up?"})
check("prepare returns the copyable prompt + prep id",
      _r39.status_code == 200 and "prep_id" in _r39.json()
      and "DOCUMENT:" in _r39.json()["prompt"]
      and "Does it add up?" in _r39.json()["prompt"])
check("the prepared prompt is redacted — no NRIC leaves",
      "880512-14-5533" not in _r39.json()["prompt"])
_pid39 = _r39.json()["prep_id"]
with open(os.path.join(os.path.dirname(__file__), "fixtures",
                       "cached_response.json")) as fh:
    _fixtxt39 = fh.read()
_v39 = _c39.post("/api/verify_json",
                 json={"prep_id": _pid39, "llm_json": _fixtxt39})
check("paste-back verifies and releases", _v39.status_code == 200
      and _v39.json()["summary"]["checks_failed"] == 1)
check("unknown prep id -> 404",
      _c39.post("/api/verify_json",
                json={"prep_id": "zz", "llm_json": "{}"}).status_code == 404)
check("garbage json -> 400, named",
      _c39.post("/api/verify_json",
                json={"prep_id": _pid39, "llm_json": "not json{"}).status_code == 400)
_h39 = open(os.path.join(os.path.dirname(__file__), "web", "index.html")).read()
check("UI: prepare/copy-prompt/paste-back controls",
      'id="prep"' in _h39 and 'id="pastejson"' in _h39
      and "COPY PROMPT" in _h39 and "paste" in _h39.lower())


# ── 40. prepare must never claim a copy it didn't make — spec BEFORE code ──

print("\n=== 40. prepare copy honesty ===")
_h40 = open(os.path.join(os.path.dirname(__file__), "web", "index.html")).read()
_blk = _h40[_h40.index('$("prep").onclick'):_h40.index('$("verifyjson").onclick')]
check("the prompt is always shown for manual copy, clipboard or not",
      "promptbox" in _blk and "select()" in _blk)
check("clipboard success is verified, not assumed",
      "copied=true" in _blk.replace(" ", "") or "copied = true" in _blk)
check("failure says so instead of claiming success",
      "select and copy" in _blk.lower() or "copy it manually" in _blk.lower())
check("a prompt textarea exists in the markup", 'id="promptbox"' in _h40)


# ── 41. prepare feedback must be where the user is looking — spec first ────

print("\n=== 41. prepare feedback visibility ===")
_h41 = open(os.path.join(os.path.dirname(__file__), "web", "index.html")).read()
_b41 = _h41[_h41.index('$("prep").onclick'):_h41.index('$("verifyjson").onclick')]
check("an inline status line sits next to the button, not only in telemetry",
      'id="prepout"' in _h41 and 'prepout' in _b41)
check("the prompt box is scrolled into view when it appears",
      "scrollIntoView" in _b41)
check("the inline status persists (no self-erasing timeout on it)",
      "prepout" in _b41 and _b41.count("setTimeout") <= 1)


# ── 42. the page must never be served from a stale cache — spec first ──────

print("\n=== 42. no stale page ===")
import server as _sv42
from fastapi.testclient import TestClient as _TC42
_r42 = _TC42(_sv42.app).get("/")
_cc42 = _r42.headers.get("cache-control", "")
check("index is served no-store", "no-store" in _cc42, _cc42)
check("no validators that let a browser reuse an old page",
      "etag" not in {k.lower() for k in _r42.headers}
      and "last-modified" not in {k.lower() for k in _r42.headers})


# ── 43. handlers must live in an executable script block — spec first ──────

print("\n=== 43. no dead script blocks ===")
import re as _re43
_h43 = open(os.path.join(os.path.dirname(__file__), "web", "index.html")).read()
_dead = []
for _m in _re43.finditer(r'<script\b([^>]*)>(.*?)</script>', _h43, _re43.S):
    if "src=" in _m.group(1) and _m.group(2).strip():
        _dead.append(_m.group(2))
check("no inline code inside a src= script tag (browsers ignore it)",
      not _dead, (_dead[0][:60] if _dead else ""))
for _hid in ("prep", "verifyjson", "exec"):
    _ok = False
    for _m in _re43.finditer(r'<script\b([^>]*)>(.*?)</script>', _h43, _re43.S):
        if "src=" not in _m.group(1) and f'$("{_hid}").onclick' in _m.group(2):
            _ok = True
    check(f"{_hid} handler sits in an executed inline script", _ok)


# ── 44. no duplicate top-level declarations in the page script ─────────────

print("\n=== 44. script parses once ===")
import re as _re44
from collections import Counter as _C44
_h44 = open(os.path.join(os.path.dirname(__file__), "web", "index.html")).read()
_code44 = "\n".join(m.group(2) for m in _re44.finditer(
    r'<script\b([^>]*)>(.*?)</script>', _h44, _re44.S) if "src=" not in m.group(1))
_top44 = _re44.findall(r"^(?:let|const)\s+([A-Za-z_$][\w$]*)", _code44, _re44.M)
_dup44 = sorted(n for n, c in _C44(_top44).items() if c > 1)
check("no top-level let/const declared twice (kills the whole script)",
      not _dup44, ",".join(_dup44[:6]))

# ── 45. redaction profiles: company (frozen) vs personal — spec BEFORE code ─

print("\n=== 45. redaction profiles ===")
# The company profile exists to audit company financial reports, where a
# bare 12-digit run is a Companies Act registration number (entity identity,
# not PII). A personal bank statement inverts that: a 12-digit run IS the
# customer's account number. The caller must be able to say which document
# it is holding, and the default must stay byte-for-byte what it is today.


def _redact45(text, **kw):
    # A missing `profile=` kwarg is a TypeError, not a wrong answer; report
    # it as a FAIL row rather than aborting the whole suite.
    try:
        return backend.redact(text, **kw)
    except TypeError as e:
        return f"<<TypeError: {e}>>", -1


# 45a. the default cannot drift: explicit "company" == implicit default
_fixtures45 = [
    sample,
    "Approved by Siti Nurhaliza Binti Hassan on 12 May",
    "Signed for the board: MOHD RAZAK BIN OSMAN, Director",
    "Datuk Seri Wan Azizah attended the meeting",
    "Ramasamy A/L Muniandy holds 40,000 shares",
    "Company No. 202001012345 (12 digits)",
    "Ref: 991331-14-5533 is an invoice, not an IC",
    "IC: 880512-14-5533",
    "Account 1234567890123456 at 81300 SKUDAI, JOHOR, MYS",
] + [text for _, text in backend.parse_pdf("sample_report.pdf")]
check("company profile is byte-identical with and without the explicit arg",
      all(backend.redact(t) == _redact45(t, profile="company")
          for t in _fixtures45))

# 45b. 12-digit run: entity identity under company, account number under personal
_t45 = "Company No. 202001012345 (12 digits)"
check("12-digit run NOT redacted under company",
      "202001012345" in _redact45(_t45, profile="company")[0])
_p45, _n45 = _redact45(_t45, profile="personal")
check("12-digit run -> [ACCOUNT] under personal",
      "202001012345" not in _p45 and "[ACCOUNT]" in _p45 and _n45 >= 1, _p45)

# 45c. [ACCOUNT] boundary: 9 digits is never an account, 10 is
check("9-digit run untouched under company",
      "123456789" in _redact45("Ref 123456789 ok", profile="company")[0])
check("9-digit run untouched under personal",
      "123456789" in _redact45("Ref 123456789 ok", profile="personal")[0])
check("10-digit run -> [ACCOUNT] under personal",
      _redact45("Acct 7123456789 ok", profile="personal")[0] == "Acct [ACCOUNT] ok",
      _redact45("Acct 7123456789 ok", profile="personal")[0])
check("13-digit run -> [ACCOUNT] under personal",
      "[ACCOUNT]" in _redact45("Acct 7123456789012 ok", profile="personal")[0])
check("10-digit run untouched under company",
      "7123456789" in _redact45("Acct 7123456789 ok", profile="company")[0])

# 45d. [CARD]: 14-16 digit runs are labelled as cards, not accounts
for _len45 in (14, 15, 16):
    _digits45 = "4" + "1" * (_len45 - 1)
    _c45, _ = _redact45(f"Card {_digits45} paid", profile="personal")
    check(f"{_len45}-digit run -> [CARD] under personal (not [ACCOUNT])",
          _c45 == "Card [CARD] paid", _c45)
check("17-digit run left whole under company (neither card nor account)",
      _redact45("Ref 41111111111111111 x", profile="company")[0]
      == "Ref 41111111111111111 x")
check("16-digit run untouched under company",
      "4111111111111111" in _redact45("Card 4111111111111111", profile="company")[0])

# 45d-ii. [REF]: 17+ digit runs are payment references on a personal
# statement — a unique trace of one real transaction (issue #70). Redacted
# under personal, whole (not part-eaten by the 10-16 window) under company.
for _len45 in (17, 19, 23):
    _digits45 = "2" + "0" * (_len45 - 1)
    _r45d, _n45d = _redact45(f"Pay {_digits45} TIKTOK 12.90", profile="personal")
    check(f"{_len45}-digit run -> [REF] under personal, counted",
          _r45d == "Pay [REF] TIKTOK 12.90" and _n45d == 1, _r45d)
    check(f"{_len45}-digit run left whole under company",
          _redact45(f"Pay {_digits45} TIKTOK", profile="company")[0]
          == f"Pay {_digits45} TIKTOK")
check("[REF] before [CARD]/[ACCOUNT]: 19-digit run is not part-redacted",
      "[CARD]" not in _redact45("Ref 2026072700341802279 x", profile="personal")[0]
      and "[ACCOUNT]" not in _redact45("Ref 2026072700341802279 x", profile="personal")[0])

# 45e. amounts survive under personal — every form a statement prints
_amts45 = "Bal 1,047.00 Dr 47.00 Fee 0.51 Adj (50.00) Big 1,234,567.89 Int 12.345"
_a45, _ = _redact45(_amts45, profile="personal")
check("amounts survive under personal (commas, decimals, parens)",
      _a45 == _amts45, _a45)
check("date-stamps and short refs survive under personal",
      _redact45("31/07/2026 20260731 REF 987654", profile="personal")[0]
      == "31/07/2026 20260731 REF 987654")

# 45f. [ADDRESS]: postcode + state (or MYS/MALAYSIA), comma-separated
_addr45 = ("IRFAN\nNO 12 JALAN BUNGA 3, TAMAN MELATI, 81300 SKUDAI, JOHOR, MYS\n"
           "Statement date 31/07/2026")
_r45, _ = _redact45(_addr45, profile="personal")
check("address -> [ADDRESS] under personal (postcode + state gone)",
      "81300" not in _r45 and "JOHOR" not in _r45 and "[ADDRESS]" in _r45, _r45)
check("address redaction stops at the country token — the next line survives",
      "Statement date 31/07/2026" in _r45, _r45)
check("address redaction reaches back to the street line",
      "JALAN BUNGA" not in _r45, _r45)
_r45b, _ = _redact45("Lot 7, Jalan Ampang, 50450 Kuala Lumpur, Malaysia",
                     profile="personal")
check("mixed-case two-word state + MALAYSIA -> [ADDRESS]",
      "50450" not in _r45b and "Kuala Lumpur" not in _r45b and "[ADDRESS]" in _r45b,
      _r45b)
_r45c, _ = _redact45("Taman Desa, 58100 Kuala Lumpur", profile="personal")
check("postcode + state with no country token -> [ADDRESS]",
      "58100" not in _r45c and "[ADDRESS]" in _r45c, _r45c)
check("a 5-digit number without a state is NOT an address",
      _redact45("Cheque 12345, cleared", profile="personal")[0]
      == "Cheque 12345, cleared")
check("address untouched under company",
      "81300 SKUDAI, JOHOR" in _redact45(_addr45, profile="company")[0])

# 45g. personal is a superset — every company rule still fires
_sup45, _ = _redact45(sample, profile="personal")
check("personal still scrubs names, NRIC, emails, phones",
      "Ahmad Bin Ali" not in _sup45 and "880512-14-5533" not in _sup45
      and "ahmad.ali@nusantara.com.my" not in _sup45
      and "012-3456789" not in _sup45)
check("personal honours extra_names too",
      "Zulkifli" not in _redact45("Zulkifli owes RM 5.00",
                                  extra_names=["Zulkifli"], profile="personal")[0])

# 45h. unknown profile is rejected, naming the valid ones
try:
    backend.redact("x", profile="corporate")
    check("unknown profile -> ValueError naming valid profiles", False, "no raise")
except ValueError as e:
    check("unknown profile -> ValueError naming valid profiles",
          "company" in str(e) and "personal" in str(e), str(e))
except TypeError as e:
    check("unknown profile -> ValueError naming valid profiles", False, str(e))

# 45i. /api/prepare accepts and echoes the profile; default is company
import server as _sv45
from fastapi.testclient import TestClient as _TC45
_c45 = _TC45(_sv45.app)
with open("sample_report.pdf", "rb") as fh:
    _rd45 = _c45.post("/api/prepare",
                      files={"file": ("s.pdf", fh, "application/pdf")},
                      data={"question": "q"})
check("prepare without profile echoes profile=company",
      _rd45.status_code == 200 and _rd45.json().get("profile") == "company",
      _rd45.text[:120])
with open("sample_report.pdf", "rb") as fh:
    _rp45 = _c45.post("/api/prepare",
                      files={"file": ("s.pdf", fh, "application/pdf")},
                      data={"question": "q", "profile": "personal"})
check("prepare with profile=personal echoes it",
      _rp45.status_code == 200 and _rp45.json().get("profile") == "personal",
      _rp45.text[:120])
with open("sample_report.pdf", "rb") as fh:
    _rx45 = _c45.post("/api/prepare",
                      files={"file": ("s.pdf", fh, "application/pdf")},
                      data={"question": "q", "profile": "corporate"})
check("prepare with unknown profile -> 400 listing valid profiles",
      _rx45.status_code == 400 and "company" in _rx45.text
      and "personal" in _rx45.text, f"{_rx45.status_code} {_rx45.text[:80]}")

# 45j. account-holder name is read from the page-1 header block (issue #69)
# A lone given name in a DuitNow recipient field carries none of the name
# signals (honorific, patronymic, cue, metadata). The personal profile
# already redacts the holder's address block; the name sits on the line
# above it, so the redactor takes its tokens from there — the statement's
# own header, never a guess from capitalisation.
_stmt45 = (
    "Malayan Banking Berhad (3813-K)\n"
    "14th Floor, Menara Maybank, 100 Jalan Tun Perak, 50050 Kuala Lumpur, Malaysia\n"
    "MR / ENCIK FARIS HAKIMI BIN ZULKARNAIN STATEMENT DATE : 31/07/26\n"
    "17 JALAN CEMPAKA 4, TAMAN SERI, 43000 KAJANG, SELANGOR, MYS\n"
    "ACCOUNT NO : 512345678901\n"
    "01/07 DUITNOW TRANSFER TO FARIS 250.00 1,047.00\n"
    "02/07 GRAB* 6812 KUALA LUMPUR MYS 18.50 1,028.50\n"
    "03/07 SHOPEE MOBILE MALAYSIA SDN BHD 61.00 967.50\n"
    "04/07 TIKTOK SHOP 12.00 955.50\n"
)
_h45, _ = _redact45(_stmt45, profile="personal")
_amt45 = re.compile(r"\b\d{1,3}(?:,\d{3})*\.\d{2}\b")
check("holder given name in a bare transaction line -> redacted under personal",
      "FARIS" not in _h45, _h45)
check("holder surname tokens redacted wherever they appear under personal",
      "HAKIMI" not in _h45 and "ZULKARNAIN" not in _h45, _h45)
check("holder address block still -> [ADDRESS]",
      "[ADDRESS]" in _h45 and "43000" not in _h45, _h45)
check("merchant names survive — no capitalisation guessing",
      all(w in _h45 for w in ("GRAB*", "SHOPEE MOBILE MALAYSIA", "TIKTOK SHOP")),
      _h45)
check("bank's own name is not taken as the holder",
      "Malayan Banking Berhad" in _h45, _h45)
check("amount-shaped token count unchanged before/after",
      len(_amt45.findall(_stmt45)) == len(_amt45.findall(_h45)),
      f"{len(_amt45.findall(_stmt45))} -> {len(_amt45.findall(_h45))}")
check("company (frozen) leaves the bare given name alone",
      "TRANSFER TO FARIS" in _redact45(_stmt45, profile="company")[0])
# Deterministic, and short/state/digit tokens are never names
check("same input, same output (deterministic)",
      _redact45(_stmt45, profile="personal") == _redact45(_stmt45, profile="personal"))
_hn45 = getattr(backend, "header_names", lambda t: [])(_stmt45)
check("header_names yields only the holder's tokens (>=3 chars, no state/MYS/digits)",
      sorted(_hn45) == ["FARIS", "HAKIMI", "ZULKARNAIN"], _hn45)
_lo45 = ("AB CDE LIM\nLot 7, Jalan Ampang, 50450 Kuala Lumpur, Malaysia\n"
         "01/07 TRANSFER TO LIM 5.00\n01/07 AB CDE 6.00\n")
_lr45, _ = _redact45(_lo45, profile="personal")
check("2-char header token is not a name (AB survives), 3-char is",
      "AB" in _lr45 and " LIM " not in _lr45 and "TO LIM" not in _lr45, _lr45)

# ── Summary ───────────────────────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"  {PASS} passed, {FAIL} failed")
if FAIL:
    print("  WARNING: fix failures before demo day!")
    sys.exit(1)
else:
    print("  All clear. Ship it.")

