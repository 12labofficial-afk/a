"""
Turn an uploaded Adobe Animate .fla (XFL zip) into a browsable list of the
REAL, artist-authored animations inside it, and render short preview clips
for them on demand.

An .fla's LIBRARY is full of symbols: most are static single-pose art
(a static DOMFrame per layer). The ones worth surfacing are the symbols
where some layer actually has multiple keyframes -- those are genuine
hand-built motion (a walk cycle, a blink, a bow-draw), not just a body part
sitting still. We find those by parsing every LIBRARY/**/*.xml and counting
DOMFrame elements per layer.
"""
import glob
import os
import re
import shutil
import subprocess
import tempfile

import numpy as np
from PIL import Image
from xml.etree import ElementTree as ET

XFL_NS = "{http://ns.adobe.com/xfl/2008/}"


def _local(tag):
    return tag.split("}")[-1] if "}" in tag else tag


def repair_and_extract(fla_path, extract_dir):
    """XFL .fla files are zips and real-world exports are sometimes slightly
    truncated/corrupted. Try a plain unzip first; if that doesn't yield a
    proper XFL project, repair with `zip -FF` (same trick that fixed the
    Shikari file) and unzip the repaired copy."""
    os.makedirs(extract_dir, exist_ok=True)
    subprocess.run(["unzip", "-o", "-q", fla_path, "-d", extract_dir], capture_output=True)

    if not os.path.isdir(os.path.join(extract_dir, "LIBRARY")):
        shutil.rmtree(extract_dir, ignore_errors=True)
        os.makedirs(extract_dir, exist_ok=True)
        fixed_path = fla_path + ".fixed.fla"
        subprocess.run(
            ["zip", "-FF", fla_path, "--out", fixed_path],
            input=b"y\ny\ny\n", capture_output=True,
        )
        if not os.path.exists(fixed_path):
            raise RuntimeError("FLA file corrupt hai aur repair nahi ho payi.")
        subprocess.run(["unzip", "-o", "-q", fixed_path, "-d", extract_dir], check=True)
        os.remove(fixed_path)

    if not os.path.isdir(os.path.join(extract_dir, "LIBRARY")):
        raise RuntimeError(
            "Ye ek valid .fla (XFL / uncompressed Animate format) nahi lag rahi "
            "-- LIBRARY folder nahi mila."
        )


def _analyze_symbol_file(full_path):
    """Returns None if this isn't a usable DOMSymbolItem. Otherwise a dict
    with the max keyframes seen on any one layer (motion signal), the
    timeline's total frame length, and the layer count."""
    try:
        tree = ET.parse(full_path)
    except ET.ParseError:
        return None
    root = tree.getroot()
    if _local(root.tag) != "DOMSymbolItem":
        return None

    max_keyframes = 0
    total_duration = 0
    layer_count = 0
    nested_refs = set()
    for layer in root.iter():
        if _local(layer.tag) != "DOMLayer":
            continue
        layer_count += 1
        frames = [f for f in layer.iter() if _local(f.tag) == "DOMFrame"]
        max_keyframes = max(max_keyframes, len(frames))
        for f in frames:
            try:
                idx = int(f.get("index", "0"))
                dur = int(f.get("duration", "1"))
            except ValueError:
                continue
            total_duration = max(total_duration, idx + dur)
        for inst in layer.iter():
            if _local(inst.tag) == "DOMSymbolInstance":
                lib = inst.get("libraryItemName")
                if lib:
                    nested_refs.add(lib)

    return dict(
        keyframes=max_keyframes,
        duration=max(total_duration, 1),
        layers=layer_count,
        symbol_type=root.get("symbolType", "graphic"),
        nested_parts=len(nested_refs),
    )


def find_stage_symbols(extract_dir):
    """The symbol(s) placed directly on the Stage/Scene -- this is what you'd
    actually SEE if you opened the .fla in Adobe Animate. It's often a mostly
    static full-body pose (few keyframes of its own, since the real motion
    lives in separate library duplicates), so the keyframe-based scan below
    can miss it entirely even though it's the single most important thing
    to show: the assembled character itself."""
    doc_path = os.path.join(extract_dir, "DOMDocument.xml")
    if not os.path.exists(doc_path):
        return []
    try:
        tree = ET.parse(doc_path)
    except ET.ParseError:
        return []
    root = tree.getroot()
    refs = []
    seen = set()
    for inst in root.iter():
        if _local(inst.tag) != "DOMSymbolInstance":
            continue
        lib = inst.get("libraryItemName")
        if lib and lib not in seen:
            seen.add(lib)
            refs.append(lib)
    return refs


