"""
Loads a character's cutout body-part sprites from a folder.

Two supported input styles, auto-detected per character folder:
  1. Individually exported PNGs, one per body part (the common case for hand-drawn
     rigs like the nurse/boy sheets) — filenames are fuzzy-matched to canonical slot ids.
  2. A single 1024x1024 master-sheet atlas (matching the studio's original blueprint
     layout) — auto-sliced using the known blueprint coordinates.
"""
import os
import re
from PIL import Image

CANONICAL_SLOTS = [
    "body",
    "head_eyes_opened",
    "head_eyes_closed",
    "mouth_shape_1",
    "mouth_shape_2",
    "mouth_shape_3",
    "mouth_shape_4",
    "arm_left_upper",
    "arm_right_upper",
    "forearm_left",
    "forearm_right",
    "hand_left",
    "hand_right",
    "left_palm_1",
    "left_palm_2",
    "left_palm_3",
    "right_palm_1",
    "right_palm_2",
    "right_palm_3",
    "right_hand_prop",
    "thigh_left",
    "thigh_right",
    "leg_lower_left",
    "leg_lower_right",
]

# Matched against the normalized filename stem (lowercased, non-alnum stripped to spaces)
SLOT_KEYWORDS = {
    "body": [["body"], ["torso"], ["saree"], ["dress"]],
    "head_eyes_opened": [["head", "open"], ["face", "open"], ["head"]],
    "head_eyes_closed": [["head", "closed"], ["face", "closed"], ["head", "close"]],
    "mouth_shape_1": [["mouth", "closed"], ["mouth", "1"], ["lip", "closed"]],
    "mouth_shape_2": [["mouth", "2"], ["mouth", "narrow"], ["mouth", "slight"]],
    "mouth_shape_3": [["mouth", "3"], ["mouth", "round"], ["mouth", "medium"]],
    "mouth_shape_4": [["mouth", "4"], ["mouth", "wide"], ["mouth", "open"]],
    "arm_left_upper": [["arm", "left", "upper"], ["left", "upper", "arm"], ["sleeve", "left"]],
    "arm_right_upper": [["arm", "right", "upper"], ["right", "upper", "arm"], ["sleeve", "right"]],
    "forearm_left": [["forearm", "left"], ["left", "lower", "arm"], ["left", "forearm"]],
    "forearm_right": [["forearm", "right"], ["right", "lower", "arm"], ["right", "forearm"]],
    "hand_left": [["left", "hand"], ["left", "palm"]],
    "hand_right": [["right", "hand"], ["right", "palm"]],
    "left_palm_1": [["left", "palm", "1"], ["left", "hand", "1"], ["left", "hand", "open"]],
    "left_palm_2": [["left", "palm", "2"], ["left", "hand", "2"]],
    "left_palm_3": [["left", "cup"], ["left", "mug"], ["left", "palm", "3"], ["left", "hand", "3"]],
    "right_palm_1": [["right", "palm", "1"], ["right", "hand", "1"], ["right", "point"]],
    "right_palm_2": [["right", "palm", "2"], ["right", "hand", "2"]],
    "right_palm_3": [["right", "palm", "3"], ["right", "hand", "3"]],
    "right_hand_prop": [["right", "sword"], ["right", "prop"]],
    "thigh_left": [["thigh", "left"], ["left", "thigh"], ["leg", "upper", "left"]],
    "thigh_right": [["thigh", "right"], ["right", "thigh"], ["leg", "upper", "right"]],
    "leg_lower_left": [["leg", "lower", "left"], ["left", "leg", "lower"], ["left", "shin"], ["left", "foot"], ["left", "leg"]],
    "leg_lower_right": [["leg", "lower", "right"], ["right", "leg", "lower"], ["right", "shin"], ["right", "foot"], ["right", "leg"]],
}

# top-center vs bottom-center pivot for rotation, matching rest-pose direction of each bone.
# Limbs are reliably drawn hanging straight down/up, so a fixed convention works.
PIVOT_AT_TOP = {
    "arm_left_upper", "arm_right_upper", "forearm_left", "forearm_right",
    "thigh_left", "thigh_right", "leg_lower_left", "leg_lower_right",
}
PIVOT_AT_BOTTOM = {"head_eyes_opened", "head_eyes_closed", "body"}

