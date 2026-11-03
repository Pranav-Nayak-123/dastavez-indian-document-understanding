"""Generate a synthetic test set: 40 Indian-language notices/forms with known field values.

The documents are rendered from HTML with headless Edge (it shapes Indic scripts correctly)
and saved to testset/ along with ground_truth.json. All people, numbers and dates are made up.

Run:  python make_testset.py
"""
import json
import os
import random
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "testset")
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

# Labels, names and cities per language (code, school/college, notice titles, field labels, body line)
LANG = {
    "hi": dict(
        code="hi-IN", org="राजकीय महाविद्यालय",
        fee=dict(title="शुल्क भुगतान सूचना", name="विद्यार्थी का नाम", roll="रोल नंबर",
                 amount="देय राशि", date="अंतिम तिथि", body="कृपया अंतिम तिथि से पहले शुल्क जमा करें।"),
        exam=dict(title="परीक्षा प्रवेश पत्र", name="परीक्षार्थी का नाम", roll="अनुक्रमांक",
                  date="परीक्षा की तिथि", city="परीक्षा केंद्र (शहर)", body="प्रवेश पत्र के बिना परीक्षा में बैठने की अनुमति नहीं है।"),
        names=["राहुल शर्मा", "प्रिया वर्मा", "अमित कुमार", "सुनीता देवी", "विकास यादव", "नेहा गुप्ता", "रवि सिंह", "पूजा मिश्रा"],
        cities=["जयपुर", "लखनऊ", "पटना", "भोपाल", "इंदौर", "दिल्ली"], n=16),
    "kn": dict(
        code="kn-IN", org="ಸರ್ಕಾರಿ ಕಾಲೇಜು",
        fee=dict(title="ಶುಲ್ಕ ಪಾವತಿ ಸೂಚನೆ", name="ವಿದ್ಯಾರ್ಥಿಯ ಹೆಸರು", roll="ನೋಂದಣಿ ಸಂಖ್ಯೆ",
                 amount="ಪಾವತಿಸಬೇಕಾದ ಮೊತ್ತ", date="ಕೊನೆಯ ದಿನಾಂಕ", body="ದಯವಿಟ್ಟು ಕೊನೆಯ ದಿನಾಂಕದೊಳಗೆ ಶುಲ್ಕ ಪಾವತಿಸಿ."),
        exam=dict(title="ಪರೀಕ್ಷಾ ಪ್ರವೇಶ ಪತ್ರ", name="ಪರೀಕ್ಷಾರ್ಥಿಯ ಹೆಸರು", roll="ನೋಂದಣಿ ಸಂಖ್ಯೆ",
                  date="ಪರೀಕ್ಷಾ ದಿನಾಂಕ", city="ಪರೀಕ್ಷಾ ಕೇಂದ್ರ (ನಗರ)", body="ಪ್ರವೇಶ ಪತ್ರವಿಲ್ಲದೆ ಪರೀಕ್ಷೆ ಬರೆಯಲು ಅನುಮತಿ ಇಲ್ಲ."),
        names=["ರವಿ ಕುಮಾರ್", "ಸುಮಾ ಹೆಗಡೆ", "ಕಿರಣ್ ಗೌಡ", "ಅನಿತಾ ರಾವ್", "ಮಂಜುನಾಥ್ ಶೆಟ್ಟಿ", "ಲಕ್ಷ್ಮಿ ನಾಯಕ್"],
        cities=["ಬೆಂಗಳೂರು", "ಮೈಸೂರು", "ಹುಬ್ಬಳ್ಳಿ", "ಮಂಗಳೂರು", "ಬೆಳಗಾವಿ"], n=12),
    "ta": dict(
        code="ta-IN", org="அரசு கல்லூரி",
        fee=dict(title="கட்டணம் செலுத்துவதற்கான அறிவிப்பு", name="மாணவர் பெயர்", roll="பதிவு எண்",
                 amount="செலுத்த வேண்டிய தொகை", date="கடைசி தேதி", body="கடைசி தேதிக்குள் கட்டணத்தைச் செலுத்தவும்."),
        exam=dict(title="தேர்வு அனுமதிச் சீட்டு", name="தேர்வர் பெயர்", roll="பதிவு எண்",
                  date="தேர்வு தேதி", city="தேர்வு மையம் (நகரம்)", body="அனுமதிச் சீட்டு இல்லாமல் தேர்வு எழுத அனுமதி இல்லை."),
        names=["ராஜேஷ் குமார்", "கவிதா சுந்தரம்", "முருகன் செல்வம்", "பிரியா ராமன்", "அருண் கண்ணன்", "லதா மணி"],
        cities=["சென்னை", "மதுரை", "கோயம்புத்தூர்", "திருச்சி", "சேலம்"], n=12),
}

