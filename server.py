"""FinVerify frontend server — FastAPI.

Serves the self-contained web UI and streams backend.analyze_stream()
as NDJSON so the browser renders the CI pipeline live. The uploaded
file exists on disk only for the duration of the analysis: it is
written to a private temp path and unlinked in a finally block the
moment the stream ends — retention is the length of the request.

Run: uv run uvicorn server:app --port 7861   (or: uv run python server.py)
"""

import json
import os
import tempfile

from fastapi import FastAPI, Form, Request, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse

import backend

app = FastAPI(title="FinVerify")

_WEB = os.path.join(os.path.dirname(__file__), "web", "index.html")


@app.get("/")
def index():
    # The whole app is one HTML file whose JS changes every deploy — a
    # cached copy runs stale handlers against a current server, which
    # looks exactly like "the button does nothing". Never cache it.
    # FileResponse always attaches etag/last-modified, which a browser
    # can revalidate into a 304 and keep the stale page — read and send
    # the bytes directly instead.
    with open(_WEB, encoding="utf-8") as fh:
        return Response(fh.read(), media_type="text/html", headers={
            "Cache-Control": "no-store, must-revalidate",
            "Pragma": "no-cache",
        })


_prepared: dict = {}


@app.post("/api/prepare")
async def prepare(file: UploadFile, question: str = Form(...),
                  profile: str = Form("company")):
    """Use-your-AI-app mode, step 1: parse + redact ONLY — no model call.
    Returns the copyable prompt; the redacted pages are held in-process
    (ephemeral, LRU 20) so the paste-back step can pin citations.

    `profile` picks the redaction profile ("company" default, "personal"
    for bank statements — see backend.REDACTION_PROFILES) and is echoed
    back so the caller can confirm what was applied."""
    import hashlib
    if profile not in backend.REDACTION_PROFILES:
        return Response(
            f"unknown profile {profile!r}; valid profiles: "
            + ", ".join(backend.REDACTION_PROFILES), status_code=400)
    suffix = os.path.splitext(file.filename or "")[1].lower() or ".pdf"
    fd, path = tempfile.mkstemp(prefix="finverify_", suffix=suffix)
    with os.fdopen(fd, "wb") as out:
        out.write(await file.read())
    try:
        pages = backend.parse_file(path)
        if not pages:
            return Response("no text found in the document", status_code=400)
        extra = (backend.pdf_metadata_names(path)
                 if path.lower().endswith(".pdf") else [])
        redacted, total = [], 0
        for label, text in pages:
            clean, n = backend.redact(text, extra, profile=profile)
            redacted.append((label, clean))
            total += n
    except Exception as e:
        return Response(f"could not read that file: {e}", status_code=400)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    prompt = backend.build_external_prompt(redacted, question.strip())
    prep_id = hashlib.sha256(prompt.encode()).hexdigest()[:24]
    _prepared[prep_id] = redacted
    while len(_prepared) > 20:
        _prepared.pop(next(iter(_prepared)))
    return {"prep_id": prep_id, "prompt": prompt, "redaction_count": total,
            "profile": profile}


@app.post("/api/verify_json")
async def verify_json(request: Request):
    """Step 2: the user pastes their app's JSON back; the identical
    deterministic pipeline verifies it."""
    body = await request.json()
    prep_id = str(body.get("prep_id", ""))
    redacted = _prepared.get(prep_id)
    if redacted is None:
        return Response("unknown prep id — prepare the document on this "
                        "server first (preparations are ephemeral)",
                        status_code=404)
    try:
        raw = backend._extract_json(str(body.get("llm_json", "")))
    except Exception:
        return Response("that is not parseable JSON — paste your AI's "
                        "complete JSON reply", status_code=400)
    return backend.verify_external(raw, redacted)


@app.post("/api/analyze")
async def analyze(file: UploadFile, question: str = Form(...),
                  provider: str = Form(""), api_key: str = Form("")):
    # BYOK: provider + key ride this request only — never stored, never
    # logged. Empty means the server's env defaults.
    suffix = os.path.splitext(file.filename or "")[1].lower() or ".pdf"
    fd, path = tempfile.mkstemp(prefix="finverify_", suffix=suffix)
    with os.fdopen(fd, "wb") as out:
        out.write(await file.read())

    def stream():
        try:
            for event in backend.analyze_stream(
                    path, question,
                    provider=(provider or None),
                    api_key=(api_key or None)):
                yield json.dumps(event) + "\n"
        finally:
            # Retention = duration of the request. Nothing to purge later.
            try:
                os.unlink(path)
            except OSError:
                pass

    return StreamingResponse(stream(), media_type="application/x-ndjson")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=7861)
