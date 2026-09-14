"""Procedural idle/talk/wave/point sway.

Hand slot names follow the blueprint's anatomical naming: selectedRightHand holds the
character's right-hand art, which the renderer draws on the viewer's left."""
import math
from dataclasses import dataclass

# (mode, Hindi label) — drives both the one-click preview buttons in the frontend and
# server-side validation of which mode names are real.
POSE_LIBRARY = [
    ("idle", "Idle (khada hua)"),
    ("talk", "Baat karna"),
    ("walk_talk", "Chalte hue baat karna"),
    ("run_talk", "Daudte hue baat karna"),
    ("wave", "Haath hilana (Wave)"),
    ("point", "Ungli se point karna"),
    ("thinking", "Sochna"),
    ("shrug", "Shrug (pata nahi)"),
    ("excited_jump", "Khushi me uchalna"),
    ("laughing", "Hansna"),
    ("sad", "Udaas"),
    ("clapping", "Taali bajana"),
    ("facepalm", "Facepalm"),
    ("scratch_head", "Sar khujana (confused)"),
    ("angry", "Gussa"),
]
POSE_MODES = [m for m, _ in POSE_LIBRARY]


@dataclass
class RigPose:
    bodyY: float = 0.0
    bodyRotation: float = 0.0
    headRotation: float = 0.0
    headBobY: float = 0.0
    headBlinkClosed: bool = False
    rightArmUpperRot: float = 0.0
    rightForearmRot: float = 0.0
    leftArmUpperRot: float = 0.0
    leftForearmRot: float = 0.0
    rightThighRot: float = 0.0
    rightLowerLegRot: float = 0.0
    leftThighRot: float = 0.0
    leftLowerLegRot: float = 0.0
    selectedRightHand: str = "right_palm_1"
    selectedLeftHand: str = "left_palm_1"


def _foot_locked_leg_angles(t, cadence, phase_offset, walk_speed_px, leg_length_px, lift_deg):
    """
    Thigh/lower-leg angles for one leg of a walk cycle whose planted foot actually stays
    put on the ground while the pelvis translates over it, instead of a plain sine that
    swings the foot back and forth with no regard for how fast the body is moving.

    A sine-driven leg (the old approach) always looks fine at one particular walk speed,
    but at any other speed the foot's own back-and-forth swing fights the body's
    translation — most visibly when the swing carries the foot backward on screen while
    the body is still moving forward, which reads as moonwalking. Locking the stance
    foot's world position removes that mismatch outright: during stance the foot's
    position relative to the pelvis is derived directly from how far the pelvis has
    moved since touchdown, so it is exactly stationary on the ground by construction,
    whatever the walk speed is.

    Returns (thigh_deg, lower_leg_deg).
    """
    omega = cadence
    half_period = math.pi / omega
    # Distance the pelvis covers during one stance (or swing) half-cycle. The planted
    # foot's position relative to the pelvis must cover exactly this same distance
    # over the stance half-cycle (not more) for its ABSOLUTE position to stay fixed:
    # rel_x(t) = rel_x(0) - walk_speed*t, so rel_x swings across a total span of
    # exactly this distance, split evenly ahead of and behind the pelvis.
    half_stride = (walk_speed_px * half_period) / 2

    cycle_pos = (t * omega + phase_offset) % (2 * math.pi)
    in_stance = cycle_pos < math.pi

    if in_stance:
        frac = cycle_pos / math.pi  # 0 -> 1 across stance
        rel_x = half_stride * (1 - 2 * frac)
        knee = 4.0
    else:
        frac = (cycle_pos - math.pi) / math.pi  # 0 -> 1 across swing
        ease = (1 - math.cos(math.pi * frac)) / 2
        rel_x = -half_stride + 2 * half_stride * ease
        # A real walk's knee snaps into its bend right after lift-off (for ground
        # clearance) and straightens back out more gradually before the next
        # touchdown — an even peak-in-the-middle sine looks noticeably more
        # mechanical than this. frac**0.5 pulls the peak to roughly a third of
        # the way through swing instead of the halfway point.
        knee = lift_deg * math.sin(math.pi * frac ** 0.5)

    ratio = max(-0.95, min(0.95, rel_x / leg_length_px))
    thigh = math.degrees(math.asin(ratio))
    return thigh, knee


