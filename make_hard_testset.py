"""Make a harder test set: 18 of the clean documents degraded to look like phone photos.

Each image is tilted, blurred, shrunk and re-enlarged (low resolution), unevenly lit, noisy
and saved as a low-quality JPEG. Ground truth is the same as the clean originals.
Three severity levels (mild / medium / harsh), six documents each.

Run:  python make_hard_testset.py
"""
import json
import os
import random

import numpy as np
from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "testset")
OUT = os.path.join(HERE, "testset_hard")

# (rotation deg, blur radius, resolution scale, noise sigma, JPEG quality, darkest lighting factor)
LEVELS = {
    "mild":   (2.0, 0.8, 0.70, 8, 45, 0.90),
    "medium": (4.0, 1.4, 0.50, 16, 30, 0.78),
    "harsh":  (6.0, 2.0, 0.38, 26, 20, 0.65),
}


def degrade(img, level, rng):
    rot, blur, scale, sigma, _, dark = LEVELS[level]
    w, h = img.size
    img = img.convert("RGB").rotate(rng.uniform(-rot, rot), expand=True, fillcolor=(205, 200, 190), resample=Image.BICUBIC)
    img = img.filter(ImageFilter.GaussianBlur(blur))
    small = img.resize((int(img.width * scale), int(img.height * scale)), Image.BILINEAR)
    img = small.resize((w, h), Image.BILINEAR)
    arr = np.asarray(img).astype(np.float32)
    # uneven lighting: a left-to-right shadow gradient
    shade = np.linspace(1.0, dark, w)[None, :, None]
    arr = arr * (shade if rng.random() < 0.5 else shade[:, ::-1])
    arr += np.random.default_rng(rng.randint(0, 10**6)).normal(0, sigma, arr.shape)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def main():
    os.makedirs(OUT, exist_ok=True)
    truth = json.load(open(os.path.join(SRC, "ground_truth.json"), encoding="utf-8"))
    rng = random.Random(11)
    by_lang = {}
    for t in truth:
        by_lang.setdefault(t["lang"], []).append(t)
    # 6 docs per level: 2 per language (one fee notice, one admit card), different docs per level
    hard = []
    for li, level in enumerate(LEVELS):
        for lang, docs in by_lang.items():
            for tpl in ("fee", "exam"):
                pool = [d for d in docs if d["template"] == tpl]
                t = dict(pool[(li * 2 + 1) % len(pool)])
                name = t["file"].replace(".png", f"_{level}.jpg")
                img = degrade(Image.open(os.path.join(SRC, t["file"])), level, rng)
                img.save(os.path.join(OUT, name), quality=LEVELS[level][4])
                t.update(file=name, level=level)
                hard.append(t)
                print("made", name)
    with open(os.path.join(OUT, "ground_truth.json"), "w", encoding="utf-8") as f:
        json.dump(hard, f, ensure_ascii=False, indent=1)
    print(f"{len(hard)} documents in {OUT}")


if __name__ == "__main__":
    main()
