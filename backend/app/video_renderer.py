import math
import os
import subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.rig_pose import calculate_rig_pose, RigPose
from app.rig_assets import get_pivot

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
    "/usr/share/fonts/truetype/lohit-devanagari/Lohit-Devanagari.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _load_font(size: int):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def rotate_vec(dx, dy, angle_deg):
    a = math.radians(angle_deg)
    c, s = math.cos(a), math.sin(a)
    return (dx * c - dy * s, dx * s + dy * c)


def build_geometry(parts: dict) -> dict:
    """
    Derives per-character bind-pose joint positions (native pixel units, pelvis at origin)
    directly from each part's own pixel size, since hand-drawn/scattered-sheet rigs have
    wildly different proportions between characters and a single shared abstract skeleton
    does not fit them all.
    """
    body = parts.get("body")
    head = parts.get("head_eyes_opened") or parts.get("head_eyes_closed")
    arm_l = parts.get("arm_left_upper")
    arm_r = parts.get("arm_right_upper")
    fore_l = parts.get("forearm_left")
    fore_r = parts.get("forearm_right")
    thigh_l = parts.get("thigh_left")
    thigh_r = parts.get("thigh_right")
    leg_l = parts.get("leg_lower_left")
    leg_r = parts.get("leg_lower_right")

    bw, bh = body.size if body else (100, 150)

    pelvis = (0.0, 0.0)
    neck = (0.0, -bh * 0.94)
    shoulder_left = (-bw * 0.36, -bh * 0.88)
    shoulder_right = (bw * 0.36, -bh * 0.88)
    hip_left = (-bw * 0.20, -bh * 0.04)
    hip_right = (bw * 0.20, -bh * 0.04)

    head_h = head.height * 0.92 if head else bh * 0.5
    head_top = (neck[0], neck[1] - head_h)

    arm_l_len = arm_l.height * 0.82 if arm_l else bh * 0.3
    elbow_left = (shoulder_left[0], shoulder_left[1] + arm_l_len)
    arm_r_len = arm_r.height * 0.82 if arm_r else bh * 0.3
    elbow_right = (shoulder_right[0], shoulder_right[1] + arm_r_len)

    fore_l_len = fore_l.height * 0.82 if fore_l else bh * 0.28
    wrist_left = (elbow_left[0], elbow_left[1] + fore_l_len)
    fore_r_len = fore_r.height * 0.82 if fore_r else bh * 0.28
    wrist_right = (elbow_right[0], elbow_right[1] + fore_r_len)

    hand_left = (wrist_left[0], wrist_left[1] + fore_l_len * 0.04)
    hand_right = (wrist_right[0], wrist_right[1] + fore_r_len * 0.04)

    thigh_l_len = thigh_l.height * 0.82 if thigh_l else 0.0
    knee_left = (hip_left[0], hip_left[1] + thigh_l_len)
    thigh_r_len = thigh_r.height * 0.82 if thigh_r else 0.0
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
    pts["neck"] = (pts["pelvis"][0] + dx, pts["pelvis"][1] + dy)

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


BONE_ORDER = [
    ("thigh_right", "hip_right", "thigh_right", 10),
    ("lower_leg_right", "knee_right", "leg_lower_right", 11),
    ("thigh_left", "hip_left", "thigh_left", 20),
    ("lower_leg_left", "knee_left", "leg_lower_left", 21),
    ("torso", "pelvis", "body", 30),
    ("upper_arm_left", "shoulder_left", "arm_left_upper", 40),
    ("forearm_left", "elbow_left", "forearm_left", 41),
    ("hand_left", "wrist_left", "__left_hand__", 42),
    ("head", "neck", "__head__", 50),
    ("upper_arm_right", "shoulder_right", "arm_right_upper", 60),
    ("forearm_right", "elbow_right", "forearm_right", 61),
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
            pos = (int(hw * 0.5 - mw * 0.5), int(hh * 0.87 - mh * 0.5))
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
                sprite = self.parts.get(pose.selectedLeftHand) or self.parts.get("hand_left")
                pivot = get_pivot("hand_left", sprite) if sprite else (0.5, 0.0)
            elif slot == "__right_hand__":
                sprite = self.parts.get(pose.selectedRightHand) or self.parts.get("hand_right")
                pivot = get_pivot("hand_right", sprite) if sprite else (0.5, 0.0)
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


def draw_subtitle(canvas: Image.Image, character: str, line: str, w: int, h: int):
    draw = ImageDraw.Draw(canvas)
    box_h = int(h * 0.16)
    box_y = h - box_h - int(h * 0.03)
    box_w = int(w * 0.9)
    box_x = (w - box_w) // 2
    draw.rounded_rectangle([box_x, box_y, box_x + box_w, box_y + box_h], radius=14, fill=(10, 10, 10, 220))

    name_font = _load_font(int(h * 0.032))
    line_font = _load_font(int(h * 0.034))
    draw.text((box_x + 20, box_y + 14), character, font=name_font, fill=(255, 200, 80, 255))
    max_chars = max(20, int(box_w / (h * 0.02)))
    wrapped = line if len(line) <= max_chars else line[: max_chars - 1] + "…"
    draw.text((box_x + 20, box_y + int(box_h * 0.5)), wrapped, font=line_font, fill=(255, 255, 255, 255))


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
        active_line = None
        if active_i >= 0:
            dlg = project.dialogues[active_i]
            active_char = dlg.character
            choreo = choreographies[active_i]
            camera_scale = CAMERA_PRESETS.get(choreo["cameraShot"], 1.0)
            renderer = renderers.get(active_char)
            focus_frac = renderer.name_x_frac if renderer else 0.5
            active_line = (dlg.character, dlg.line)

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
        if active_line:
            frame_rgb = frame_rgb.convert("RGBA")
            draw_subtitle(frame_rgb, active_line[0], active_line[1], width, height)
            frame_rgb = frame_rgb.convert("RGB")

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
