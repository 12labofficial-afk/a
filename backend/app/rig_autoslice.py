"""
Slices a character sheet into named body parts using the blueprint's exact cell
rectangles: detect every piece of art on the sheet, then assign each to the cell whose
rectangle contains it. No tolerance guessing — a part is whatever the artist drew inside
that cell.
"""
import numpy as np
from PIL import Image
from scipy import ndimage

from app.sheet_template import CELLS, MOUTH_SLOTS

MIN_BLOB_AREA_FRAC = 0.00003  # ignores specks and stray copyright-text glyphs


def _find_blobs(img: Image.Image):
    arr = np.array(img)
    mask = arr[:, :, 3] > 10
    labeled, _ = ndimage.label(mask, structure=np.ones((3, 3), dtype=bool))
    W, H = img.width, img.height
    min_area = MIN_BLOB_AREA_FRAC * W * H

    blobs = []
    for label_id, sl in enumerate(ndimage.find_objects(labeled), start=1):
        if sl is None:
            continue
        area = int((labeled[sl] == label_id).sum())
        if area < min_area:
            continue
        y0, y1 = sl[0].start, sl[0].stop
        x0, x1 = sl[1].start, sl[1].stop
        blobs.append({
            "label_id": label_id, "x0": x0, "y0": y0, "x1": x1, "y1": y1,
            "cx": (x0 + x1) / 2 / W, "cy": (y0 + y1) / 2 / H, "area": area,
            "labeled": labeled,
        })
    return blobs


def _crop(img: Image.Image, blob: dict, pad: int = 4) -> Image.Image:
    x0 = max(0, blob["x0"] - pad)
    y0 = max(0, blob["y0"] - pad)
    x1 = min(img.width, blob["x1"] + pad)
    y1 = min(img.height, blob["y1"] + pad)
    crop = np.array(img.crop((x0, y0, x1, y1)))
    neighbours = blob["labeled"][y0:y1, x0:x1]
    crop[(neighbours != blob["label_id"]) & (neighbours != 0)] = 0
    return Image.fromarray(crop)


def _order_mouths_by_openness(parts: dict):
    """The four mouth cells aren't drawn in a guaranteed order, so rank the art by how
    much of it is filled — closed lips are the smallest, a wide open mouth the largest."""
    found = [(slot, parts[slot]) for slot in MOUTH_SLOTS if slot in parts]
    if len(found) < 2:
        return
    ranked = sorted(found, key=lambda item: (np.array(item[1].split()[-1]) > 10).sum())
    for i, (_slot, image) in enumerate(ranked, start=1):
        parts[f"mouth_shape_{i}"] = image


def _verify_eye_state(parts: dict):
    """
    The two head cells differ only at the eyes, so which one is open is decided by
    comparing them rather than trusting the cell labels — the reference sheets draw
    them the opposite way round from how the blueprint labels them.
    """
    a = parts.get("head_eyes_opened")
    b = parts.get("head_eyes_closed")
    if a is None or b is None:
        only = a or b
        if only is not None:
            parts["head_eyes_opened"] = only
            parts["head_eyes_closed"] = only
        return

    size = (max(a.width, b.width), max(a.height, b.height))
    ga = np.array(a.convert("L").resize(size, Image.BILINEAR)).astype(float)
    gb = np.array(b.convert("L").resize(size, Image.BILINEAR)).astype(float)

    changed = np.abs(ga - gb) > 25
    if changed.sum() < 20:
        return  # the two heads are effectively identical; nothing to tell apart

    # Open eyes put a dark pupil right next to bright sclera, so the eye region is much
    # higher contrast than a closed lid's flat skin. (Average brightness doesn't separate
    # them — the bright sclera cancels out the dark pupil.)
    score_a = ga[changed].std(), (ga[changed] < 70).sum()
    score_b = gb[changed].std(), (gb[changed] < 70).sum()
    a_is_open = score_a[0] > score_b[0] if abs(score_a[0] - score_b[0]) > 3 else score_a[1] > score_b[1]
    if not a_is_open:
        parts["head_eyes_opened"], parts["head_eyes_closed"] = b, a


def auto_slice_sheet(img: Image.Image) -> dict:
    img = img.convert("RGBA")
    blobs = _find_blobs(img)

    parts = {}
    for slot, (x0, y0, x1, y1) in CELLS.items():
        inside = [b for b in blobs if x0 <= b["cx"] <= x1 and y0 <= b["cy"] <= y1]
        if inside:
            parts[slot] = _crop(img, max(inside, key=lambda b: b["area"]))

    _order_mouths_by_openness(parts)
    _verify_eye_state(parts)
    return parts
