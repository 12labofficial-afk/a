"""Port of masterSheetBlueprint.ts — slices a 1024x1024-style master-sheet atlas into named parts."""
from PIL import Image

# id -> (x, y, w, h) normalized 0..1, copied from src/utils/masterSheetBlueprint.ts
BLUEPRINT_SLOTS = {
    "body": (0.298, 0.003, 0.300, 0.450),
    "head_eyes_closed": (0.003, 0.647, 0.215, 0.170),
    "head_eyes_opened": (0.003, 0.820, 0.215, 0.176),
    "mouth_shape_1": (0.003, 0.270, 0.112, 0.092),
    "mouth_shape_2": (0.003, 0.365, 0.112, 0.092),
    "mouth_shape_3": (0.003, 0.460, 0.112, 0.092),
    "mouth_shape_4": (0.003, 0.555, 0.112, 0.088),
    "right_hand_sword": (0.003, 0.003, 0.287, 0.265),
    "arm_right_upper": (0.223, 0.582, 0.173, 0.210),
    "arm_left_upper": (0.400, 0.582, 0.173, 0.210),
    "forearm_right": (0.220, 0.795, 0.162, 0.203),
    "forearm_left": (0.386, 0.795, 0.160, 0.203),
    "right_palm_3": (0.608, 0.003, 0.219, 0.187),
    "right_palm_2": (0.608, 0.193, 0.219, 0.193),
    "right_palm_1": (0.608, 0.390, 0.219, 0.187),
    "left_palm_3_cup": (0.575, 0.582, 0.252, 0.210),
    "left_palm_2": (0.552, 0.795, 0.220, 0.203),
    "left_palm_1": (0.775, 0.795, 0.220, 0.203),
    "thigh_right": (0.830, 0.003, 0.168, 0.187),
    "leg_lower_right": (0.830, 0.193, 0.168, 0.193),
    "thigh_left": (0.830, 0.390, 0.168, 0.187),
    "leg_lower_left": (0.830, 0.582, 0.168, 0.210),
}


def slice_master_sheet(img: Image.Image) -> dict:
    w, h = img.size
    parts = {}
    for slot_id, (x, y, sw, sh) in BLUEPRINT_SLOTS.items():
        box = (round(x * w), round(y * h), round((x + sw) * w), round((y + sh) * h))
        cropped = img.crop(box)
        bbox = cropped.getbbox()
        if bbox:
            cropped = cropped.crop(bbox)
        parts[slot_id] = cropped
    return parts
