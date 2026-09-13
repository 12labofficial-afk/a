import math
import os
import subprocess
import numpy as np
from PIL import Image

from app.rig_pose import calculate_rig_pose, RigPose
from app.rig_assets import get_pivot, get_hand_bind_offset
from app.sheet_template import (
    SCREEN_LEFT_PARTS, SCREEN_RIGHT_PARTS,
    HAND_VARIANTS_SCREEN_LEFT, HAND_VARIANTS_SCREEN_RIGHT,
)

def rotate_vec(dx, dy, angle_deg):
    a = math.radians(angle_deg)
    c, s = math.cos(a), math.sin(a)
    return (dx * c - dy * s, dx * s + dy * c)


def _body_landmarks(body: Image.Image):
    """
    Reads the neck, shoulder line and hip width off the torso art itself.

    The torso is drawn with a bare neck stub on top, and how tall that stub is varies a
    lot between characters, so the head has to attach where the shoulders actually start
    rather than at a fixed fraction of the sprite.
    """
    alpha = np.array(body.split()[-1]) > 10
    h, w = alpha.shape
    widths = alpha.sum(axis=1)
    if widths.max() == 0:
        return None

    filled = np.nonzero(widths > 0)[0]
    top, bottom = int(filled[0]), int(filled[-1])
    # the first row that widens out of the neck stub into the shoulders
    shoulder_row = max(int(np.argmax(widths >= 0.55 * widths.max())), top + 1)

    def half_width(row):
        row = min(max(int(row), 0), h - 1)
        xs = np.nonzero(alpha[row])[0]
        return (xs.max() - xs.min()) / 2 if len(xs) else widths.max() / 2

    return {
        "h": h, "w": w, "top": top, "bottom": bottom, "shoulder_row": shoulder_row,
        "shoulder_half": half_width(shoulder_row + 0.03 * h),
        "hip_half": half_width(bottom - 0.05 * h),
    }


def build_geometry(parts: dict) -> dict:
    """
    Derives per-character bind-pose joint positions (native pixel units, pelvis at origin)
    from the art itself — torso landmarks for the neck/shoulders/hips, and each limb
    sprite's own length for the joints below them. Hand-drawn characters differ too much
    in proportion for one shared skeleton to fit them all.
    """
    body = parts.get("body")
    head = parts.get("head_eyes_opened") or parts.get("head_eyes_closed")
    arm_l = parts.get(SCREEN_LEFT_PARTS["upper_arm"])
    arm_r = parts.get(SCREEN_RIGHT_PARTS["upper_arm"])
    fore_l = parts.get(SCREEN_LEFT_PARTS["forearm"])
    fore_r = parts.get(SCREEN_RIGHT_PARTS["forearm"])
    thigh_l = parts.get(SCREEN_LEFT_PARTS["thigh"])
    thigh_r = parts.get(SCREEN_RIGHT_PARTS["thigh"])
    leg_l = parts.get(SCREEN_LEFT_PARTS["lower_leg"])
    leg_r = parts.get(SCREEN_RIGHT_PARTS["lower_leg"])

    bw, bh = body.size if body else (100, 150)
    lm = _body_landmarks(body) if body else None

    # A sprite row r maps to bind y = r - bh, since the torso hangs from its bottom edge.
    pelvis = (0.0, 0.0)
    if lm:
        # leave a quarter of the neck stub showing; the head covers the rest of it
        neck_row = lm["shoulder_row"] - 0.25 * (lm["shoulder_row"] - lm["top"])
        neck = (0.0, neck_row - bh)
        shoulder_y = lm["shoulder_row"] + 0.04 * bh - bh
        shoulder_x = 0.78 * lm["shoulder_half"]
        hip_y = lm["bottom"] - 0.10 * bh - bh
        hip_x = 0.45 * lm["hip_half"]
    else:
        neck = (0.0, -bh * 0.88)
        shoulder_y, shoulder_x = -bh * 0.80, bw * 0.36
        hip_y, hip_x = -bh * 0.10, bw * 0.20

    shoulder_left = (-shoulder_x, shoulder_y)
    shoulder_right = (shoulder_x, shoulder_y)
    hip_left = (-hip_x, hip_y)
    hip_right = (hip_x, hip_y)

    head_h = head.height * 0.92 if head else bh * 0.5
    head_top = (neck[0], neck[1] - head_h)

    # Each piece is shortened a little against its own art so the next one down overlaps
    # it and hides the cut edge, instead of the two just meeting and showing a seam.
    arm_l_len = arm_l.height * 0.75 if arm_l else bh * 0.3
    elbow_left = (shoulder_left[0], shoulder_left[1] + arm_l_len)
    arm_r_len = arm_r.height * 0.75 if arm_r else bh * 0.3
    elbow_right = (shoulder_right[0], shoulder_right[1] + arm_r_len)

    fore_l_len = fore_l.height * 0.78 if fore_l else bh * 0.28
    wrist_left = (elbow_left[0], elbow_left[1] + fore_l_len)
    fore_r_len = fore_r.height * 0.78 if fore_r else bh * 0.28
    wrist_right = (elbow_right[0], elbow_right[1] + fore_r_len)

    hand_left = (wrist_left[0], wrist_left[1] + fore_l_len * 0.04)
    hand_right = (wrist_right[0], wrist_right[1] + fore_r_len * 0.04)

    thigh_l_len = thigh_l.height * 0.72 if thigh_l else 0.0
    knee_left = (hip_left[0], hip_left[1] + thigh_l_len)
    thigh_r_len = thigh_r.height * 0.72 if thigh_r else 0.0
    knee_right = (hip_right[0], hip_right[1] + thigh_r_len)

    leg_l_len = leg_l.height * 0.82 if leg_l else bh * 0.35
    foot_left = (knee_left[0], knee_left[1] + leg_l_len)
    leg_r_len = leg_r.height * 0.82 if leg_r else bh * 0.35
    foot_right = (knee_right[0], knee_right[1] + leg_r_len)

    return {
        "pelvis": pelvis, "spine_upper": neck, "neck": neck, "head_top": head_top,
        "shoulder_left": shoulder_left, "elbow_left": elbow_left, "wrist_left": wrist_left, "hand_left": hand_left,
        "shoulder_right": shoulder_right, "elbow_right": elbow_right, "wrist_right": wrist_right, "hand_right": hand_right,
        "hip_left": hip_left, "knee_left": knee_left, "foot_left": foot_left,
        "hip_right": hip_right, "knee_right": knee_right, "foot_right": foot_right,
    }


