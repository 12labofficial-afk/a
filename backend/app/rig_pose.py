"""Python port of masterSheetRigEngine.ts calculateRigPose — procedural idle/talk/wave sway."""
import math
from dataclasses import dataclass


@dataclass
class RigPose:
    bodyY: float = 0.0
    bodyRotation: float = 0.0
    headRotation: float = 0.0
    headBlinkClosed: bool = False
    rightArmUpperRot: float = 0.0
    rightForearmRot: float = 0.0
    leftArmUpperRot: float = 0.0
    leftForearmRot: float = 0.0
    rightThighRot: float = 0.0
    rightLowerLegRot: float = 0.0
    leftThighRot: float = 0.0
    leftLowerLegRot: float = 0.0
    selectedRightHand: str = "hand_right"
    selectedLeftHand: str = "hand_left"


def calculate_rig_pose(
    t_seconds: float,
    mode: str,
    speed_multiplier: float = 1.0,
    force_blink: bool = False,
    right_hand_prop: str = None,
    left_hand_prop: str = None,
) -> RigPose:
    t = t_seconds * speed_multiplier
    blink_cycle = t_seconds % 3.6
    is_blinking = force_blink or blink_cycle < 0.16

    right_hand = right_hand_prop or "hand_right"
    left_hand = left_hand_prop or "hand_left"

    if mode == "wave":
        wave_freq = t * 6.0
        return RigPose(
            bodyY=math.sin(t * 1.5) * 2,
            bodyRotation=math.sin(t * 1.5) * 1.2,
            headRotation=2 + math.sin(t * 2) * 2,
            headBlinkClosed=is_blinking,
            rightArmUpperRot=-75 + math.sin(wave_freq) * 8,
            rightForearmRot=-35 + math.sin(wave_freq) * 22,
            leftArmUpperRot=8 + math.sin(t * 1.5) * 4,
            leftForearmRot=12 + math.sin(t * 1.5) * 3,
            selectedRightHand=right_hand_prop or "right_palm_2",
            selectedLeftHand=left_hand,
        )

    if mode == "talk":
        talk_freq = t * 3.0
        return RigPose(
            bodyY=math.sin(talk_freq) * 2.5,
            bodyRotation=math.sin(talk_freq * 0.8) * 1.5,
            headRotation=math.sin(talk_freq) * 3.0,
            headBlinkClosed=is_blinking,
            rightArmUpperRot=-12 + math.sin(talk_freq * 1.2) * 10,
            rightForearmRot=25 + math.sin(talk_freq) * 12,
            leftArmUpperRot=10 + math.sin(talk_freq * 0.9) * 8,
            leftForearmRot=20 + math.sin(talk_freq) * 10,
            selectedRightHand=right_hand,
            selectedLeftHand=left_hand,
        )

    if mode == "point":
        return RigPose(
            bodyY=math.sin(t * 2.0) * 1.5,
            bodyRotation=4,
            headRotation=-2,
            headBlinkClosed=is_blinking,
            rightArmUpperRot=-55,
            rightForearmRot=-10,
            leftArmUpperRot=6,
            leftForearmRot=10,
            selectedRightHand=right_hand_prop or "right_palm_1",
            selectedLeftHand=left_hand,
        )

    # idle (default)
    breath_freq = t * 2.0
    return RigPose(
        bodyY=math.sin(breath_freq) * 2.5,
        bodyRotation=math.sin(breath_freq * 0.5) * 0.8,
        headRotation=math.sin(breath_freq * 0.7) * 1.5,
        headBlinkClosed=is_blinking,
        rightArmUpperRot=math.sin(breath_freq) * 3,
        rightForearmRot=math.sin(breath_freq + 0.5) * 2.5,
        leftArmUpperRot=-math.sin(breath_freq) * 3,
        leftForearmRot=-math.sin(breath_freq + 0.5) * 2.5,
        selectedRightHand=right_hand,
        selectedLeftHand=left_hand,
    )
