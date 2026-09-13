"""
Loads a character's body-part sprites.

Primary path: one sheet PNG per character, sliced against the blueprint's exact cell
grid (see sheet_template.py / rig_autoslice.py). Fallback path: a folder of separately
exported PNGs, matched to slots by filename.

Slot names are the blueprint's own labels, which are anatomical — "right" is the
character's right, drawn on the viewer's left.
"""
import os
import re
from PIL import Image

from app.sheet_template import CELLS

CANONICAL_SLOTS = list(CELLS.keys())

# Matched against the normalized filename stem (lowercased, non-alnum stripped to spaces)
SLOT_KEYWORDS = {
    "body": [["body"], ["torso"], ["saree"], ["dress"]],
    "head_eyes_opened": [["head", "open"], ["face", "open"], ["head"]],
    "head_eyes_closed": [["head", "closed"], ["face", "closed"], ["head", "close"]],
    "mouth_shape_1": [["mouth", "1"], ["mouth", "closed"], ["lip", "closed"]],
    "mouth_shape_2": [["mouth", "2"]],
    "mouth_shape_3": [["mouth", "3"]],
    "mouth_shape_4": [["mouth", "4"], ["mouth", "wide"], ["mouth", "open"]],
    "arm_right": [["arm", "right"], ["right", "arm"]],
    "arm_left": [["arm", "left"], ["left", "arm"]],
    "hand_right": [["hand", "right"], ["right", "hand"], ["forearm", "right"]],
    "hand_left": [["hand", "left"], ["left", "hand"], ["forearm", "left"]],
    "right_palm_1": [["right", "palm", "1"]],
    "right_palm_2": [["right", "palm", "2"]],
    "right_palm_3": [["right", "palm", "3"]],
    "left_palm_1": [["left", "palm", "1"]],
    "left_palm_2": [["left", "palm", "2"]],
    "left_palm_3": [["left", "palm", "3"]],
    "right_hand_prop": [["right", "prop"], ["right", "holding"], ["right", "sword"]],
    "left_hand_prop": [["left", "prop"], ["left", "holding"], ["left", "cup"], ["left", "mug"]],
    "thigh_right": [["thigh", "right"], ["right", "thigh"]],
    "thigh_left": [["thigh", "left"], ["left", "thigh"]],
    "leg_lower_right": [["leg", "lower", "right"], ["right", "shin"], ["right", "leg"]],
    "leg_lower_left": [["leg", "lower", "left"], ["left", "shin"], ["left", "leg"]],
    "eye_background": [["eye", "background"]],
    "eye_balls": [["eye", "ball"]],
}

# Limbs are drawn hanging straight down from their joint, so a fixed pivot works:
# the blueprint's "arm" cells hold upper arms and its "hand" cells hold forearms.
PIVOT_AT_TOP = {
    "arm_right", "arm_left", "hand_right", "hand_left",
    "thigh_right", "thigh_left", "leg_lower_right", "leg_lower_left",
}
PIVOT_AT_BOTTOM = {"head_eyes_opened", "head_eyes_closed", "body"}

# Palm/prop art is pre-posed at arbitrary angles (a pointing hand drawn sideways, a fist
# drawn diagonally, ...) so a fixed top/bottom guess is often wrong — the wrist attachment
# point is auto-detected per image instead (see _detect_wrist_pivot).
HAND_SLOTS = {
    "right_palm_1", "right_palm_2", "right_palm_3", "right_hand_prop",
    "left_palm_1", "left_palm_2", "left_palm_3", "left_hand_prop",
}


def _detect_wrist_pivot(img: Image.Image):
    """
    The wrist attaches where the hand is a single solid mass (the palm/heel of the
    hand) — that end has a HIGH average cross-section. Splayed or pointing fingers
    make the opposite end of the blob read as sparse/narrow (gaps between fingers,
    or just one finger's width), even though that end is not the attachment point.
    So the pivot is the pixel centroid of whichever end (along the image's longer
    axis) has the LARGER average cross-section, not the smaller one.
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
        if profile[:q].mean() > profile[-q:].mean():
            return centroid_of(alpha[:, :q], 0, 0) or (0.03, 0.5)
        return centroid_of(alpha[:, -q:], w - q, 0) or (0.97, 0.5)
    profile = alpha.sum(axis=1)
    q = max(1, h // 4)
    if profile[:q].mean() > profile[-q:].mean():
        return centroid_of(alpha[:q, :], 0, 0) or (0.5, 0.03)
    return centroid_of(alpha[-q:, :], 0, h - q) or (0.5, 0.97)


def get_hand_bind_offset(img: Image.Image, pivot: tuple) -> float:
    """
    Degrees to add to a hand's rotation so it obeys the same "0 rotation = hangs
    straight down from the pivot" convention every limb sprite is drawn to.

    Palm art (an open hand, a fist, a pointing finger) is usually drawn hanging down
    from its wrist like the forearm above it, but not always — e.g. a fist meant for a
    sideways punch can be drawn rotated ~90° from that. Rotating it by the forearm's
    angle directly then swings it a further 90° off from where the forearm actually
    ends up, making the hand look twisted or disconnected. So this measures which way
    THIS sprite's own mass actually points from its pivot, and returns the correction
    needed to bring it in line with the down-hanging convention before the pose's own
    rotation is added on top.
    """
    import numpy as np

    alpha = np.array(img.split()[-1]) > 10
    h, w = alpha.shape
    if not alpha.any():
        return 0.0
    ys, xs = np.nonzero(alpha)
    cx, cy = xs.mean(), ys.mean()
    px, py = pivot[0] * w, pivot[1] * h
    ux, uy = cx - px, cy - py
    if ux == 0 and uy == 0:
        return 0.0
    import math
    angle_from_down = math.degrees(math.atan2(ux, uy))
    return -angle_from_down


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
            return auto_slice_sheet(img)

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
