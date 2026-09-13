"""
Fixed-layout template for the character master-sheet format the user always uses
(single flattened transparent PNG, parts scattered at fixed positions — verified
against two real reference sheets at different resolutions: the same slots land
within ~1% of the same normalized (x/width, y/height) position regardless of the
sheet's pixel resolution).

STRUCTURAL_SLOTS are matched by nearest-centroid to these anchors — these are the
skeletal parts and their position genuinely does not move between sheets.

Hand "gesture" variants (spare palm/fist/prop poses) are NOT forced into fixed
per-slot identities: their exact position/count varies per character, so they are
collected as an interchangeable pool instead (see rig_assets.py).
"""

# slot_id -> (center_x, center_y, box_w, box_h) normalized 0..1, with generous padding
STRUCTURAL_SLOTS = {
    "body": (0.4554, 0.1965, 0.1641, 0.5247),
    "head_eyes_opened": (0.1173, 0.7155, 0.1239, 0.1417),
    "head_eyes_closed": (0.1185, 0.8937, 0.1239, 0.1421),
    "arm_left_upper": (0.3206, 0.6389, 0.0541, 0.1256),
    "arm_right_upper": (0.4883, 0.6403, 0.0702, 0.1074),
    "forearm_left": (0.3097, 0.8763, 0.0494, 0.0966),
    "forearm_right": (0.4695, 0.8571, 0.0402, 0.1068),
    "thigh_left": (0.9172, 0.0658, 0.0738, 0.1276),
    "thigh_right": (0.9224, 0.4580, 0.0745, 0.1299),
    "leg_lower_left": (0.9166, 0.2631, 0.0606, 0.1559),
    "leg_lower_right": (0.9153, 0.6516, 0.0606, 0.1569),
}

# Region (not a single anchor) where the 4 stacked mouth/viseme shapes live —
# openness is measured per-sheet (by alpha pixel area) rather than assumed by position,
# since the artist doesn't always stack them in the same intensity order.
MOUTH_REGION = (0.03, 0.28, 0.12, 0.62)  # xmin, ymin, xmax, ymax normalized

# Everything else with a hand/prop-sized bounding box, outside the regions above,
# is pooled as interchangeable gesture variants (see rig_assets.py: HAND_POOL_MAX_AREA_FRAC etc).
EXCLUDED_REGIONS = [MOUTH_REGION]

MAX_MATCH_DISTANCE = 0.06  # normalized centroid distance beyond which a blob is not considered a match
