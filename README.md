# Dastavez: Indian Document Understanding Tool

CS3235 mini-project (Project 3 from the AI4Bharat & BharatGen list). Upload a notice, form or
bill in an Indian language (image or PDF) and the tool will:

1. **Read it**: full-page OCR of Hindi, Kannada, Tamil and other Indian scripts
2. **Pull out key fields**: name, ID number, date, amount, issuing organisation
3. **Summarise it** in plain English
4. **Translate it** into any of 11 languages (Hindi, Kannada, Tamil, Telugu, Marathi, Bengali,
   Gujarati, Malayalam, Punjabi, Odia, English) and download the result
5. **Answer questions** about the document

```
image / PDF ──► Parse (OCR) ──► text ──┬─► Summary (LLM)
            └─► Extract (fields)       ├─► Translate, cell by cell, into a chosen language
                                       └─► Question answering (LLM)
```

## Models

| Step | Model / API | Provider |
|---|---|---|
| OCR + field extraction | Sarvam Vision 2.1 (Document AI) | Sarvam AI (India) |
| Summary and Q&A | `sarvam-105b` | Sarvam AI (India) |
| Translation | Sarvam-Translate v1 | Sarvam AI (India) |

**Deviation from the project brief:** the brief suggests BharatGen Patram and AI4Bharat
IndicTrans2. Patram is a 7.7B-parameter model (15.3 GB of weights) with no hosted endpoint, which
was not practical to run on our hardware and network, so we used Sarvam AI's hosted
document-understanding API instead. All models are still Indian-built. `docai.py` is the only file
that talks to the API, so a local Patram backend could replace it.

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env        # paste your Sarvam key (https://dashboard.sarvam.ai)
python server.py            # opens the website at http://localhost:5050
```
On Windows you can also double-click **`run_app.bat`** (it uses the Anaconda Python).

```bash
python make_testset.py       # (re)generate the 40 clean test documents  (needs Microsoft Edge)
python make_hard_testset.py  # (re)generate the 18 degraded "phone photo" documents
python evaluate.py           # evaluate the clean set  -> results/
python evaluate.py hard      # evaluate the degraded set -> results/hard_*
```

**The website** (`web/`, plain HTML/CSS/JavaScript, no frameworks) is a single page:
a hero, **the tool** (pick a sample or upload; live progress while it reads; then key fields,
a plain-English summary, and tabs for the text, translation, questions and downloads),
**the results** (charts and a failure breakdown read from `results/`), and **how it works**.
`server.py` is a small Flask server that serves the page and wraps `pipeline.py` in a JSON API.
Interrupted evaluations resume from `results/cache*/`; documents that fail because of an API
error are skipped, not scored as wrong.

## Translation feature

After reading a document, open the **Translate** tab, pick a language and press the button.
How it is made reliable (all found by testing, see `pipeline.py`):

- The OCR output is split into table cells and **each cell is translated separately**.
  Sending the whole page at once made Kannada and Tamil output merge lines, drop a line and
  corrupt the table markup.
- **IDs, dates and amounts are never sent to the translator** (ASCII text containing a digit is
  copied as written). In one test the Tamil model turned `02/02/2026` into "October 2, 2026".
- Every translated cell is checked: if its numbers differ from the original, a **⚠ warning** is
  shown.
- Long paragraphs are split at sentence ends, because the API accepts at most 1000 characters.
- `sarvam-translate:v1` is used rather than `mayura:v1`; on the same cells it mistranslated
  "roll number" as "cylinder number" (Tamil) and "fee" as "fare" (English), and mixed in a Telugu word
  in Kannada.

Machine translation can still be imperfect, especially for names.

## Evaluation

**Test sets** (all synthetic: every name, number and date is made up, so ground truth is exact):

- **Clean:** 40 documents in `testset/` (16 Hindi, 12 Kannada, 12 Tamil), two templates
  (fee-payment notice, exam admit card), 4 fields each = 160 fields + 40 questions.
- **Degraded:** 18 phone-photo copies of some of those documents, in `testset_hard/` (58 test cases from 40 unique documents in total), made to look like phone photos: tilted,
  blurred, shrunk and re-enlarged, unevenly lit, noisy, and saved as low-quality JPEG, at three
  severity levels (mild, medium, harsh), 6 documents each.

**Metrics:**
- *Field-extraction accuracy*: fraction of fields that match ground truth (digits-only comparison
  for dates and amounts, so `15000` equals `15,000`; whitespace/punctuation-insensitive for text).
- *QA accuracy*: for each document, one English question (amount due, last date, exam date or exam
  city) answered from the parsed text; correct if the expected value appears in the answer.

### Results

| Test set | Documents | Field-extraction accuracy | QA accuracy |
|---|---|---|---|
| Clean | 40 | **100%** (160 / 160) | **100%** (40 / 40) |
| Degraded, all levels | 18 | **83.3%** (60 / 72) | **88.9%** (16 / 18) |
| &nbsp;&nbsp;mild | 6 | 100% | 100% |
| &nbsp;&nbsp;medium | 6 | 100% | 100% |
| &nbsp;&nbsp;harsh | 6 | **50%** (12 / 24) | **66.7%** (4 / 6) |

On the clean set accuracy is 100% in every language and for every field, and the scoring is
not hiding anything: no field was empty and the only non-identical strings were formatting
differences such as `15000` vs `15,000`. Accuracy only drops on the **harsh** images
(about 6° tilt, heavy blur, a 2.6x resolution loss, strong noise, JPEG quality 20).

### Failure analysis

All 12 wrong fields and both wrong answers are in harsh documents. Reading the raw API output
shows four distinct failure modes (modes 1 to 3 account for all 12 wrong fields: 4 + 3 + 5):

| # | Failure mode | Evidence | Count |
|---|---|---|---|
| 1 | **Single-digit misreads** in blurred numbers | Roll numbers `RV2568829` read as `RVZ168829`, `RV2354833` as `RV2354811`, `RV2589988` as `RV2589968`; amount `32000` read as `12,000`; confusions seen: 3→1, 5→1, 8→6, 2→Z | 4 fields |
| 2 | **Date digits misread (6 read as 4)** | `16/07/2026`→`16/07/2024`, `16/11/2026`→`16/11/2024`, `13/12/2026`→`13/11/2024` | 3 fields |
| 3 | **Label misread, extractor returns null** | Kannada doc 27: OCR read the field labels as unrelated words, so the extractor could not map any field and returned `null` for all four. Tamil doc 39 also returned `null` for the candidate name | 5 fields |
| 4 | **OCR hallucination** (overlaps with 1 and 2) | Tamil doc 38: the parsed text contained a Tirukkural verse, "Dear mother" and a Kannada organisation name that are not on the page. The separate extractor job, which reads the image directly, still got the name and almost all of the roll number | 1 doc |

Observations:

- **Errors are mostly digits, not words.** Names (script-specific) were either read correctly or
  returned as empty; they were never silently misspelt. Roll numbers and dates carry the risk,
  so they should be verified by a person.
- **The model is more likely to refuse than to guess for names**, but it does guess for digits.
  Failures 1 and 2 are *confident wrong answers*, the more dangerous kind.
- **Question answering is only as good as the OCR text.** Both wrong answers come from bad
  parsed text: doc 27 answered with a different city (`ಮಂಗಳೂರು` instead of `ಮೈಸೂರು`) taken from a
  misread header, and doc 38 said "Not found" because the hallucinated text had no date, even
  though the extractor had found a date (with the year misread). Feeding the extracted fields to the question-answering
  step as well would likely fix the doc-38 case; we did not do this, to avoid tuning on our own test set.
- **By language** (all degraded documents): Hindi 87.5%, Kannada 79.2%, Tamil 83.3% field accuracy.
  Each language has only 6 documents (2 harsh), so these differences are within noise.
- **Bug found and fixed:** on one document the parser returned the page as a base64 image
  instead of text, which would have wasted a large number of LLM tokens. `docai.parse` now
  strips those image blobs (the results above were produced before this fix).

### Limitations

- Test documents are synthetic and use only two simple layouts; real notices are messier.
- Only Hindi, Kannada and Tamil were evaluated, although the app accepts 11 languages.
- Question answering is scored by string containment, so it can accept a correct value inside a
  wrong sentence.
- Documents are sent to Sarvam AI's servers; do not upload sensitive personal documents.

## Files

- `server.py`: Flask server and JSON API; `run_app.bat`: Windows launcher
- `web/index.html`, `web/style.css`, `web/app.js`: the website
- `pipeline.py`: parse, extract, summarise, cell-by-cell translation and question answering
- `docai.py`: Sarvam API client (retries, error handling)
- `make_testset.py`, `make_hard_testset.py`: build the two synthetic test sets
- `evaluate.py`: scoring
- `testset/`, `testset_hard/`, `results/`: test documents and evaluation output