def compute_limb_points(pose: RigPose, bind: dict):
    """Forward-kinematics: bone world offsets from a pelvis at (0,0), in this character's own pixel units."""
    b = bind

    def off(a, c):
        return (b[c][0] - b[a][0], b[c][1] - b[a][1])

    pts = {"pelvis": (0.0, pose.bodyY)}

    dx, dy = rotate_vec(*off("pelvis", "spine_upper"), pose.bodyRotation)
    pts["spine_upper"] = (pts["pelvis"][0] + dx, pts["pelvis"][1] + dy)

    dx, dy = rotate_vec(*off("pelvis", "neck"), pose.bodyRotation)
    # headBobY only nudges where the head sprite attaches (the "head" bone's world_pt is
    # this same "neck" point) — the torso/shoulders/hips read off pelvis instead, so this
    # doesn't disturb them.
    pts["neck"] = (pts["pelvis"][0] + dx, pts["pelvis"][1] + dy + pose.headBobY)

    head_angle = pose.bodyRotation + pose.headRotation
    dx, dy = rotate_vec(*off("neck", "head_top"), head_angle)
    pts["head_top"] = (pts["neck"][0] + dx, pts["neck"][1] + dy)

    dx, dy = rotate_vec(*off("pelvis", "shoulder_left"), pose.bodyRotation)
    pts["shoulder_left"] = (pts["pelvis"][0] + dx, pts["pelvis"][1] + dy)
    upper_l = pose.bodyRotation + pose.leftArmUpperRot
    dx, dy = rotate_vec(*off("shoulder_left", "elbow_left"), upper_l)
    pts["elbow_left"] = (pts["shoulder_left"][0] + dx, pts["shoulder_left"][1] + dy)
    fore_l = upper_l + pose.leftForearmRot
    dx, dy = rotate_vec(*off("elbow_left", "wrist_left"), fore_l)
    pts["wrist_left"] = (pts["elbow_left"][0] + dx, pts["elbow_left"][1] + dy)
    dx, dy = rotate_vec(*off("wrist_left", "hand_left"), fore_l)
    pts["hand_left"] = (pts["wrist_left"][0] + dx, pts["wrist_left"][1] + dy)

    dx, dy = rotate_vec(*off("pelvis", "shoulder_right"), pose.bodyRotation)
    pts["shoulder_right"] = (pts["pelvis"][0] + dx, pts["pelvis"][1] + dy)
    upper_r = pose.bodyRotation + pose.rightArmUpperRot
    dx, dy = rotate_vec(*off("shoulder_right", "elbow_right"), upper_r)
    pts["elbow_right"] = (pts["shoulder_right"][0] + dx, pts["shoulder_right"][1] + dy)
    fore_r = upper_r + pose.rightForearmRot
    dx, dy = rotate_vec(*off("elbow_right", "wrist_right"), fore_r)
    pts["wrist_right"] = (pts["elbow_right"][0] + dx, pts["elbow_right"][1] + dy)
    dx, dy = rotate_vec(*off("wrist_right", "hand_right"), fore_r)
    pts["hand_right"] = (pts["wrist_right"][0] + dx, pts["wrist_right"][1] + dy)

    dx, dy = off("pelvis", "hip_left")
    pts["hip_left"] = (pts["pelvis"][0] + dx, pts["pelvis"][1] + dy)
    dx, dy = rotate_vec(*off("hip_left", "knee_left"), pose.leftThighRot)
    pts["knee_left"] = (pts["hip_left"][0] + dx, pts["hip_left"][1] + dy)
    lower_l = pose.leftThighRot + pose.leftLowerLegRot
    dx, dy = rotate_vec(*off("knee_left", "foot_left"), lower_l)
    pts["foot_left"] = (pts["knee_left"][0] + dx, pts["knee_left"][1] + dy)

    dx, dy = off("pelvis", "hip_right")
    pts["hip_right"] = (pts["pelvis"][0] + dx, pts["pelvis"][1] + dy)
    dx, dy = rotate_vec(*off("hip_right", "knee_right"), pose.rightThighRot)
    pts["knee_right"] = (pts["hip_right"][0] + dx, pts["hip_right"][1] + dy)
    lower_r = pose.rightThighRot + pose.rightLowerLegRot
    dx, dy = rotate_vec(*off("knee_right", "foot_right"), lower_r)
    pts["foot_right"] = (pts["knee_right"][0] + dx, pts["knee_right"][1] + dy)

    angles = {
        "torso": pose.bodyRotation, "head": head_angle,
        "upper_arm_left": upper_l, "forearm_left": fore_l, "hand_left": fore_l,
        "upper_arm_right": upper_r, "forearm_right": fore_r, "hand_right": fore_r,
        "thigh_left": pose.leftThighRot, "lower_leg_left": lower_l,
        "thigh_right": pose.rightThighRot, "lower_leg_right": lower_r,
    }
    return pts, angles