def list_animated_symbols(extract_dir, min_keyframes=2, composite_threshold=6):
    """Scan the whole LIBRARY for symbols worth surfacing to a user browsing
    this .fla: the assembled character(s) actually placed on the Stage
    (always included, however static -- it's the one thing you'd recognize
    on opening the file in Animate), plus every symbol with real (multi-
    keyframe) motion on at least one layer.

    Each result gets a `role`:
      - "character": on the Stage, or itself assembles several other symbols
        (nested_parts >= composite_threshold) -- a full body/head, not a part.
      - "animation": real multi-keyframe motion, but not a full assembly --
        a walk cycle, a blink, a gesture.
      - "part": everything else that still had >=min_keyframes (small
        fragments -- an eyebrow twitch, one finger). Kept, but ranked last,
        since these are rarely what someone browsing the file actually wants.
    """
    library_dir = os.path.join(extract_dir, "LIBRARY")
    stage_symbols = set(find_stage_symbols(extract_dir))

    all_info = {}
    for root_dir, _, files in os.walk(library_dir):
        for fn in files:
            if not fn.endswith(".xml"):
                continue
            full = os.path.join(root_dir, fn)
            rel = os.path.relpath(full, library_dir)
            symbol_path = rel[:-4].replace(os.sep, "/")
            info = _analyze_symbol_file(full)
            if info is None:
                continue
            all_info[symbol_path] = info

    def resolve(symbol_path):
        """Stage instances are recorded under their bare name (e.g. "Symbol 4"),
        but the file may only exist under "Duplicate Items Folder/Symbol 4" --
        match either way."""
        if symbol_path in all_info:
            return symbol_path
        for cand in all_info:
            if cand.endswith("/" + symbol_path):
                return cand
        return None

    results = []
    seen = set()
    for stage_sym in stage_symbols:
        resolved = resolve(stage_sym)
        if resolved is None or resolved in seen:
            continue
        seen.add(resolved)
        info = all_info[resolved]
        results.append(dict(symbol=resolved, display_name=os.path.basename(resolved),
                             role="character", **info))

    for symbol_path, info in all_info.items():
        if symbol_path in seen:
            continue
        is_composite = info["nested_parts"] >= composite_threshold
        if is_composite:
            role = "character"
        elif info["keyframes"] >= min_keyframes:
            role = "animation"
        else:
            continue
        results.append(dict(symbol=symbol_path, display_name=os.path.basename(symbol_path),
                             role=role, **info))

    role_rank = {"character": 0, "animation": 1, "part": 2}
    results.sort(key=lambda r: (role_rank.get(r["role"], 3), -r["keyframes"]))
    return results


def safe_name(symbol_path):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", symbol_path)