# Schema keys sent to the extractor, with the kind of comparison used when scoring
TEMPLATES = {
    "fee": {"name": ("student_name", "text"), "roll": ("roll_number", "text"),
            "amount": ("amount_due", "digits"), "date": ("last_date", "digits")},
    "exam": {"name": ("candidate_name", "text"), "roll": ("roll_number", "text"),
             "date": ("exam_date", "digits"), "city": ("centre_city", "text")},
}
QUESTIONS = {
    "amount_due": "How much amount is due?",
    "last_date": "What is the last date to pay the fee?",
    "exam_date": "On what date is the exam?",
    "centre_city": "In which city is the exam centre?",
}

HTML = """<!doctype html><html lang="{lang}"><meta charset="utf-8">
<body style="margin:0;background:#fff;font-family:'Nirmala UI',sans-serif">
<div style="margin:18px;border:3px double #333;padding:22px 28px;height:520px">
<div style="text-align:center;font-size:26px;font-weight:bold">{org}</div>
<div style="text-align:center;font-size:22px;margin:8px 0 4px">{title}</div>
<div style="text-align:right;font-size:15px;color:#444">Ref: {ref}</div>
<hr style="margin:10px 0 18px">
<table style="font-size:21px;width:100%;border-collapse:collapse">{rows}</table>
<p style="font-size:19px;margin-top:26px">{body}</p>
</div></body></html>"""


def render(html, png):
    with tempfile.TemporaryDirectory() as tmp:
        page = os.path.join(tmp, "page.html")
        with open(page, "w", encoding="utf-8") as f:
            f.write(html)
        subprocess.run([EDGE, "--headless", "--disable-gpu", "--hide-scrollbars",
                        f"--user-data-dir={tmp}", f"--screenshot={png}",
                        "--window-size=820,620", "file:///" + page.replace("\\", "/")],
                       check=True, timeout=90, capture_output=True)


def main():
    os.makedirs(OUT, exist_ok=True)
    rng = random.Random(7)
    truth, idx = [], 0
    for lang, cfg in LANG.items():
        for i in range(cfg["n"]):
            tpl = "fee" if i % 2 == 0 else "exam"
            lab = cfg[tpl]
            values = {
                "name": rng.choice(cfg["names"]),
                "roll": f"RV{rng.randint(23, 25)}{rng.randint(10000, 99999)}",
                "amount": rng.choice([8500, 12500, 15000, 21750, 32000, 45500]),
                "date": f"{rng.randint(1, 28):02d}/{rng.randint(1, 12):02d}/2026",
                "city": rng.choice(cfg["cities"]),
            }
            shown = dict(values, amount=f"₹ {values['amount']:,}")
            rows = "".join(
                f"<tr><td style='padding:9px 0;width:48%;color:#222'>{lab[k]}</td>"
                f"<td style='padding:9px 0;font-weight:bold'>{shown[k]}</td></tr>"
                for k in TEMPLATES[tpl])
            fname = f"doc_{idx:02d}_{lang}_{tpl}.png"
            render(HTML.format(lang=lang, org=cfg["org"], title=lab["title"],
                               ref=f"{rng.randint(100, 999)}/2026", rows=rows, body=lab["body"]),
                   os.path.join(OUT, fname))
            fields = {key: (str(values[k]), kind) for k, (key, kind) in TEMPLATES[tpl].items()}
            askable = [k for k in QUESTIONS if k in fields]  # two per template; alternate between them
            qkey = askable[(i // 2) % len(askable)]
            truth.append({"file": fname, "lang": lang, "language_code": cfg["code"], "template": tpl,
                          "fields": {k: {"value": v, "kind": kd} for k, (v, kd) in fields.items()},
                          "question": QUESTIONS[qkey], "answer_field": qkey})
            idx += 1
            print("made", fname)
    with open(os.path.join(OUT, "ground_truth.json"), "w", encoding="utf-8") as f:
        json.dump(truth, f, ensure_ascii=False, indent=1)
    print(f"{len(truth)} documents in {OUT}")


if __name__ == "__main__":
    main()
