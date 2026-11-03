"""Thin client for Sarvam AI: Document AI (parse / extract), chat, and translate."""
import io
import json
import mimetypes
import os
import re
import time
import zipfile

import requests

BASE = "https://api.sarvam.ai"
TERMINAL = {"completed", "partially_completed", "failed", "rejected"}

LANGUAGES = {
    "Hindi": "hi-IN", "Kannada": "kn-IN", "Tamil": "ta-IN", "Telugu": "te-IN",
    "Marathi": "mr-IN", "Bengali": "bn-IN", "Gujarati": "gu-IN", "Malayalam": "ml-IN",
    "Punjabi": "pa-IN", "Odia": "od-IN", "English": "en-IN",
}


class SarvamError(RuntimeError):
    pass


def _headers():
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    except ImportError:
        pass
    key = os.environ.get("SARVAM_API_KEY")
    if not key:
        raise SarvamError("SARVAM_API_KEY is not set. Copy .env.example to .env and add your key.")
    return {"api-subscription-key": key}


def _check(r, what):
    if r.status_code == 402:
        raise SarvamError("Your Sarvam API credits are used up. Add credits or use a new key at dashboard.sarvam.ai.")
    if not r.ok:
        raise SarvamError(f"{what} -> {r.status_code}: {r.text[:300]}")
    return r


def _request(method, path, retries=5, **kw):
    """HTTP call with retry on rate limits, server errors and network drops."""
    last = "no response"
    for attempt in range(retries):
        try:
            r = requests.request(method, BASE + path, headers=_headers(), timeout=(20, 120), **kw)
        except requests.exceptions.RequestException as e:  # timeout, connection reset, DNS...
            last = type(e).__name__
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            last = f"status {r.status_code}"
            time.sleep(2 ** attempt * 2)
            continue
        return _check(r, path)
    raise SarvamError(f"{path} failed after {retries} tries ({last})")


# ---------- Document AI (Sarvam Vision) ----------

def _run_job(op, data, filename, fields, timeout=300):
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    job = _request("POST", f"/doc-ai/v1/job/{op}", files={"file": (filename, data, mime)}, data=fields).json()
    job_id = job["job_id"]
    start = time.time()
    while True:
        st = _request("GET", f"/doc-ai/v1/job/{job_id}/status").json()
        state = str(st.get("status", "")).lower()
        if state in TERMINAL:
            if state in ("failed", "rejected"):
                raise SarvamError(f"{op} job {job_id} {state}: {json.dumps(st)[:300]}")
            return job_id
        if time.time() - start > timeout:
            raise SarvamError(f"{op} job {job_id} timed out")
        time.sleep(3)


def parse(data, filename, language="hi-IN"):
    """Full-page OCR. Returns the document text as Markdown."""
    job_id = _run_job("parse", data, filename, {"language": language, "output_format": "md"})
    dl = _request("GET", f"/doc-ai/v1/job/{job_id}/download-url").json()
    try:
        blob = requests.get(dl["url"], timeout=(20, 120))  # pre-signed URL, no auth header
    except requests.exceptions.RequestException as e:
        raise SarvamError(f"download failed: {type(e).__name__}")
    _check(blob, "download")
    with zipfile.ZipFile(io.BytesIO(blob.content)) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".md")]
        if not names:
            raise SarvamError(f"no Markdown file in parse output: {z.namelist()}")
        text = "\n\n".join(z.read(n).decode("utf-8") for n in sorted(names))
    # the parser sometimes embeds regions it could not read as base64 images; drop them
    return re.sub(r"!\[[^\]]*\]\(data:[^)]*\)", "[image]", text)


def extract(data, filename, schema, language="hi-IN"):
    """Pull the fields described by a JSON schema. Returns a dict."""
    job_id = _run_job("extract", data, filename,
                      {"language": language, "output_format": "json", "schema": json.dumps(schema)})
    return _request("GET", f"/doc-ai/v1/job/{job_id}/results").json().get("result", {})


def make_schema(fields):
    """fields: {name: description} -> JSON schema with string-valued properties."""
    return {"type": "object",
            "properties": {k: {"type": "string", "description": v} for k, v in fields.items()}}


# ---------- text models ----------

def chat(system, user, model="sarvam-105b", max_tokens=4000):
    """Ask the LLM. It is a reasoning model, so part of max_tokens goes on thinking;
    if the answer still gets cut off, retry once with a bigger budget."""
    for budget in (max_tokens, max_tokens * 2):
        data = _request("POST", "/v1/chat/completions", json={
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.2,
            "max_tokens": budget,
        }).json()
        choice = data["choices"][0]
        if choice.get("finish_reason") != "length":
            break
    text = choice["message"]["content"] or ""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def _split(line, limit=900):
    """Split one long line into pieces of at most `limit` characters, preferring sentence ends."""
    pieces = []
    line = line.strip()
    while len(line) > limit:
        cut = max(line.rfind(sep, 0, limit) for sep in (". ", "। ", "? ", "! ", ", ", " "))
        cut = cut + 1 if cut > 0 else limit
        pieces.append(line[:cut].strip())
        line = line[cut:].strip()
    return pieces + [line] if line else pieces


def translate(text, source, target="en-IN", model="sarvam-translate:v1"):
    """Translate text of any length. The API accepts <=1000 characters per call and tends to merge
    lines, so every line is translated on its own and long lines are split at sentence ends."""
    lines_out = []
    for line in text.splitlines():
        done = [_request("POST", "/translate", json={
            "input": piece, "source_language_code": source, "target_language_code": target,
            "model": model}).json()["translated_text"] for piece in _split(line)]
        if done:
            lines_out.append(" ".join(done))
    return "\n".join(lines_out)