# (bone, joint it hangs from, sheet slot to draw, z-order). "left"/"right" here are screen
# sides; SCREEN_*_PARTS maps them onto the blueprint's anatomical part names.
BONE_ORDER = [
    ("thigh_right", "hip_right", SCREEN_RIGHT_PARTS["thigh"], 10),
    ("lower_leg_right", "knee_right", SCREEN_RIGHT_PARTS["lower_leg"], 11),
    ("thigh_left", "hip_left", SCREEN_LEFT_PARTS["thigh"], 20),
    ("lower_leg_left", "knee_left", SCREEN_LEFT_PARTS["lower_leg"], 21),
    ("torso", "pelvis", "body", 30),
    ("upper_arm_left", "shoulder_left", SCREEN_LEFT_PARTS["upper_arm"], 40),
    ("forearm_left", "elbow_left", SCREEN_LEFT_PARTS["forearm"], 41),
    ("hand_left", "wrist_left", "__left_hand__", 42),
    ("head", "neck", "__head__", 50),
    ("upper_arm_right", "shoulder_right", SCREEN_RIGHT_PARTS["upper_arm"], 60),
    ("forearm_right", "elbow_right", SCREEN_RIGHT_PARTS["forearm"], 61),
    ("hand_right", "wrist_right", "__right_hand__", 62),
]


