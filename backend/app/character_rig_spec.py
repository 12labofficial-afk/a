"""
Bounding-box + skeleton spec for the per-layer character export (one PNG per named
part, each with its own intrinsic size — not slices cut from one fixed sheet like
sheet_template.py's CELLS). This is the source of truth for:

  - PART_BOUNDING_BOXES: every named layer's own (width, height) in pixels, exactly as
    measured off the source art, grouped the way the export groups them.
  - SKELETON: the bone hierarchy those layers attach to — each bone's parent, its
    length (taken from the attached limb part's own height, since these parts are
    drawn tall-and-narrow along the bone), and which part(s) can be swapped onto it.

Bone convention (matches the rest of the rig): a bone's local origin is its TOP,
hanging straight down its own length to the joint below it — the same "0 rotation =
hangs down" convention already used for arms/legs/hands elsewhere in this codebase.
Left/right below are anatomical (the character's own left/right), not screen sides —
SCREEN_LEFT_PARTS/SCREEN_RIGHT_PARTS in sheet_template.py is the existing pattern for
mapping that onto the viewer's screen.
"""

# --- Bounding boxes, exactly as given, grouped by category -----------------------

PART_BOUNDING_BOXES = {
    "Head": {
        "Head": (216, 347),
    },
    "Eyes": {
        "Left Eyebrow": (60, 11),
        "Right Eyebrow": (46, 12),
        "Left Eyeball": (18, 18),
        "Right Eyeball": (18, 18),
        "White": (104, 18),
        "Eyelids": (126, 30),
    },
    "Lips": {
        "Lips/A": (151, 67),
        "Lips/B": (148, 88),
        "Lips/C": (92, 97),
        "Lips/D": (152, 98),
        "Lips/E": (46, 82),
        "Lips/X": (150, 54),
        "Lips/A_B": (130, 74),
        "Lips/A_C": (134, 94),
        "Lips/A_D_N": (132, 94),
        "Lips/A_D": (129, 106),
        "Lips/A_E": (111, 108),
        "Lips/A_F": (130, 80),
        "Lips/A_X": (112, 46),
    },
    "Hands": {
        "Right Arm": (77, 241),
        "Left Arm": (77, 241),
        "Left Forearm": (60, 183),
        "Right Forearm": (59, 176),
    },
    "Palms": {
        "Left Palm": (57, 100),
        "Left Palm Closed": (141, 162),
        "Palm 1": (250, 98),
        "Palm 2": (93, 234),
        "Palm 3": (132, 209),
        "Palm 4": (132, 230),
        "Palm 5": (248, 169),
        "Palm 6": (123, 181),
        "Palm 7": (123, 243),
        "Palm 8": (153, 224),
        "Palm 9": (132, 243),
        "Palm 10": (196, 177),
        "Palm 11": (141, 264),
        "Palm 12": (133, 188),
        "Palm 13": (119, 232),
        "Palm 14": (147, 160),
        "Palm Mobile": (221, 190),
        "Palm Point": (98, 237),
        "Palm Think": (115, 235),
        "Right Palm": (52, 101),
        "R Palm Strong": (128, 171),
    },
    "Body": {
        "TORSO 2": (816, 1530),
    },
    "Legs": {
        "Left Thigh": (132, 354),
        "Right Thigh": (132, 354),
        "Left Calf": (91, 301),
        "Right Calf": (91, 301),
        "Left Shoe": (109, 104),
        "Right Shoe": (111, 103),
    },
    "Additionals": {
        "Back Hair": (219, 354),
        "L Props": (500, 500),
        "R Props": (500, 500),
        "Hair": (400, 400),
        "Beard": (200, 150),
    },
}


def get_bbox(category: str, name: str):
    return PART_BOUNDING_BOXES[category][name]


# --- Skeleton ----------------------------------------------------------------
# Each bone: (name, parent, length_px, part_ref, swappable_variants)
# length_px is None for bones that are pure joints (no single "this is the bone's
# length" part — e.g. the pelvis/shoulders, whose position instead comes from the
# torso art itself, same as build_geometry() does today for body/shoulder/hip
# landmarks). part_ref points at the PART_BOUNDING_BOXES entry that hangs from
# this bone at rest; swappable_variants lists the other layers that can replace it
# (a pose picks one, same idea as the current selectedLeftHand/selectedRightHand).

