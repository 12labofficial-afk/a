"""
The character sheet layout, measured 1:1 off the user's own labelled blueprint.

Every sheet follows this exact grid: each named cell is a fixed rectangle and the
artist draws that one part inside it. So slicing is not a guess — a part is whatever
sits inside its cell. Verified against two real sheets at different resolutions
(2048px and 4096px): every cell resolved to exactly one piece of art, with nothing
left over.

Rectangles are normalized (x0, y0, x1, y1) against the sheet's own width/height, so
they hold at any resolution. Names are the blueprint's own labels, which are
anatomical: "right" means the CHARACTER's right, which appears on the viewer's left.
"""

# slot -> (x0, y0, x1, y1) normalized 0..1
CELLS = {
    "right_hand_prop":  (0.0039, 0.0049, 0.2886, 0.2637),   # "right hand palm holding prop -2"
    "body":             (0.2993, 0.0000, 0.5962, 0.4502),
    "right_palm_3":     (0.6074, 0.0068, 0.8262, 0.1929),
    "thigh_right":      (0.8325, 0.0059, 0.9941, 0.1831),
    "right_palm_2":     (0.6074, 0.2002, 0.8262, 0.3853),
    "leg_lower_right":  (0.8340, 0.1909, 0.9946, 0.3906),
    "mouth_shape_1":    (0.0039, 0.2725, 0.1113, 0.3574),
    "left_hand_prop":   (0.1191, 0.2744, 0.2905, 0.5728),   # unlabelled cell, mirrors the right prop
    "mouth_shape_2":    (0.0039, 0.3647, 0.1113, 0.4497),
    "right_palm_1":     (0.6074, 0.3950, 0.8262, 0.5801),
    "thigh_left":       (0.8325, 0.3979, 0.9941, 0.5752),
    "mouth_shape_3":    (0.0044, 0.4575, 0.1123, 0.5420),
    "eye_background":   (0.3018, 0.4590, 0.4438, 0.5747),
    "eye_balls":        (0.4536, 0.4590, 0.5952, 0.5747),
    "mouth_shape_4":    (0.0039, 0.5498, 0.1113, 0.6343),
    "arm_right":        (0.2261, 0.5845, 0.3892, 0.7876),
    "arm_left":         (0.4023, 0.5845, 0.5654, 0.7876),
    "left_palm_3":      (0.5776, 0.5869, 0.7935, 0.7861),
    "leg_lower_left":   (0.8340, 0.5830, 0.9946, 0.7822),
    "head_eyes_closed": (0.0054, 0.6484, 0.2129, 0.8164),
    "hand_right":       (0.2227, 0.7969, 0.3794, 0.9951),
    "hand_left":        (0.3887, 0.7969, 0.5454, 0.9951),
    "left_palm_2":      (0.5537, 0.7964, 0.7695, 0.9941),
    "left_palm_1":      (0.7783, 0.7964, 0.9941, 0.9946),
    "head_eyes_opened": (0.0054, 0.8267, 0.2129, 0.9946),
}

MOUTH_SLOTS = ["mouth_shape_1", "mouth_shape_2", "mouth_shape_3", "mouth_shape_4"]

# Every limb/hand cell also has a short rigging line drawn inside its boundary, on the
# same blueprint the CELLS rectangles were measured from. That line IS the rig for that
# slot: its higher-up end is the pivot (where this part attaches to its parent joint),
# and its own tilt off vertical is the natural bind-pose angle the character's art is
# drawn to hang at in that cell — not necessarily straight down. Measured once directly
# off the blueprint's own line pixels (a farthest-pair scan over the cell's interior,
# with a fixed margin cut on all sides to drop the cell's border stroke and its
# bottom-left slot-name label), so every character sheet built to this same template
# reuses these exact numbers instead of re-guessing a pivot/angle from that character's
# own art — the whole reason the earlier per-image wrist-pivot/bind-angle heuristics in
# rig_assets.py (_detect_wrist_pivot, get_hand_bind_offset) kept misreading art with an
# unusual shape (e.g. a curled fist wider at the knuckles than at the wrist stub).
# "right_hand_prop"/"left_hand_prop" have no such line (their cell shows a small
# checkmark instead) because prop art is deliberately posed at an arbitrary angle per
# character, so those two keep the runtime auto-detection.
# pivot: (x, y) fraction within the slot's own CELLS rectangle.
# bind_angle_deg: degrees this cell's line tilts from straight down (positive = toward
# the viewer's right), i.e. the rotation a pose delta of 0 should render this part at.
SHEET_RIG_LINES = {
    "arm_left":        {"pivot": (0.3623, 0.1058), "bind_angle_deg": 32.50},
    "arm_right":       {"pivot": (0.6168, 0.0481), "bind_angle_deg": -12.04},
    "hand_left":       {"pivot": (0.5312, 0.1136), "bind_angle_deg": -8.33},
    "hand_right":      {"pivot": (0.6137, 0.2321), "bind_angle_deg": -18.03},
    "thigh_left":      {"pivot": (0.5861, 0.0742), "bind_angle_deg": -10.25},
    "thigh_right":     {"pivot": (0.5468, 0.0663), "bind_angle_deg": -9.34},
    "leg_lower_left":  {"pivot": (0.4909, 0.0490), "bind_angle_deg": -8.74},
    "leg_lower_right": {"pivot": (0.4817, 0.0782), "bind_angle_deg": -7.02},
    "right_palm_1":    {"pivot": (0.5568, 0.1421), "bind_angle_deg": -17.80},
    "right_palm_2":    {"pivot": (0.5768, 0.1398), "bind_angle_deg": -12.95},
    "right_palm_3":    {"pivot": (0.5702, 0.0995), "bind_angle_deg": -10.84},
    "left_palm_1":     {"pivot": (0.4977, 0.0914), "bind_angle_deg": 4.17},
    "left_palm_2":     {"pivot": (0.4955, 0.0743), "bind_angle_deg": -5.20},
    "left_palm_3":     {"pivot": (0.5011, 0.0637), "bind_angle_deg": -1.78},
}

# The blueprint's "arm"/"hand" pair is upper arm + forearm; the palms are the hands.
# A front-facing character's right side is drawn on the viewer's left, so the screen-left
# bone chain takes the "right_*" art and vice versa.
SCREEN_LEFT_PARTS = {
    "upper_arm": "arm_right",
    "forearm": "hand_right",
    "thigh": "thigh_right",
    "lower_leg": "leg_lower_right",
}
SCREEN_RIGHT_PARTS = {
    "upper_arm": "arm_left",
    "forearm": "hand_left",
    "thigh": "thigh_left",
    "lower_leg": "leg_lower_left",
}

HAND_VARIANTS_SCREEN_LEFT = ["right_palm_1", "right_palm_2", "right_palm_3", "right_hand_prop"]
HAND_VARIANTS_SCREEN_RIGHT = ["left_palm_1", "left_palm_2", "left_palm_3", "left_hand_prop"]