class CharacterRenderer:
    def __init__(self, parts: dict, x_px: float, ground_y_px: float, target_height_px: float, facing: int = 1):
        self.parts = parts
        self.bind = build_geometry(parts)
        natural_height_px = self.bind["foot_left"][1] - self.bind["head_top"][1]
        self.scale = target_height_px / max(1.0, natural_height_px)
        feet_offset_px = self.bind["foot_left"][1] * self.scale
        self.screen_anchor = (x_px, ground_y_px - feet_offset_px)
        self.facing = facing
        self._mouth_cache = {}
        self._face_cache = None

    def _face_anchor(self):
        """
        Where the mouth belongs on the head, as fractions of the head crop.

        The two head variants differ only at the eyes, so diffing them locates the eye
        line and the face's centre; the mouth then sits most of the way down from there
        to the chin. A fixed fraction of the crop can't work — how much hair sits above
        the face varies wildly between characters, which is what pushed the nurse's
        mouth onto her jaw.
        """
        if self._face_cache is not None:
            return self._face_cache

        anchor = (0.5, 0.82)
        a = self.parts.get("head_eyes_opened")
        b = self.parts.get("head_eyes_closed")
        if a is not None and b is not None:
            size = (max(a.width, b.width), max(a.height, b.height))
            ga = np.array(a.convert("L").resize(size, Image.BILINEAR)).astype(float)
            gb = np.array(b.convert("L").resize(size, Image.BILINEAR)).astype(float)
            changed = np.abs(ga - gb) > 25
            rows = np.nonzero(np.array(a.split()[-1].resize(size, Image.BILINEAR)) > 10)[0]
            if changed.sum() > 20 and len(rows):
                ys, xs = np.nonzero(changed)
                eye_y, chin_y = ys.mean(), rows.max()
                anchor = (xs.mean() / size[0], (eye_y + 0.58 * (chin_y - eye_y)) / size[1])

        self._face_cache = anchor
        return anchor

    def _head_with_mouth(self, head_slot: str, mouth_shape: str):
        key = (head_slot, mouth_shape)
        if key in self._mouth_cache:
            return self._mouth_cache[key]
        head = self.parts.get(head_slot) or self.parts.get("head_eyes_opened")
        if head is None:
            self._mouth_cache[key] = None
            return None
        composed = head.copy()
        mouth = self.parts.get(mouth_shape)
        if mouth is not None:
            mw, mh = mouth.size
            hw, hh = head.size
            fx, fy = self._face_anchor()
            pos = (int(hw * fx - mw * 0.5), int(hh * fy - mh * 0.5))
            composed.paste(mouth, pos, mouth)
        self._mouth_cache[key] = composed
        return composed

    def _paste(self, canvas, sprite: Image.Image, world_pt, angle_deg, pivot_frac):
        if sprite is None or sprite.width == 0 or sprite.height == 0:
            return
        w, h = sprite.size
        sw, sh = max(1, int(w * self.scale)), max(1, int(h * self.scale))
        scaled = sprite.resize((sw, sh), Image.LANCZOS)
        if self.facing == -1:
            scaled = scaled.transpose(Image.FLIP_LEFT_RIGHT)
            pivot_frac = (1.0 - pivot_frac[0], pivot_frac[1])

        # Pivots are often off-center (e.g. top-center for a hanging limb), so the padded
        # canvas must have enough margin for the FARTHEST corner from the pivot to swing
        # through at any rotation angle — not just half the sprite's own diagonal, which
        # only holds for a centered pivot and otherwise clips the sprite when rotated.
        pivot_local = (sw * pivot_frac[0], sh * pivot_frac[1])
        corners = [(0, 0), (sw, 0), (0, sh), (sw, sh)]
        max_radius = max(math.hypot(cx - pivot_local[0], cy - pivot_local[1]) for cx, cy in corners)
        canvas_size = int(max_radius * 2) + 6
        pivot_px = (canvas_size / 2, canvas_size / 2)

        padded = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
        ox = int(pivot_px[0] - pivot_local[0])
        oy = int(pivot_px[1] - pivot_local[1])
        padded.paste(scaled, (ox, oy), scaled)

        screen_angle = angle_deg if self.facing == 1 else -angle_deg
        rotated = padded.rotate(-screen_angle, resample=Image.BICUBIC, center=pivot_px)

        wx = self.screen_anchor[0] + (world_pt[0] * self.facing) * self.scale
        wy = self.screen_anchor[1] + world_pt[1] * self.scale
        paste_x = int(wx - pivot_px[0])
        paste_y = int(wy - pivot_px[1])
        canvas.alpha_composite(rotated, (paste_x, paste_y))

    def _pick_hand(self, preferred: str, variants: list):
        sprite = self.parts.get(preferred)
        if sprite is not None:
            return sprite
        for name in variants:
            if name in self.parts:
                return self.parts[name]
        return None

    def draw(self, canvas, pose: RigPose, mouth_shape: str):
        pts, angles = compute_limb_points(pose, self.bind)
        for bone_name, start_joint, slot, _z in BONE_ORDER:
            world_pt = pts[start_joint]
            angle = angles[bone_name]
            if slot == "__head__":
                head_slot = "head_eyes_closed" if pose.headBlinkClosed else "head_eyes_opened"
                sprite = self._head_with_mouth(head_slot, mouth_shape)
                pivot = (0.5, 1.0)
            elif slot == "__left_hand__":
                # pose.selectedLeftHand/rightHand are screen-side (they pair with
                # leftArmUpperRot/rightArmUpperRot, which drive this same bone's rotation
                # below) — HAND_VARIANTS_SCREEN_LEFT is what maps that screen side onto the
                # blueprint's anatomical part names.
                sprite = self._pick_hand(pose.selectedLeftHand, HAND_VARIANTS_SCREEN_LEFT)
                pivot = get_pivot("right_palm_1", sprite) if sprite else (0.5, 0.0)
                if sprite is not None:
                    angle += get_hand_bind_offset(sprite, pivot)
            elif slot == "__right_hand__":
                sprite = self._pick_hand(pose.selectedRightHand, HAND_VARIANTS_SCREEN_RIGHT)
                pivot = get_pivot("left_palm_1", sprite) if sprite else (0.5, 0.0)
                if sprite is not None:
                    angle += get_hand_bind_offset(sprite, pivot)
            else:
                sprite = self.parts.get(slot)
                pivot = get_pivot(slot, sprite) if sprite else (0.5, 0.0)
            self._paste(canvas, sprite, world_pt, angle, pivot)