# Hand/gesture art is pre-posed at arbitrary angles (a pointing hand drawn sideways, a fist
# drawn diagonally, ...) so a fixed top/bottom guess is often wrong — the wrist attachment
# point is auto-detected per image instead (see _detect_wrist_pivot).
HAND_SLOTS = {
    "hand_left", "hand_right", "left_palm_1", "left_palm_2", "left_palm_3",
    "right_palm_1", "right_palm_2", "right_palm_3", "right_hand_prop",
}


def _detect_wrist_pivot(img: Image.Image):
    """
    Hands are wide at the palm/fingers and narrow at the wrist, and are not always drawn
    hanging straight down (a pointing hand may be posed at a diagonal). Finds whichever end
    (along the image's longer axis) has the smaller average cross-section, then returns the
    actual pixel centroid of that narrow end (not just the edge midpoint) as the pivot, so a
    wrist sitting off to one side of that end is still located correctly.
    """
    import numpy as np

    alpha = np.array(img.split()[-1]) > 10
    h, w = alpha.shape
    if w == 0 or h == 0 or not alpha.any():
        return (0.5, 0.0)

    def centroid_of(mask_slice, x_offset, y_offset):
        ys, xs = np.nonzero(mask_slice)
        if len(xs) == 0:
            return None
        return ((xs.mean() + x_offset) / w, (ys.mean() + y_offset) / h)

    if w >= h:
        profile = alpha.sum(axis=0)
        q = max(1, w // 4)
        if profile[:q].mean() < profile[-q:].mean():
            return centroid_of(alpha[:, :q], 0, 0) or (0.03, 0.5)
        return centroid_of(alpha[:, -q:], w - q, 0) or (0.97, 0.5)
    else:
        profile = alpha.sum(axis=1)
        q = max(1, h // 4)
        if profile[:q].mean() < profile[-q:].mean():
            return centroid_of(alpha[:q, :], 0, 0) or (0.5, 0.03)
        return centroid_of(alpha[-q:, :], 0, h - q) or (0.5, 0.97)


def _normalize(name: str):
    stem = os.path.splitext(name)[0].lower()
    tokens = re.split(r"[^a-z0-9]+", stem)
    return [tok for tok in tokens if tok]


def _match_slot(tokens):
    best_slot, best_score = None, 0
    for slot, keyword_groups in SLOT_KEYWORDS.items():
        for group in keyword_groups:
            if all(any(kw in tok for tok in tokens) for kw in group):
                score = len(group)
                if score > best_score:
                    best_slot, best_score = slot, score
    return best_slot


def load_character_parts(folder: str) -> dict:
    """Returns {slot_id: PIL.Image (RGBA, alpha-trimmed)}."""
    files = [f for f in os.listdir(folder) if f.lower().endswith((".png", ".webp"))]

    atlas_candidates = [f for f in files if _normalize(f) and ("sheet" in _normalize(f) or "master" in _normalize(f) or "atlas" in _normalize(f))]
    if len(files) == 1 or atlas_candidates:
        atlas_file = atlas_candidates[0] if atlas_candidates else files[0]
        img = Image.open(os.path.join(folder, atlas_file)).convert("RGBA")
        if img.width >= 512 and img.height >= 512:
            from app.rig_autoslice import auto_slice_sheet
            parts = auto_slice_sheet(img)
            if len(parts) >= 8:
                return parts
            from app.rig_blueprint_atlas import slice_master_sheet
            return slice_master_sheet(img)

    parts = {}
    for f in files:
        tokens = _normalize(f)
        slot = _match_slot(tokens)
        if not slot:
            continue
        try:
            img = Image.open(os.path.join(folder, f)).convert("RGBA")
            parts[slot] = _trim_alpha(img)
        except Exception:
            continue
    return parts


def _trim_alpha(img: Image.Image) -> Image.Image:
    bbox = img.getbbox()
    if bbox:
        return img.crop(bbox)
    return img


def get_pivot(slot: str, img: Image.Image = None):
    """Fractional (0..1) pivot point used as the rotation/attachment anchor."""
    if slot in PIVOT_AT_BOTTOM:
        return (0.5, 1.0)
    if slot in HAND_SLOTS and img is not None:
        return _detect_wrist_pivot(img)
    return (0.5, 0.0)