SKELETON = [
    # --- core ---
    {"name": "root", "parent": None, "length_px": None, "part": None},
    {"name": "pelvis", "parent": "root", "length_px": None, "part": ("Body", "TORSO 2")},
    {"name": "neck", "parent": "pelvis", "length_px": None, "part": None},
    {"name": "head", "parent": "neck", "length_px": 347, "part": ("Head", "Head")},

    # --- face (all children of "head", positioned within the head's own crop —
    # not separate FK bones, since they don't rotate independently of the head) ---
    {"name": "left_eyebrow", "parent": "head", "length_px": None, "part": ("Eyes", "Left Eyebrow")},
    {"name": "right_eyebrow", "parent": "head", "length_px": None, "part": ("Eyes", "Right Eyebrow")},
    {"name": "left_eyeball", "parent": "head", "length_px": None, "part": ("Eyes", "Left Eyeball")},
    {"name": "right_eyeball", "parent": "head", "length_px": None, "part": ("Eyes", "Right Eyeball")},
    {"name": "eye_white", "parent": "head", "length_px": None, "part": ("Eyes", "White")},
    {"name": "eyelids", "parent": "head", "length_px": None, "part": ("Eyes", "Eyelids")},
    {"name": "mouth", "parent": "head", "length_px": None, "part": ("Lips", "Lips/X"),
     "swappable_variants": [
         "Lips/A", "Lips/B", "Lips/C", "Lips/D", "Lips/E", "Lips/X",
         "Lips/A_B", "Lips/A_C", "Lips/A_D_N", "Lips/A_D", "Lips/A_E", "Lips/A_F", "Lips/A_X",
     ]},
    {"name": "hair", "parent": "head", "length_px": None, "part": ("Additionals", "Hair")},
    {"name": "back_hair", "parent": "head", "length_px": None, "part": ("Additionals", "Back Hair")},
    {"name": "beard", "parent": "head", "length_px": None, "part": ("Additionals", "Beard")},

    # --- left arm ---
    {"name": "shoulder_left", "parent": "pelvis", "length_px": None, "part": None},
    {"name": "upper_arm_left", "parent": "shoulder_left", "length_px": 241, "part": ("Hands", "Left Arm")},
    {"name": "forearm_left", "parent": "upper_arm_left", "length_px": 183, "part": ("Hands", "Left Forearm")},
    {"name": "palm_left", "parent": "forearm_left", "length_px": None, "part": ("Palms", "Left Palm"),
     "swappable_variants": ["Left Palm", "Left Palm Closed", "Palm Mobile", "Palm Point", "Palm Think"]
     + [f"Palm {i}" for i in range(1, 15)]},
    {"name": "prop_left", "parent": "palm_left", "length_px": None, "part": ("Additionals", "L Props")},

    # --- right arm ---
    {"name": "shoulder_right", "parent": "pelvis", "length_px": None, "part": None},
    {"name": "upper_arm_right", "parent": "shoulder_right", "length_px": 241, "part": ("Hands", "Right Arm")},
    {"name": "forearm_right", "parent": "upper_arm_right", "length_px": 176, "part": ("Hands", "Right Forearm")},
    {"name": "palm_right", "parent": "forearm_right", "length_px": None, "part": ("Palms", "Right Palm"),
     "swappable_variants": ["Right Palm", "R Palm Strong", "Palm Mobile", "Palm Point", "Palm Think"]
     + [f"Palm {i}" for i in range(1, 15)]},
    {"name": "prop_right", "parent": "palm_right", "length_px": None, "part": ("Additionals", "R Props")},

    # --- left leg ---
    {"name": "hip_left", "parent": "pelvis", "length_px": None, "part": None},
    {"name": "thigh_left", "parent": "hip_left", "length_px": 354, "part": ("Legs", "Left Thigh")},
    {"name": "calf_left", "parent": "thigh_left", "length_px": 301, "part": ("Legs", "Left Calf")},
    {"name": "shoe_left", "parent": "calf_left", "length_px": None, "part": ("Legs", "Left Shoe")},

    # --- right leg ---
    {"name": "hip_right", "parent": "pelvis", "length_px": None, "part": None},
    {"name": "thigh_right", "parent": "hip_right", "length_px": 354, "part": ("Legs", "Right Thigh")},
    {"name": "calf_right", "parent": "thigh_right", "length_px": 301, "part": ("Legs", "Right Calf")},
    {"name": "shoe_right", "parent": "calf_right", "length_px": None, "part": ("Legs", "Right Shoe")},
]

BONES_BY_NAME = {b["name"]: b for b in SKELETON}


def children_of(bone_name: str):
    return [b["name"] for b in SKELETON if b["parent"] == bone_name]