CAMERA_PRESETS = {
    "two_shot": 1.0,
    "wide_room": 1.0,
    "close_up_speaker": 1.55,
    "dramatic_zoom": 1.9,
}


def apply_camera(frame: Image.Image, scale: float, focus_x_frac: float):
    if scale <= 1.001:
        return frame
    w, h = frame.size
    crop_w, crop_h = w / scale, h / scale
    cx = w * focus_x_frac
    cy = h * 0.42
    x0 = min(max(0, cx - crop_w / 2), w - crop_w)
    y0 = min(max(0, cy - crop_h / 2), h - crop_h)
    cropped = frame.crop((int(x0), int(y0), int(x0 + crop_w), int(y0 + crop_h)))
    return cropped.resize((w, h), Image.LANCZOS)


def render_video(
    project,
    dialogue_audios: list,
    choreographies: list,
    character_parts: dict,
    output_path: str,
    combined_audio_path: str,
    width: int,
    height: int,
    fps: int,
    progress_cb=None,
):
    char_names = list(project.characterSettings.keys()) or sorted({d.character for d in project.dialogues})
    n = max(1, len(char_names))
    ground_y = int(height * 0.88)
    target_h_px = height * 0.62

    renderers = {}
    for i, name in enumerate(char_names):
        x = int(width * (i + 1) / (n + 1))
        facing = 1 if i < (n + 1) / 2 else -1
        parts = character_parts.get(name, {})
        renderers[name] = CharacterRenderer(parts, x, ground_y, target_h_px, facing)
        renderers[name].name_x_frac = (i + 1) / (n + 1)

    total_duration = max((t.startTime + t.duration for t in project.timeline), default=1.0) + 1.0
    total_frames = max(1, int(total_duration * fps))

    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-pixel_format", "rgb24",
        "-video_size", f"{width}x{height}", "-framerate", str(fps),
        "-i", "-",
        "-i", combined_audio_path,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
        "-c:a", "aac", "-shortest",
        output_path,
    ]
    proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    idle_pose_cache = {}

    for frame_idx in range(total_frames):
        t = frame_idx / fps
        active_i = -1
        for i, item in enumerate(project.timeline):
            if item.startTime <= t <= item.startTime + item.duration:
                active_i = i
                break

        canvas = Image.new("RGBA", (width, height), (24, 28, 40, 255))

        active_char = None
        camera_scale = 1.0
        focus_frac = 0.5
        if active_i >= 0:
            dlg = project.dialogues[active_i]
            active_char = dlg.character
            choreo = choreographies[active_i]
            camera_scale = CAMERA_PRESETS.get(choreo["cameraShot"], 1.0)
            renderer = renderers.get(active_char)
            focus_frac = renderer.name_x_frac if renderer else 0.5

        for name, renderer in renderers.items():
            if name == active_char:
                choreo = choreographies[active_i]
                mode = choreo["mode"]
                local_t = t - project.timeline[active_i].startTime
                pose = calculate_rig_pose(t, mode, right_hand_prop=choreo["rightHand"], left_hand_prop=choreo["leftHand"])
                amp = dialogue_audios[active_i].amplitude_at(local_t) if dialogue_audios[active_i] else 0.0
                from app.audio_utils import amplitude_to_mouth_shape
                mouth = amplitude_to_mouth_shape(amp)
            else:
                pose = calculate_rig_pose(t, "idle")
                mouth = "mouth_shape_1"
            renderer.draw(canvas, pose, mouth)

        frame_rgb = canvas.convert("RGB")
        frame_rgb = apply_camera(frame_rgb, camera_scale, focus_frac)

        arr = np.asarray(frame_rgb, dtype=np.uint8)
        proc.stdin.write(arr.tobytes())

        if progress_cb and frame_idx % max(1, fps) == 0:
            pct = 30 + int((frame_idx / total_frames) * 65)
            progress_cb(pct, f"Rendering frame {frame_idx}/{total_frames} ({t:.1f}s / {total_duration:.1f}s)")

    proc.stdin.close()
    proc.wait()
    return output_path


