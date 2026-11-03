"""Indian Document Understanding: parse -> extract fields -> summarise -> translate -> answer questions."""
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor

import docai

# What to pull out of any notice / form in the app (key -> description for the extractor)
GENERIC_FIELDS = {
    "document_type": "Kind of document, e.g. fee notice, admit card, bill",
    "organisation": "Name of the issuing organisation or institution, as written",
    "person_name": "Name of the person the document is about, exactly as written",
    "id_number": "Roll number, registration number or any ID number",
    "date": "Any key date on the document, as written",
    "amount": "Any amount of money, digits only",
}

# Per-template fields used by the evaluation (key -> description)
TEMPLATE_FIELDS = {
    "fee": {
        "student_name": "Name of the student, exactly as written in the document's own script",
        "roll_number": "Roll or registration number",
        "amount_due": "Amount due in rupees, digits only",
        "last_date": "Last date for payment, as dd/mm/yyyy",
    },
    "exam": {
        "candidate_name": "Name of the candidate, exactly as written in the document's own script",
        "roll_number": "Roll or registration number",
        "exam_date": "Date of the exam, as dd/mm/yyyy",
        "centre_city": "City of the exam centre, exactly as written in the document's own script",
    },
}

SUMMARY_PROMPT = (
    "You summarise Indian government and college notices. Using ONLY the document text given, "
    "write a 2-3 sentence summary in plain English: who it is for, what it says and any date or amount. "
    "Always write the summary in English, even when the document is in Hindi or another language. "
    "Do not add anything that is not in the document, and do not guess anyone's gender (use names, or 'they')."
)
QA_PROMPT = (
    "Answer the question using ONLY the document text given. Reply with just the answer "
    "(a name, number, date or short phrase), copied as written in the document. "
    "If the answer is not in the document, reply 'Not found'."
)


def analyze(data, filename, language_code, template=None):
    """OCR the document and extract fields. template=None uses the generic field list."""
    fields = TEMPLATE_FIELDS[template] if template else GENERIC_FIELDS
    text = docai.parse(data, filename, language_code)
    extracted = docai.extract(data, filename, docai.make_schema(fields), language_code)
    return {"text": text, "fields": extracted}


def summarize(text):
    return docai.chat(SUMMARY_PROMPT, text)


def ask(text, question):
    return docai.chat(QA_PROMPT, f"Document:\n{text}\n\nQuestion: {question}")


# ---------- document translation ----------
# The OCR text is split into rows of cells. Each cell is translated on its own (translating a whole
# block merges lines and drops content), and cells that are IDs, dates or amounts are kept as written.

def parse_rows(text):
    """OCR Markdown/HTML -> list of rows; each row is a list of cell strings."""
    rows = []
    for m in re.finditer(r"<tr[^>]*>(.*?)</tr>|([^\n]+)", re.sub(r"<(/?)(table|tbody|thead)[^>]*>", "", text), flags=re.S):
        if m.group(1) is not None:
            cells = [" ".join(re.sub(r"<[^>]+>", " ", c).split()) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", m.group(1), flags=re.S)]
            cells = [c for c in cells if c]
            if cells:
                rows.append(cells)
        else:
            line = re.sub(r"<[^>]+>", " ", m.group(2))
            line = " ".join(re.sub(r"^#+\s*", "", line.strip()).split())
            if line and line != "[image]":
                rows.append([line])
    return rows


def _is_protected(cell):
    """ASCII text containing a digit (IDs, dates, amounts, reference numbers) is never translated."""
    return bool(re.search(r"\d", cell)) and all(ord(ch) < 128 or ch == "₹" for ch in cell)


def _numbers(s):
    ascii_digits = "".join(str(unicodedata.digit(c)) if c.isdigit() else c for c in s)
    return sorted(re.findall(r"\d+", ascii_digits))


def translate_rows(rows, source, target):
    """Returns rows of (original, translated, numbers_ok) tuples."""
    unique = sorted({c for r in rows for c in r})

    def one(cell):
        return cell if _is_protected(cell) else docai.translate(cell, source, target)

    with ThreadPoolExecutor(min(10, max(1, len(unique)))) as pool:  # one worker per cell: the API is slow, not rate-limited
        done = dict(zip(unique, pool.map(one, unique)))
    return [[(c, done[c], _numbers(c) == _numbers(done[c])) for c in r] for r in rows]


def rows_to_text(translated):
    return "\n".join(" | ".join(out for _, out, _ in row) for row in translated)
