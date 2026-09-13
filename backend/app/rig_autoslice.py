"""
Auto-slices a single flattened character sheet PNG (parts scattered on transparent
background at fixed positions) into named body-part images, using connected-component
blob detection + nearest-anchor matching against sheet_template.STRUCTURAL_SLOTS.
"""
import numpy as np
from PIL import Image
from scipy import ndimage

from app.sheet_template import STRUCTURAL_SLOTS, MOUTH_REGION, MAX_MATCH_DISTANCE

MIN_BLOB_AREA_FRAC = 0.00003  # ignore specks/anti-aliasing noise and stray text-glyph fragments


def _find_blobs(img: Image.Image):
    arr = np.array(img)
    alpha = arr[:, :, 3]
    mask = alpha > 10
    structure = np.ones((3, 3), dtype=bool)
    labeled, n = ndimage.label(mask, structure=structure)
    slices = ndimage.find_objects(labeled)

    W, H = img.width, img.height
    min_area = MIN_BLOB_AREA_FRAC * W * H
    blobs = []
    for label_id, sl in enumerate(slices, start=1):
        if sl is None:
            continue
        y0, y1 = sl[0].start, sl[0].stop
        x0, x1 = sl[1].start, sl[1].stop
        area = int((labeled[sl] == label_id).sum())
        if area < min_area:
            continue
        cx, cy = (x0 + x1) / 2 / W, (y0 + y1) / 2 / H
        blobs.append({
            "label_id": label_id, "x0": x0, "y0": y0, "x1": x1, "y1": y1,
            "cx": cx, "cy": cy, "area": area, "labeled": labeled,
        })
    return blobs


def _crop_blob(img: Image.Image, blob: dict, pad: int = 4) -> Image.Image:
    x0, y0, x1, y1 = blob["x0"], blob["y0"], blob["x1"], blob["y1"]
    cx0, cy0 = max(0, x0 - pad), max(0, y0 - pad)
    cx1, cy1 = min(img.width, x1 + pad), min(img.height, y1 + pad)
    crop = img.crop((cx0, cy0, cx1, cy1))
    arr = np.array(crop)
    local_labels = blob["labeled"][cy0:cy1, cx0:cx1]
    keep = blob["label_id"]
    arr[(local_labels != keep) & (local_labels != 0)] = 0
    return Image.fromarray(arr)


def _in_region(blob: dict, region) -> bool:
    xmin, ymin, xmax, ymax = region
    return xmin <= blob["cx"] <= xmax and ymin <= blob["cy"] <= ymax


def auto_slice_sheet(img: Image.Image) -> dict:
    img = img.convert("RGBA")
    blobs = _find_blobs(img)
    parts = {}
    used = set()

    # 1. Structural slots: nearest-centroid match
    for slot, (acx, acy, _aw, _ah) in STRUCTURAL_SLOTS.items():
        best_blob, best_dist = None, None
        for b in blobs:
            if id(b) in used:
                continue
            dist = ((b["cx"] - acx) ** 2 + (b["cy"] - acy) ** 2) ** 0.5
            if dist <= MAX_MATCH_DISTANCE and (best_dist is None or dist < best_dist):
                best_blob, best_dist = b, dist
        if best_blob:
            parts[slot] = _crop_blob(img, best_blob)
            used.add(id(best_blob))

    # 2. Mouth region: collect all remaining blobs inside it, rank by pixel area (openness)
    mouth_candidates = [b for b in blobs if id(b) not in used and _in_region(b, MOUTH_REGION)]
    mouth_candidates.sort(key=lambda b: b["area"])
    for i, b in enumerate(mouth_candidates[:4], start=1):
        parts[f"mouth_shape_{i}"] = _crop_blob(img, b)
        used.add(id(b))

    # 3. Everything else hand-prop-sized becomes an interchangeable gesture pool
    hand_pool = []
    for b in blobs:
        if id(b) in used:
            continue
        area_frac = b["area"] / (img.width * img.height)
        if 0.0003 < area_frac < 0.03:
            hand_pool.append(_crop_blob(img, b))

    hand_slot_names = ["right_hand_sword", "right_palm_1", "right_palm_2",
                        "left_palm_3_cup", "left_palm_1", "left_palm_2"]
    for name, img_part in zip(hand_slot_names, hand_pool):
        parts[name] = img_part
    # if fewer gesture variants exist than named slots, reuse whatever was found
    if hand_pool:
        for name in hand_slot_names:
            if name not in parts:
                parts[name] = hand_pool[0]

    return parts
