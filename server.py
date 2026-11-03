"""Dastavez: local web server. Serves the website in web/ and a small JSON API around pipeline.py.

Run:  python server.py        (opens http://localhost:5050)
"""
import json
import os
import re
import threading
import time
import uuid
import webbrowser
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
from flask import Flask, abort, jsonify, request, send_from_directory

import docai
import pipeline

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")
TESTSET = os.path.join(HERE, "testset")
RESULTS = os.path.join(HERE, "results")
PORT = 5050
ALLOWED = {".png", ".jpg", ".jpeg", ".pdf"}

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB uploads

JOBS = {}                  # job id -> progress dict
DOCS = OrderedDict()       # doc id -> analysed document (kept in memory, newest 30)
LOCK = threading.Lock()


# ---------- static files ----------

@app.get("/")
def index():
    return send_from_directory(WEB, "index.html")


@app.get("/assets/<path:name>")
def assets(name):
    return send_from_directory(WEB, name)


def sample_list():
    """One fee notice and one admit card per language, in a fixed order."""
    path = os.path.join(TESTSET, "ground_truth.json")
    if not os.path.exists(path):
        return []
    seen, picked = set(), []
    for t in json.load(open(path, encoding="utf-8")):
        if (t["lang"], t["template"]) not in seen:
            seen.add((t["lang"], t["template"]))
            picked.append(t)
    order = {"hi": 0, "kn": 1, "ta": 2}
    picked.sort(key=lambda t: (t["template"] != "fee", order[t["lang"]]))
    return [{"file": t["file"], "language_code": t["language_code"], "template": t["template"]} for t in picked]


@app.get("/samples/<name>")
def sample_file(name):
    if name not in {s["file"] for s in sample_list()} | {"doc_16_kn_fee.png", "doc_28_ta_fee.png"}:
        abort(404)
    return send_from_directory(TESTSET, name)


@app.get("/api/samples")
def api_samples():
    return jsonify(sample_list())


# ---------- analysis ----------

def run_job(job, doc_id, data, name, code):
    steps = job["steps"]
    try:
        with ThreadPoolExecutor(3) as pool:
            f_text = pool.submit(docai.parse, data, name, code)
            f_fields = pool.submit(docai.extract, data, name, docai.make_schema(pipeline.GENERIC_FIELDS), code)
            text = f_text.result()
            steps["text"] = True
            f_sum = pool.submit(pipeline.summarize, text)
            fields = f_fields.result()
            steps["fields"] = True
            summary = f_sum.result()
            steps["summary"] = True
        fields = {k: str(v) for k, v in (fields or {}).items() if v not in (None, "", "null")}
        rows = pipeline.parse_rows(text)
        doc = {"id": doc_id, "name": name, "code": code, "text": text, "rows": rows, "fields": fields, "summary": summary}
        with LOCK:
            DOCS[doc_id] = doc
            while len(DOCS) > 30:
                DOCS.popitem(last=False)
        job.update(status="done", result={k: doc[k] for k in ("id", "name", "code", "rows", "fields", "summary")})
    except docai.SarvamError as e:
        job.update(status="error", error=str(e))
    except Exception as e:  # never leave the page waiting
        job.update(status="error", error=f"Unexpected error: {type(e).__name__}: {str(e)[:200]}")


@app.post("/api/analyze")
def api_analyze():
    code = request.form.get("language_code", "hi-IN")
    if code not in docai.LANGUAGES.values():
        return jsonify(error="Unknown language"), 400
    sample = request.form.get("sample")
    if sample:
        if sample not in {s["file"] for s in sample_list()}:
            return jsonify(error="Unknown sample"), 400
        name = sample
        data = open(os.path.join(TESTSET, sample), "rb").read()
    else:
        f = request.files.get("file")
        if not f or not f.filename:
            return jsonify(error="No file uploaded"), 400
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in ALLOWED:
            return jsonify(error="Please upload a PNG, JPG or PDF file"), 400
        name = re.sub(r"[^\w.\-]+", "_", os.path.basename(f.filename))
        data = f.read()
    job_id, doc_id = uuid.uuid4().hex, uuid.uuid4().hex[:12]
    job = {"status": "running", "steps": {"text": False, "fields": False, "summary": False}}
    JOBS[job_id] = job
    threading.Thread(target=run_job, args=(job, doc_id, data, name, code), daemon=True).start()
    return jsonify(job=job_id)


@app.get("/api/job/<job_id>")
def api_job(job_id):
    job = JOBS.get(job_id)
    if not job:
        abort(404)
    return jsonify(job)


def get_doc(doc_id):
    doc = DOCS.get(doc_id)
    if not doc:
        abort(404)
    return doc


@app.post("/api/translate")
def api_translate():
    body = request.get_json(force=True)
    doc, target = get_doc(body.get("id")), body.get("target")
    if target not in docai.LANGUAGES.values() or target == doc["code"]:
        return jsonify(error="Choose a different target language"), 400
    t0 = time.time()
    try:
        rows = pipeline.translate_rows(doc["rows"], doc["code"], target)
    except docai.SarvamError as e:
        print(f"translate -> {target} FAILED after {time.time() - t0:.1f}s: {e}", flush=True)
        return jsonify(error=str(e)), 502
    print(f"translate -> {target} took {time.time() - t0:.1f}s", flush=True)
    return jsonify(rows=[[{"src": s, "out": o, "ok": ok} for s, o, ok in row] for row in rows])


@app.post("/api/ask")
def api_ask():
    body = request.get_json(force=True)
    doc, question = get_doc(body.get("id")), (body.get("question") or "").strip()[:500]
    if not question:
        return jsonify(error="Type a question first"), 400
    try:
        return jsonify(answer=pipeline.ask(doc["text"], question))
    except docai.SarvamError as e:
        return jsonify(error=str(e)), 502


# ---------- evaluation results ----------

def load_eval(prefix):
    sp = os.path.join(RESULTS, prefix + "summary.json")
    if not os.path.exists(sp):
        return None
    fr = pd.read_csv(os.path.join(RESULTS, prefix + "field_results.csv"))
    qa = pd.read_csv(os.path.join(RESULTS, prefix + "qa_results.csv"))
    out = {"documents": int(qa.shape[0]), "fields": round(fr.correct.mean() * 100, 1),
           "qa": round(qa.correct.mean() * 100, 1), "field_count": int(fr.shape[0]),
           "by_level": {}, "wrong_fields": [], "wrong_qa": []}
    if "level" in fr:
        for lvl in ("mild", "medium", "harsh"):
            f, q = fr[fr.level == lvl], qa[qa.level == lvl]
            if len(f):
                out["by_level"][lvl] = {"fields": round(f.correct.mean() * 100, 1), "qa": round(q.correct.mean() * 100, 1)}
    wf, wq = fr[~fr.correct].fillna(""), qa[~qa.correct].fillna("")
    out["wrong_fields"] = [{k: str(r[k]) for k in ("file", "field", "expected", "got")} for _, r in wf.iterrows()]
    out["wrong_qa"] = [{k: str(r[k]) for k in ("file", "question", "expected", "answer")} for _, r in wq.iterrows()]
    return out


@app.get("/api/results")
def api_results():
    return jsonify(clean=load_eval(""), hard=load_eval("hard_"))


if __name__ == "__main__":
    if not os.environ.get("DASTAVEZ_NO_BROWSER"):
        threading.Timer(1.2, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()
    print(f"Dastavez running at http://localhost:{PORT}  (Ctrl+C to stop)")
    app.run(host="127.0.0.1", port=PORT, threaded=True)