def calculate_rig_pose(
    t_seconds: float,
    mode: str,
    speed_multiplier: float = 1.0,
    force_blink: bool = False,
    right_hand_prop: str = None,
    left_hand_prop: str = None,
    walk_speed_px: float = None,
    leg_length_px: float = None,
) -> RigPose:
    t = t_seconds * speed_multiplier
    blink_cycle = t_seconds % 2.6
    is_blinking = force_blink or blink_cycle < 0.20

    right_hand = right_hand_prop or "right_palm_1"
    left_hand = left_hand_prop or "left_palm_1"

    if mode == "wave":
        wave_freq = t * 6.0
        return RigPose(
            bodyY=math.sin(t * 1.5) * 2,
            bodyRotation=math.sin(t * 1.5) * 1.2,
            headRotation=2 + math.sin(t * 2) * 2,
            headBobY=math.sin(t * 2) * 2,
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
            headBobY=math.sin(talk_freq * 1.3) * 2,
            headBlinkClosed=is_blinking,
            rightArmUpperRot=-12 + math.sin(talk_freq * 1.2) * 10,
            rightForearmRot=25 + math.sin(talk_freq) * 12,
            leftArmUpperRot=10 + math.sin(talk_freq * 0.9) * 8,
            leftForearmRot=20 + math.sin(talk_freq) * 10,
            selectedRightHand=right_hand,
            selectedLeftHand=left_hand,
        )

    if mode == "walk_talk":
        cadence = 4.5
        walk_freq = t * cadence
        leg_r = math.sin(walk_freq)
        leg_l = -leg_r
        talk_freq = t * 3.0
        if walk_speed_px and leg_length_px:
            right_thigh, right_knee = _foot_locked_leg_angles(t, cadence, 0.0, walk_speed_px, leg_length_px, 34.0)
            left_thigh, left_knee = _foot_locked_leg_angles(t, cadence, math.pi, walk_speed_px, leg_length_px, 34.0)
        else:
            right_thigh, right_knee = leg_r * 22, (abs(leg_r) * 34 if leg_r < 0 else 4)
            left_thigh, left_knee = leg_l * 22, (abs(leg_l) * 34 if leg_l < 0 else 4)
        return RigPose(
            bodyY=abs(math.sin(walk_freq)) * -6 + 3,
            bodyRotation=math.sin(walk_freq) * 2,
            headRotation=math.sin(talk_freq) * 3.0 + math.sin(walk_freq * 2) * 1.2,
            headBobY=abs(math.sin(walk_freq)) * -3.5,
            headBlinkClosed=is_blinking,
            # right arm gestures while talking; left arm counter-swings with the stride
            rightArmUpperRot=-20 + math.sin(talk_freq * 1.2) * 18,
            rightForearmRot=30 + math.sin(talk_freq) * 16,
            # The left arm counter-swings with the RIGHT leg (real walk-cycle
            # reference data confirms opposite-side arm and leg move together) —
            # driven directly off right_thigh's own computed curve, not a separate
            # sine, so it stays exactly in phase and shape with however the leg is
            # actually moving (foot-locked stance-then-swing, not a plain sine).
            leftArmUpperRot=right_thigh * 0.6,
            leftForearmRot=max(0, right_thigh * 0.4) + 8,
            rightThighRot=right_thigh,
            rightLowerLegRot=right_knee,
            leftThighRot=left_thigh,
            leftLowerLegRot=left_knee,
            selectedRightHand=right_hand,
            selectedLeftHand=left_hand,
        )

    if mode == "run_talk":
        cadence = 8.0
        run_freq = t * cadence
        leg_r = math.sin(run_freq)
        leg_l = -leg_r
        talk_freq = t * 3.0
        if walk_speed_px and leg_length_px:
            right_thigh, right_knee = _foot_locked_leg_angles(t, cadence, 0.0, walk_speed_px, leg_length_px, 58.0)
            left_thigh, left_knee = _foot_locked_leg_angles(t, cadence, math.pi, walk_speed_px, leg_length_px, 58.0)
        else:
            right_thigh, right_knee = leg_r * 40, (abs(leg_r) * 58 if leg_r < 0 else 8)
            left_thigh, left_knee = leg_l * 40, (abs(leg_l) * 58 if leg_l < 0 else 8)
        return RigPose(
            bodyY=abs(math.sin(run_freq)) * -10 + 5,
            bodyRotation=6 + math.sin(run_freq) * 2,
            headRotation=math.sin(talk_freq) * 2.5,
            headBobY=abs(math.sin(run_freq)) * -5,
            headBlinkClosed=is_blinking,
            rightArmUpperRot=leg_l * 34 - 10,
            rightForearmRot=40 + math.sin(talk_freq) * 10,
            leftArmUpperRot=leg_r * 34 + 10,
            leftForearmRot=max(0, leg_r * 26) + 15,
            rightThighRot=right_thigh,
            rightLowerLegRot=right_knee,
            leftThighRot=left_thigh,
            leftLowerLegRot=left_knee,
            selectedRightHand=right_hand,
            selectedLeftHand=left_hand,
        )

    if mode == "thinking":
        think_freq = t * 1.2
        return RigPose(
            bodyY=math.sin(think_freq) * 1.5,
            bodyRotation=-3,
            headRotation=8 + math.sin(think_freq) * 3,
            headBobY=math.sin(think_freq) * 1.0,
            headBlinkClosed=is_blinking,
            rightArmUpperRot=-95,
            rightForearmRot=-70 + math.sin(think_freq) * 4,
            leftArmUpperRot=-math.sin(think_freq) * 2,
            leftForearmRot=8,
            selectedRightHand=right_hand_prop or "right_palm_2",
            selectedLeftHand=left_hand,
        )

    if mode == "shrug":
        shrug_freq = t * 2.0
        return RigPose(
            bodyY=-4,
            headRotation=math.sin(shrug_freq) * 2,
            headBobY=-1.5,
            headBlinkClosed=is_blinking,
            rightArmUpperRot=-70,
            rightForearmRot=-40,
            leftArmUpperRot=70,
            leftForearmRot=40,
            selectedRightHand=right_hand_prop or "right_palm_2",
            selectedLeftHand=left_hand_prop or "left_palm_2",
        )

    if mode == "excited_jump":
        jump_freq = t * 5.0
        jump = abs(math.sin(jump_freq))
        return RigPose(
            bodyY=-jump * 22,
            bodyRotation=math.sin(jump_freq) * 3,
            headRotation=math.sin(jump_freq * 2) * 3,
            headBobY=-jump * 6,
            headBlinkClosed=is_blinking,
            rightArmUpperRot=-100 + math.sin(jump_freq) * 10,
            rightForearmRot=-20,
            leftArmUpperRot=100 - math.sin(jump_freq) * 10,
            leftForearmRot=20,
            rightThighRot=-jump * 10,
            rightLowerLegRot=jump * 20,
            leftThighRot=-jump * 10,
            leftLowerLegRot=jump * 20,
            selectedRightHand=right_hand_prop or "right_palm_2",
            selectedLeftHand=left_hand_prop or "left_palm_2",
        )

    if mode == "laughing":
        laugh_freq = t * 9.0
        return RigPose(
            bodyY=math.sin(laugh_freq) * 3,
            bodyRotation=math.sin(laugh_freq) * 5,
            headRotation=-10 + math.sin(laugh_freq) * 4,
            headBobY=math.sin(laugh_freq * 2) * 2,
            headBlinkClosed=is_blinking,
            rightArmUpperRot=-30 + math.sin(laugh_freq) * 8,
            rightForearmRot=50,
            leftArmUpperRot=15 + math.sin(laugh_freq + 1) * 6,
            leftForearmRot=25,
            selectedRightHand=right_hand,
            selectedLeftHand=left_hand,
        )

    if mode == "sad":
        sad_freq = t * 1.0
        return RigPose(
            bodyY=2 + math.sin(sad_freq) * 1.0,
            bodyRotation=-2,
            headRotation=14,
            headBobY=2,
            headBlinkClosed=is_blinking,
            rightArmUpperRot=4 + math.sin(sad_freq) * 2,
            rightForearmRot=6,
            leftArmUpperRot=-4 - math.sin(sad_freq) * 2,
            leftForearmRot=-6,
            selectedRightHand=right_hand,
            selectedLeftHand=left_hand,
        )

    if mode == "clapping":
        clap_freq = t * 7.0
        clap = (math.sin(clap_freq) + 1) / 2
        return RigPose(
            bodyY=math.sin(clap_freq * 0.5) * 1.5,
            headRotation=math.sin(clap_freq * 0.5) * 2,
            headBlinkClosed=is_blinking,
            rightArmUpperRot=-30,
            rightForearmRot=40 - clap * 20,
            leftArmUpperRot=30,
            leftForearmRot=-40 + clap * 20,
            selectedRightHand=right_hand,
            selectedLeftHand=left_hand,
        )

    if mode == "facepalm":
        return RigPose(
            bodyY=-2,
            bodyRotation=3,
            headRotation=18,
            headBobY=1.5,
            headBlinkClosed=is_blinking,
            rightArmUpperRot=-105,
            rightForearmRot=-55,
            leftArmUpperRot=6,
            leftForearmRot=10,
            selectedRightHand=right_hand_prop or "right_palm_2",
            selectedLeftHand=left_hand,
        )

    if mode == "scratch_head":
        scratch_freq = t * 6.0
        return RigPose(
            bodyY=math.sin(scratch_freq * 0.4) * 1.5,
            bodyRotation=-2,
            headRotation=-8 + math.sin(scratch_freq * 0.4) * 3,
            headBobY=math.sin(scratch_freq) * 1.2,
            headBlinkClosed=is_blinking,
            rightArmUpperRot=-125,
            rightForearmRot=-80 + math.sin(scratch_freq) * 8,
            leftArmUpperRot=4,
            leftForearmRot=8,
            selectedRightHand=right_hand_prop or "right_palm_1",
            selectedLeftHand=left_hand,
        )

    if mode == "angry":
        angry_freq = t * 10.0
        return RigPose(
            bodyY=math.sin(angry_freq) * 1.0,
            bodyRotation=3 + math.sin(angry_freq) * 1.5,
            headRotation=-3 + math.sin(angry_freq) * 2,
            headBobY=math.sin(angry_freq) * 1.0,
            headBlinkClosed=is_blinking,
            rightArmUpperRot=-15 + math.sin(angry_freq) * 3,
            rightForearmRot=60,
            leftArmUpperRot=15 - math.sin(angry_freq) * 3,
            leftForearmRot=-60,
            selectedRightHand=right_hand_prop or "right_palm_3",
            selectedLeftHand=left_hand_prop or "left_palm_3",
        )

    if mode == "point":
        return RigPose(
            bodyY=math.sin(t * 2.0) * 1.5,
            bodyRotation=4,
            headRotation=-2,
            headBobY=math.sin(t * 2.0) * 1.5,
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
        headBobY=math.sin(breath_freq * 0.7) * 1.8,
        headBlinkClosed=is_blinking,
        rightArmUpperRot=math.sin(breath_freq) * 3,
        rightForearmRot=math.sin(breath_freq + 0.5) * 2.5,
        leftArmUpperRot=-math.sin(breath_freq) * 3,
        leftForearmRot=-math.sin(breath_freq + 0.5) * 2.5,
        selectedRightHand=right_hand,
        selectedLeftHand=left_hand,
    )
