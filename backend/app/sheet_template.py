"""
Fixed-layout template for the character master-sheet format the user always uses.
Coordinates below were measured directly off the user's own labeled blueprint/legend
sheet (2048x2048) — each named cell's exact normalized bounding box — so slicing is a
direct crop against known ground truth, not a guess. forearm_left/forearm_right are
not part of the legend itself (the legend only shows one "arm" segment per side) but
real production sheets do draw the forearm as its own piece between "arm" and "hand";
its position is estimated from two real reference sheets and kept generous.
"""

# slot_id -> (center_x, center_y, box_w, box_h) normalized 0..1, with generous padding
STRUCTURAL_SLOTS = {
    "body": (0.4478, 0.2266, 0.3200, 0.4700),
    # NOTE: the blueprint legend's own text labels this pair the other way round, but the
    # two real production sheets checked both draw eyes-open in the UPPER cell and
    # eyes-closed in the LOWER cell — verified by opening both crops directly, not assumed.
    "head_eyes_opened": (0.1091, 0.7327, 0.2250, 0.1850),
    "head_eyes_closed": (0.1094, 0.9106, 0.2250, 0.1850),
    "arm_left_upper": (0.4839, 0.6860, 0.1850, 0.2200),
    "arm_right_upper": (0.3093, 0.6860, 0.1900, 0.2200),
    "thigh_left": (0.9133, 0.4866, 0.1850, 0.1950),
    "thigh_right": (0.9133, 0.0959, 0.1850, 0.1950),
    "leg_lower_left": (0.9143, 0.6829, 0.1850, 0.2200),
    "leg_lower_right": (0.9143, 0.2908, 0.1850, 0.2200),
    # forearm: not in the legend, estimated between "arm" and "hand" cells from real sheets
    "forearm_left": (0.4695, 0.8571, 0.1300, 0.1400),
    "forearm_right": (0.3097, 0.8763, 0.1300, 0.1400),
    # default neutral hand (elbow-down)
    "hand_left": (0.4670, 0.8960, 0.1800, 0.2150),
    "hand_right": (0.3010, 0.8960, 0.1800, 0.2150),
    # alternate hand/gesture variants — exact identities from the legend, not a guessed pool
    "left_palm_3": (0.6855, 0.6865, 0.2350, 0.2150),
    "left_palm_2": (0.6616, 0.8950, 0.2350, 0.2150),
    "left_palm_1": (0.8862, 0.8950, 0.2350, 0.2150),
    "right_palm_3": (0.7168, 0.0999, 0.2400, 0.2050),
    "right_palm_2": (0.7168, 0.2927, 0.2400, 0.2050),
    "right_palm_1": (0.7168, 0.4875, 0.2400, 0.2050),
    "right_hand_prop": (0.1462, 0.1343, 0.3100, 0.2800),
    # optional finer eye detail (only used if a sheet provides separate eye parts)
    "eye_background": (0.3728, 0.5168, 0.1600, 0.1350),
    "eye_balls": (0.5244, 0.5168, 0.1600, 0.1350),
}

# Region where the 4 stacked mouth/viseme shapes live — openness is measured per-sheet
# (by alpha pixel area) rather than assumed by position, since intensity ordering isn't
# guaranteed to be identical across every sheet.
MOUTH_REGION = (0.02, 0.28, 0.14, 0.62)  # xmin, ymin, xmax, ymax normalized

MAX_MATCH_DISTANCE = 0.08  # normalized centroid distance beyond which a blob is not considered a match
