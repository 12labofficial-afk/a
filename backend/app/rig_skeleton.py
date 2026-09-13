"""
2D cutout-puppet skeleton, ported from the studio's rigging.ts DEFAULT_SKELETON_HIERARCHY.
Joint coordinates are bind-pose positions in a shared "rig space" (root at 0,0),
y increasing downward (screen/image convention) matching character standing upright:
head_top ~ -230, feet ~ +152.
"""

JOINTS = {
    "root": (0, 0, None),
    "pelvis": (0, -25, "root"),
    "spine_lower": (0, -65, "pelvis"),
    "spine_upper": (0, -110, "spine_lower"),
    "neck": (0, -132, "spine_upper"),
    "head": (0, -180, "neck"),
    "head_top": (0, -230, "head"),
    "shoulder_left": (-38, -120, "spine_upper"),
    "elbow_left": (-38, -72, "shoulder_left"),
    "wrist_left": (-38, -26, "elbow_left"),
    "hand_left": (-38, 10, "wrist_left"),
    "shoulder_right": (38, -120, "spine_upper"),
    "elbow_right": (38, -72, "shoulder_right"),
    "wrist_right": (38, -26, "elbow_right"),
    "hand_right": (38, 10, "wrist_right"),
    "hip_left": (-16, 32, "pelvis"),
    "knee_left": (-16, 82, "hip_left"),
    "ankle_left": (-16, 142, "knee_left"),
    "foot_left": (-16, 152, "ankle_left"),
    "hip_right": (16, 32, "pelvis"),
    "knee_right": (16, 82, "hip_right"),
    "ankle_right": (16, 142, "knee_right"),
    "foot_right": (16, 152, "ankle_right"),
}

# bone: (start_joint, end_joint, attachment_slot_id, zOrder, pivot_at_start)
# pivot_at_start=True -> sprite's own pivot sits at start joint (limbs hanging down from shoulder/hip/neck)
BONES = [
    ("torso", "pelvis", "spine_upper", "body", 30, True),
    ("head", "neck", "head_top", "head_eyes_opened", 50, True),
    ("upper_arm_left", "shoulder_left", "elbow_left", "arm_left_upper", 40, True),
    ("forearm_left", "elbow_left", "wrist_left", "forearm_left", 41, True),
    ("hand_left", "wrist_left", "hand_left", "left_palm_3_cup", 42, True),
    ("upper_arm_right", "shoulder_right", "elbow_right", "arm_right_upper", 60, True),
    ("forearm_right", "elbow_right", "wrist_right", "forearm_right", 61, True),
    ("hand_right", "wrist_right", "hand_right", "right_hand_sword", 62, True),
    ("thigh_left", "hip_left", "knee_left", "thigh_left", 20, True),
    ("lower_leg_left", "knee_left", "foot_left", "leg_lower_left", 21, True),
    ("thigh_right", "hip_right", "knee_right", "thigh_right", 10, True),
    ("lower_leg_right", "knee_right", "foot_right", "leg_lower_right", 11, True),
]

RIG_HEIGHT_UNITS = 230 + 152  # head_top to feet span, used to scale the rig to a target pixel height

# JOINTS coordinates are already absolute positions in shared rig-space (not parent-relative deltas)
BIND_POSITIONS = {j: (x, y) for j, (x, y, _parent) in JOINTS.items()}