def render_character_preview(parts: dict, width: int = 500, height: int = 700) -> Image.Image:
    """Assembles a single character in a neutral talking pose, for a quick upload-and-check preview."""
    canvas = Image.new("RGBA", (width, height), (30, 32, 44, 255))
    ground_y = int(height * 0.9)
    target_h_px = height * 0.72
    renderer = CharacterRenderer(parts, width // 2, ground_y, target_h_px, facing=1)
    pose = calculate_rig_pose(0.6, "talk")
    mouth = "mouth_shape_3" if "mouth_shape_3" in parts else "mouth_shape_1"
    renderer.draw(canvas, pose, mouth)
    return canvas.convert("RGB")


def render_pose_animation(
    parts: dict, mode: str, output_path: str,
    width: int = 480, height: int = 640, fps: int = 20, duration: float = 3.0,
) -> str:
    """Short, silent one-click preview clip of a single character performing one named pose."""
    from app.audio_utils import amplitude_to_mouth_shape

    total_frames = max(1, int(duration * fps))
    ground_y = int(height * 0.88)
    target_h = height * 0.6

    walks = mode in ("walk_talk", "run_talk")
    x_start, x_end = width * 0.25, width * 0.75
    talk_like = "talk" in mode

    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-pixel_format", "rgb24",
        "-video_size", f"{width}x{height}", "-framerate", str(fps),
        "-i", "-",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
        output_path,
    ]
    proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    for frame_idx in range(total_frames):
        t = frame_idx / fps
        progress = t / duration
        x = (x_start + (x_end - x_start) * progress) if walks else width / 2
        facing = -1 if walks else 1

        canvas = Image.new("RGBA", (width, height), (24, 28, 40, 255))
        renderer = CharacterRenderer(parts, x, ground_y, target_h, facing=facing)
        pose = calculate_rig_pose(t, mode)

        if talk_like:
            mouth = amplitude_to_mouth_shape(abs(math.sin(t * 9.0)) * 0.5)
        elif mode == "laughing":
            mouth = "mouth_shape_4"
        elif mode == "excited_jump":
            mouth = "mouth_shape_3"
        else:
            mouth = "mouth_shape_1"

        renderer.draw(canvas, pose, mouth)
        arr = np.asarray(canvas.convert("RGB"), dtype=np.uint8)
        try:
            proc.stdin.write(arr.tobytes())
        except BrokenPipeError:
            break

    try:
        proc.stdin.close()
    except BrokenPipeError:
        pass
    proc.wait()
    return output_path
