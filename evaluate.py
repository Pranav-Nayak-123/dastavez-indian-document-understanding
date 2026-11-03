"""Evaluate the document tool on the 40 synthetic documents in testset/.

For each document:
  * extract -> compare the 4 fields with ground truth       (field-extraction accuracy)
  * parse   -> ask one question over the text with sarvam-m  (QA accuracy)

Run:  python evaluate.py            (needs SARVAM_API_KEY; writes results/)
"""
import json
import os
import re
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

import docai
import pipeline

HERE = os.path.dirname(os.path.abspath(__file__))
HARD = "hard" in sys.argv[1:]  # `python evaluate.py hard` runs the degraded phone-photo set
TESTSET = os.path.join(HERE, "testset_hard" if HARD else "testset")
OUT = os.path.join(HERE, "results")
PREFIX = "hard_" if HARD else ""
WORKERS = 3


def canon(value, kind):
    """Normalise a value for comparison: digits-only for numbers/dates, no spaces for text."""
    s = unicodedata.normalize("NFC", str(value))
    if kind == "digits":
        return "".join(str(unicodedata.digit(c)) if c.isdigit() else "" for c in s)
    return re.sub(r"[\s.,:;\-/()]", "", s).lower()


def matches(expected, got, kind):
    return canon(expected, kind) == canon(got, kind)


def run_doc(item):
    """Run one document. Successful runs are cached so an interrupted evaluation can resume."""
    cache = os.path.join(OUT, "cache_hard" if HARD else "cache", item["file"] + ".json")
    if os.path.exists(cache):
        return json.load(open(cache, encoding="utf-8"))
    with open(os.path.join(TESTSET, item["file"]), "rb") as f:
        data = f.read()
    rec = {"file": item["file"], "lang": item["lang"], "template": item["template"]}
    try:
        res = pipeline.analyze(data, item["file"], item["language_code"], item["template"])
        rec["extracted"] = res["fields"]
        rec["text"] = res["text"]
        rec["answer"] = pipeline.ask(res["text"], item["question"])
    except docai.SarvamError as e:
        return dict(rec, error=str(e), extracted={}, text="", answer="")  # not cached: retried next run
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    json.dump(rec, open(cache, "w", encoding="utf-8"), ensure_ascii=False)
    return rec


def main():
    os.makedirs(OUT, exist_ok=True)
    truth = json.load(open(os.path.join(TESTSET, "ground_truth.json"), encoding="utf-8"))
    with ThreadPoolExecutor(WORKERS) as pool:
        runs = list(pool.map(run_doc, truth))

    field_rows, qa_rows, failed = [], [], []
    for item, run in zip(truth, runs):
        if run.get("error"):  # API/network failure, not a wrong answer: leave it out of the scores
            failed.append(item["file"])
            print(f"SKIPPED {item['file']}: {run['error'][:120]}")
            continue
        for key, spec in item["fields"].items():
            got = run["extracted"].get(key, "")
            field_rows.append({"file": item["file"], "lang": item["lang"], "level": item.get("level", "clean"), "field": key,
                               "expected": spec["value"], "got": got,
                               "correct": matches(spec["value"], got, spec["kind"])})
        spec = item["fields"][item["answer_field"]]
        correct = bool(canon(spec["value"], spec["kind"]) and
                       canon(spec["value"], spec["kind"]) in canon(run["answer"], spec["kind"]))
        qa_rows.append({"file": item["file"], "lang": item["lang"], "level": item.get("level", "clean"),
                        "question": item["question"],
                        "expected": spec["value"], "answer": run["answer"], "correct": correct})

    fields, qa = pd.DataFrame(field_rows), pd.DataFrame(qa_rows)
    fields.to_csv(os.path.join(OUT, PREFIX + "field_results.csv"), index=False, encoding="utf-8-sig")
    qa.to_csv(os.path.join(OUT, PREFIX + "qa_results.csv"), index=False, encoding="utf-8-sig")

    summary = {
        "Documents": len(truth) - len(failed),
        "Field extraction accuracy": f"{fields.correct.mean():.1%}",
        "QA accuracy": f"{qa.correct.mean():.1%}",
        "Skipped (API errors)": len(failed),
    }
    if HARD:
        for lvl in ("mild", "medium", "harsh"):
            summary[f"Fields acc. ({lvl})"] = f"{fields[fields.level == lvl].correct.mean():.1%}"
            summary[f"QA acc. ({lvl})"] = f"{qa[qa.level == lvl].correct.mean():.1%}"
    for lang, g in fields.groupby("lang"):
        summary[f"Fields acc. ({lang})"] = f"{g.correct.mean():.1%}"
    for fld, g in fields.groupby("field"):
        summary[f"Field: {fld}"] = f"{g.correct.mean():.1%}"
    with open(os.path.join(OUT, PREFIX + "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\nWrong fields:")
    print(fields[~fields.correct].to_string(index=False))
    print("\nWrong answers:")
    print(qa[~qa.correct][["file", "question", "expected", "answer"]].to_string(index=False))


if __name__ == "__main__":
    main()