def render_preview(extract_dir, symbol_path, out_path, max_frames=48, out_size=1080, fps=15):
    xml_path = os.path.join(extract_dir, "LIBRARY", *symbol_path.split("/")) + ".xml"
    if not os.path.exists(xml_path):
        raise RuntimeError(f"Symbol '{symbol_path}' library me nahi mila.")
    info = _analyze_symbol_file(xml_path)
    if info is None:
        raise RuntimeError(f"'{symbol_path}' ek valid symbol nahi hai.")

    total = max(1, min(info["duration"], max_frames))
    work = tempfile.mkdtemp(prefix="flaprev_")
    try:
        svg_dir = os.path.join(work, "svg")
        os.makedirs(svg_dir, exist_ok=True)
        r = subprocess.run(
            ["xfl2svg", extract_dir, symbol_path, svg_dir,
             "--timeline-type", "symbol", "--first-frame", "1", "--last-frame", str(total), "--no-background"],
            capture_output=True, text=True,
        )
        svgs = sorted(glob.glob(os.path.join(svg_dir, "*.svg")))
        if not svgs:
            raise RuntimeError((r.stderr or "xfl2svg render fail").strip()[:300])

        # Content can sit anywhere relative to the symbol's own origin, and at
        # any scale -- a whole walking body spans thousands of units, while a
        # small prop like an eyelid or a necklace charm is only tens of units
        # wide. A single fixed viewBox can't frame both well, so this is two
        # passes: pass 1 is a cheap, deliberately wide net (so nothing gets
        # clipped) just to find where the content actually sits; pass 2
        # re-renders each frame with the viewBox tightly fitted to that
        # content, so small props come out crisp instead of a tiny blurry
        # speck in the middle of a mostly-empty frame.
        coarse_size = 420
        wide_off, wide_span = -1500.0, 6000.0
        union = None
        for svg_path in svgs:
            data = open(svg_path, encoding="utf-8").read()
            data = re.sub(r'viewBox="[^"]*"', f'viewBox="{wide_off} {wide_off} {wide_span} {wide_span}"', data)
            data = re.sub(r'width="[^"]*px"', f'width="{coarse_size}px"', data)
            data = re.sub(r'height="[^"]*px"', f'height="{coarse_size}px"', data)
            fixed_svg = svg_path + ".coarse.svg"
            open(fixed_svg, "w", encoding="utf-8").write(data)
            png_path = svg_path + ".coarse.png"
            subprocess.run(
                ["rsvg-convert", "-w", str(coarse_size), "-h", str(coarse_size), fixed_svg, "-o", png_path],
                check=True,
            )
            arr = np.array(Image.open(png_path).convert("RGBA"))
            mask = arr[:, :, 3] > 10
            ys, xs = np.where(mask)
            if len(xs) == 0:
                continue
            b = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
            union = b if union is None else (
                min(union[0], b[0]), min(union[1], b[1]), max(union[2], b[2]), max(union[3], b[3])
            )
        if union is None:
            raise RuntimeError("Is symbol ke frames me koi drawn content nahi mila.")

        units_per_px = wide_span / coarse_size
        cx0 = wide_off + union[0] * units_per_px
        cy0 = wide_off + union[1] * units_per_px
        cx1 = wide_off + union[2] * units_per_px
        cy1 = wide_off + union[3] * units_per_px
        cw, ch = cx1 - cx0, cy1 - cy0
        pad = max(cw, ch) * 0.12 + 5
        cx0, cy0, cx1, cy1 = cx0 - pad, cy0 - pad, cx1 + pad, cy1 + pad
        cw, ch = cx1 - cx0, cy1 - cy0
        side = max(cw, ch, 1.0)
        cx0 -= (side - cw) / 2
        cy0 -= (side - ch) / 2

        raster2 = max(out_size, 480)
        frame_dir = os.path.join(work, "frames_out")
        os.makedirs(frame_dir, exist_ok=True)
        for i, svg_path in enumerate(svgs, start=1):
            data = open(svg_path, encoding="utf-8").read()
            data = re.sub(r'viewBox="[^"]*"', f'viewBox="{cx0} {cy0} {side} {side}"', data)
            data = re.sub(r'width="[^"]*px"', f'width="{raster2}px"', data)
            data = re.sub(r'height="[^"]*px"', f'height="{raster2}px"', data)
            fixed_svg = svg_path + ".fine.svg"
            open(fixed_svg, "w", encoding="utf-8").write(data)
            raw_png = svg_path + ".fine.png"
            subprocess.run(
                ["rsvg-convert", "-w", str(raster2), "-h", str(raster2), fixed_svg, "-o", raw_png],
                check=True,
            )
            im = Image.open(raw_png).convert("RGBA")
            if raster2 != out_size:
                im = im.resize((out_size, out_size))
            canvas = Image.new("RGBA", (out_size, out_size), (24, 24, 24, 255))
            canvas.alpha_composite(im, (0, 0))
            canvas.convert("RGB").save(os.path.join(frame_dir, f"f_{i:04d}.png"))

        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-y", "-framerate", str(fps),
             "-i", os.path.join(frame_dir, "f_%04d.png"),
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", out_path],
            check=True, capture_output=True,
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)
