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
import uuid
from concurrent.futures import ThreadPoolExecutor

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


# ---------------------------------------------------------------------------
# Audio-driven lip-sync: swap the real mouth-shape sub-symbol inside a target
# animation frame-by-frame to match an uploaded audio's amplitude, using only
# assets that already exist in the file (no invented motion, no guessed
# matrices -- every mouth pose and every attachment matrix is copied verbatim
# from the artist's own real data).
# ---------------------------------------------------------------------------

MOUTH_NAME_RE = re.compile(r"\b(lip|mouth)\b", re.I)


def _symbol_xml_path(extract_dir, symbol_path):
    return os.path.join(extract_dir, "LIBRARY", *symbol_path.split("/")) + ".xml"


def _first_instance(frame):
    return next((e for e in frame.iter() if _local(e.tag) == "DOMSymbolInstance"), None)


def _matrix_attrs(inst):
    mat_el = None
    for child in inst.iter():
        if _local(child.tag) == "Matrix":
            mat_el = child
            break
    a = float(mat_el.get("a", 1)) if mat_el is not None else 1.0
    b = float(mat_el.get("b", 0)) if mat_el is not None else 0.0
    c = float(mat_el.get("c", 0)) if mat_el is not None else 0.0
    d = float(mat_el.get("d", 1)) if mat_el is not None else 1.0
    tx = float(mat_el.get("tx", 0)) if mat_el is not None else 0.0
    ty = float(mat_el.get("ty", 0)) if mat_el is not None else 0.0
    return (a, b, c, d, tx, ty)


def _pivot_attrs(inst):
    for child in inst.iter():
        if _local(child.tag) == "Point":
            return (float(child.get("x", 0)), float(child.get("y", 0)))
    return (0.0, 0.0)


def find_mouth_symbol(extract_dir, target_symbol):
    """Look at each layer of `target_symbol`; for the sub-symbol its first
    frame places (e.g. a "Face" composite), check whether THAT sub-symbol has
    a layer literally named "Lip"/"Mouth" (case-insensitive) referencing a
    real multi-keyframe mouth symbol. This is exactly the manual trail used
    for Shikari's and Motu Sheth's real lip-sync assets, generalized. Returns
    None if no such structure is found anywhere in the target symbol.

    `sub_symbol` (e.g. "Face copy 2") is the thing actually placed by
    `target_layer` -- swapping its mouth requires building variant COPIES of
    the whole sub_symbol (see _build_mouth_variants), not placing the mouth
    symbol alone in target_layer, which would drop the rest of the face."""
    xml_path = _symbol_xml_path(extract_dir, target_symbol)
    if not os.path.exists(xml_path):
        return None
    root = ET.parse(xml_path).getroot()
    for layer in root.iter():
        if _local(layer.tag) != "DOMLayer":
            continue
        frame = next((f for f in layer.iter() if _local(f.tag) == "DOMFrame"), None)
        if frame is None:
            continue
        inst = _first_instance(frame)
        if inst is None:
            continue
        sub_symbol = inst.get("libraryItemName")
        if not sub_symbol:
            continue
        sub_path = _symbol_xml_path(extract_dir, sub_symbol)
        if not os.path.exists(sub_path):
            continue
        try:
            sub_root = ET.parse(sub_path).getroot()
        except ET.ParseError:
            continue
        for sub_layer in sub_root.iter():
            if _local(sub_layer.tag) != "DOMLayer":
                continue
            if not MOUTH_NAME_RE.search(sub_layer.get("name") or ""):
                continue
            sub_frame = next((f for f in sub_layer.iter() if _local(f.tag) == "DOMFrame"), None)
            if sub_frame is None:
                continue
            mouth_inst = _first_instance(sub_frame)
            if mouth_inst is None:
                continue
            mouth_symbol = mouth_inst.get("libraryItemName")
            mouth_path = _symbol_xml_path(extract_dir, mouth_symbol)
            info = _analyze_symbol_file(mouth_path)
            if info is None or info["keyframes"] < 3:
                continue  # not a real multi-shape mouth set
            return dict(
                target_layer=layer.get("name"),
                sub_symbol=sub_symbol,
                mouth_layer_name=sub_layer.get("name"),
                mouth_symbol=mouth_symbol,
                mouth_keyframes=info["keyframes"],
            )
    return None


def _build_mouth_variants(extract_dir, sub_symbol, mouth_layer_name, states):
    """Copies of `sub_symbol` (e.g. "Face copy 2", eyes/eyebrows/nose/ears
    and all) with ONLY its own mouth-layer's nested instance re-pinned to
    each real keyframe in `states` -- same technique proven on Shikari's
    "Chin with Mouth" and Motu Sheth's "Lip". Returns {state: variant_symbol_path}."""
    src_path = _symbol_xml_path(extract_dir, sub_symbol)
    src = open(src_path, encoding="utf-8").read()
    orig_name_m = re.search(r'\bname="([^"]*)"', src)
    orig_id_m = re.search(r'\bitemID="([^"]*)"', src)
    orig_name = orig_name_m.group(1) if orig_name_m else sub_symbol
    orig_id = orig_id_m.group(1) if orig_id_m else None

    # locate the mouth layer's own <DOMSymbolInstance ...> opening tag to patch
    layer_m = re.search(
        rf'<DOMLayer name="{re.escape(mouth_layer_name)}".*?</DOMLayer>\s*(?=<DOMLayer|</layers>)',
        src, re.S,
    )
    if layer_m is None:
        raise RuntimeError(f"'{mouth_layer_name}' layer nahi mili '{sub_symbol}' me.")
    layer_block = layer_m.group(0)
    inst_m = re.search(r'<DOMSymbolInstance\b[^>]*>', layer_block)
    if inst_m is None:
        raise RuntimeError(f"'{mouth_layer_name}' me koi symbol instance nahi mila.")
    orig_tag = inst_m.group(0)

    variants = {}
    for state in states:
        if "firstFrame=" in orig_tag:
            new_tag = re.sub(r'firstFrame="\d+"', f'firstFrame="{state}"', orig_tag)
        else:
            new_tag = orig_tag.replace(' loop="loop"', f' firstFrame="{state}" loop="single frame"')
            if new_tag == orig_tag:  # no loop="loop" found either; append before closing >
                new_tag = orig_tag[:-1] + f' firstFrame="{state}" loop="single frame">'
        new_layer_block = layer_block.replace(orig_tag, new_tag, 1)
        out = src.replace(layer_block, new_layer_block, 1)

        variant_symbol = f"{sub_symbol}_mouth{state}"
        variant_id = f"0000990{state:02d}-{abs(hash(sub_symbol)) % 10**8:08d}"
        out = out.replace(f'name="{orig_name}"', f'name="{variant_symbol}"', 1)
        if orig_id:
            out = out.replace(f'itemID="{orig_id}"', f'itemID="{variant_id}"', 1)

        out_path = _symbol_xml_path(extract_dir, variant_symbol)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        open(out_path, "w", encoding="utf-8").write(out)
        variants[state] = variant_symbol

    # register all variants in DOMDocument.xml
    doc_path = os.path.join(extract_dir, "DOMDocument.xml")
    doc = open(doc_path).read()
    added = False
    for state, variant_symbol in variants.items():
        include = f'          <Include href="{variant_symbol}.xml" itemIcon="1" loadImmediate="false" itemID="mouthvar-{state}" lastModified="1"/>\n'
        if f'{variant_symbol}.xml"' not in doc:
            doc = doc.replace("     <symbols>\n", "     <symbols>\n" + include)
            added = True
    if added:
        open(doc_path, "w").write(doc)
    return variants


def _mouth_state_frames(extract_dir, mouth_symbol, n_states=4):
    """Evenly-spaced real keyframe indices across the mouth symbol's own
    timeline, from its first (usually closed/neutral) to its most-open
    poses -- a spread of genuinely distinct real mouth shapes to pick from."""
    path = _symbol_xml_path(extract_dir, mouth_symbol)
    root = ET.parse(path).getroot()
    indices = sorted({
        int(f.get("index")) for layer in root.iter() if _local(layer.tag) == "DOMLayer"
        for f in layer.iter() if _local(f.tag) == "DOMFrame"
    })
    if not indices:
        return [0] * n_states
    step = max(1, len(indices) // n_states)
    picked = [indices[min(i * step, len(indices) - 1)] for i in range(n_states)]
    return picked


def render_lipsync(extract_dir, target_symbol, audio_path, out_path, fps=None,
                    n_states=4, out_size=1080, max_seconds=30.0):
    """Render `target_symbol`'s real animation with its real mouth-shape
    sub-symbol swapped, frame by frame, to match `audio_path`'s amplitude --
    every part of every frame (body, hands, legs, and the mouth pose itself)
    is real data lifted straight from the file; only WHICH real mouth
    keyframe is shown at each moment is driven by the audio."""
    from app.audio_utils import DialogueAudio

    mouth_info = find_mouth_symbol(extract_dir, target_symbol)
    if mouth_info is None:
        raise RuntimeError(
            f"'{target_symbol}' ke andar koi real mouth/lip-shape symbol nahi mila "
            f"(koi layer 'Lip' ya 'Mouth' naam ki nahi mili jisme multiple real shapes hon)."
        )

    if fps is None:
        fps = doc_frame_rate(extract_dir)
    audio = DialogueAudio(audio_path, envelope_fps=int(fps))
    duration = min(audio.duration_sec, max_seconds)
    n_frames = max(1, int(duration * fps) + 1)

    states = _mouth_state_frames(extract_dir, mouth_info["mouth_symbol"], n_states)
    variants = _build_mouth_variants(extract_dir, mouth_info["sub_symbol"],
                                      mouth_info["mouth_layer_name"], states)

    # Calibrate against THIS clip's own loudness range, not a fixed constant --
    # a normal speaking voice's RMS envelope rarely gets near an absolute 0.5,
    # so a fixed ceiling meant the loudest real mouth shapes (wide-open,
    # round-O) never got picked and the mouth kept cycling through just the
    # bottom one or two states, which reads as "the same shape repeating".
    loud_ceiling = max(float(np.percentile(audio.envelope, 95)), 1e-6)

    def amp_to_state(amp):
        bucket = int(amp * n_states / loud_ceiling)
        return states[max(0, min(bucket, len(states) - 1))]

    xml_path = _symbol_xml_path(extract_dir, target_symbol)
    root = ET.parse(xml_path).getroot()

    def frame_xml(idx, dur, lib, matrix, pivot):
        a, b, c, d, tx, ty = matrix
        mparts = []
        if abs(a - 1) > 1e-9 or b or c or abs(d - 1) > 1e-9:
            mparts += [f'a="{a}"']
            if b: mparts.append(f'b="{b}"')
            if c: mparts.append(f'c="{c}"')
            mparts += [f'd="{d}"']
        mparts += [f'tx="{tx}"', f'ty="{ty}"']
        return f'''<DOMFrame index="{idx}" duration="{dur}" keyMode="9728">
              <elements>
                <DOMSymbolInstance libraryItemName="{lib}" symbolType="graphic" loop="loop">
                  <matrix><Matrix {" ".join(mparts)}/></matrix>
                  <transformationPoint><Point x="{pivot[0]}" y="{pivot[1]}"/></transformationPoint>
                </DOMSymbolInstance>
              </elements>
            </DOMFrame>'''

    layers_xml = []
    for layer in root.iter():
        if _local(layer.tag) != "DOMLayer":
            continue
        name = layer.get("name")
        frames = [f for f in layer.iter() if _local(f.tag) == "DOMFrame"]
        out_frames = []
        if name == mouth_info["target_layer"]:
            # audio-driven: chunk every hold segment (using THAT segment's own
            # real outer matrix/pivot, so the face stays exactly where the
            # artist put it). Real gesture tweens keep their own matrix/easing
            # 100% untouched (we don't invent interpolated frames), but we
            # still swap WHICH mouth pose plays during them -- otherwise the
            # mouth freezes on its pre-tween pose for the whole tween and
            # then jumps to catch up once the next hold starts, which is what
            # makes the lipsync look like it's lagging behind the audio.
            for f in frames:
                idx = int(f.get("index"))
                dur = int(f.get("duration", 1))
                if idx >= n_frames:
                    break
                is_tween = f.get("tweenType") == "motion"
                inst = _first_instance(f)
                if inst is None:
                    out_frames.append(ET.tostring(f, encoding="unicode"))
                    continue
                if is_tween:
                    mid_frame = (idx + min(idx + dur, n_frames) - 1) / 2
                    amp = audio.amplitude_at(mid_frame / fps)
                    state = amp_to_state(amp)
                    inst.set("libraryItemName", variants[state])
                    out_frames.append(ET.tostring(f, encoding="unicode"))
                    continue
                outer_matrix = _matrix_attrs(inst)
                outer_pivot = _pivot_attrs(inst)
                chunk = max(1, int(fps // 8))  # ~8 mouth updates/sec
                pos = idx
                end = min(idx + dur, n_frames)
                while pos < end:
                    seg = min(chunk, end - pos)
                    amp = audio.amplitude_at(pos / fps)
                    state = amp_to_state(amp)
                    out_frames.append(frame_xml(pos, seg, variants[state], outer_matrix, outer_pivot))
                    pos += seg
        else:
            for f in frames:
                idx = int(f.get("index"))
                if idx >= n_frames:
                    break
                out_frames.append(ET.tostring(f, encoding="unicode"))
        if not out_frames:
            continue
        layers_xml.append(f'        <DOMLayer name="{name}">\n          <frames>\n' +
                           "\n".join(out_frames) + "\n          </frames>\n        </DOMLayer>")

    sym_name = f"{os.path.basename(target_symbol)}_lipsync"
    xml = f'''<DOMSymbolItem xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns="http://ns.adobe.com/xfl/2008/" name="{sym_name}" itemID="00009900-00000001" symbolType="graphic" lastModified="1" lastUniqueIdentifier="1">
  <timeline>
    <DOMTimeline name="{sym_name}" layerDepthEnabled="true">
      <layers>
{os.linesep.join(layers_xml)}
      </layers>
    </DOMTimeline>
  </timeline>
</DOMSymbolItem>
'''
    lib_dir = os.path.join(extract_dir, "LIBRARY")
    lipsync_xml_path = os.path.join(lib_dir, f"{sym_name}.xml")
    open(lipsync_xml_path, "w").write(xml)

    doc_path = os.path.join(extract_dir, "DOMDocument.xml")
    doc = open(doc_path).read()
    include = f'          <Include href="{sym_name}.xml" itemIcon="1" loadImmediate="false" itemID="00009900-00000001" lastModified="1"/>\n'
    if f'{sym_name}.xml"' not in doc:
        doc = doc.replace("     <symbols>\n", "     <symbols>\n" + include)
        open(doc_path, "w").write(doc)

    video_only = out_path + ".video.mp4"
    render_preview(extract_dir, sym_name, video_only, max_frames=n_frames, out_size=out_size,
                    fps=fps, min_seconds=0)

    subprocess.run(
        ["ffmpeg", "-y", "-i", video_only, "-i", audio_path,
         "-c:v", "copy", "-c:a", "aac", "-shortest", "-t", str(duration), out_path],
        check=True, capture_output=True,
    )
    os.remove(video_only)
    return dict(mouth_symbol=mouth_info["mouth_symbol"], mouth_layer=mouth_info["mouth_layer_name"],
                target_layer=mouth_info["target_layer"], frames=n_frames, duration=duration)


def attach_prop(extract_dir, target_symbol, prop_extract_dir, prop_symbol,
                 parent_layer, offset, out_symbol_name):
    """Add `prop_symbol` (a static prop from a possibly different FLA's
    extract dir, e.g. a weapon/tool drawn on its own) as a new layer inside
    `target_symbol`, RIGIDLY attached to `parent_layer` -- every frame, the
    prop gets the parent layer's own real matrix for that exact frame
    (rotation and all), composed with a fixed local `offset` (dx, dy). This
    makes the prop move exactly as much as the character's real, already-
    authored motion moves it, and not a pixel more -- nothing about the
    character's own motion is invented or recomputed, and the prop's
    placement is a fixed choice, not a fabricated animation.

    `target_symbol` may itself be a previously generated composite (e.g. the
    output of `render_lipsync`) already sitting in `extract_dir`.
    """
    prop_src_path = _symbol_xml_path(prop_extract_dir, prop_symbol)
    prop_xml = open(prop_src_path, encoding="utf-8").read()
    prop_name = f"Prop_{re.sub(r'[^A-Za-z0-9_]', '_', os.path.basename(prop_symbol))}_{uuid.uuid4().hex[:6]}"
    old_name_m = re.search(r'\bname="([^"]+)"', prop_xml)
    old_item_id_m = re.search(r'\bitemID="([^"]+)"', prop_xml)
    if old_name_m:
        prop_xml = prop_xml.replace(f'name="{old_name_m.group(1)}"', f'name="{prop_name}"', 1)
    new_item_id = f"00aa00{uuid.uuid4().hex[:10]}"
    if old_item_id_m:
        prop_xml = prop_xml.replace(f'itemID="{old_item_id_m.group(1)}"', f'itemID="{new_item_id}"', 1)

    lib_dir = os.path.join(extract_dir, "LIBRARY")
    prop_dst_path = os.path.join(lib_dir, f"{prop_name}.xml")
    open(prop_dst_path, "w", encoding="utf-8").write(prop_xml)

    doc_path = os.path.join(extract_dir, "DOMDocument.xml")
    doc = open(doc_path, encoding="utf-8").read()
    include = f'          <Include href="{prop_name}.xml" itemIcon="1" loadImmediate="false" itemID="{new_item_id}" lastModified="1"/>\n'
    if f'{prop_name}.xml"' not in doc:
        doc = doc.replace("     <symbols>\n", "     <symbols>\n" + include)
        open(doc_path, "w", encoding="utf-8").write(doc)

    xml_path = _symbol_xml_path(extract_dir, target_symbol)
    root = ET.parse(xml_path).getroot()
    dx, dy = offset
    prop_frames_xml = []
    for layer in root.iter():
        if _local(layer.tag) != "DOMLayer":
            continue
        if layer.get("name") != parent_layer:
            continue
        frames = [f for f in layer.iter() if _local(f.tag) == "DOMFrame"]
        for f in frames:
            idx = int(f.get("index"))
            dur = int(f.get("duration", 1))
            inst = _first_instance(f)
            if inst is None:
                continue
            a, b, c, d, tx, ty = _matrix_attrs(inst)
            comp_tx = a * dx + c * dy + tx
            comp_ty = b * dx + d * dy + ty
            is_tween = f.get("tweenType") == "motion"
            tween_attrs = ' tweenType="motion" motionTweenSnap="true"' if is_tween else ""
            mparts = []
            if abs(a - 1) > 1e-9 or b or c or abs(d - 1) > 1e-9:
                mparts += [f'a="{a}"']
                if b: mparts.append(f'b="{b}"')
                if c: mparts.append(f'c="{c}"')
                mparts += [f'd="{d}"']
            mparts += [f'tx="{comp_tx}"', f'ty="{comp_ty}"']
            prop_frames_xml.append(f'''<DOMFrame index="{idx}" duration="{dur}" keyMode="9728"{tween_attrs}>
              <elements>
                <DOMSymbolInstance libraryItemName="{prop_name}" symbolType="graphic" loop="loop">
                  <matrix><Matrix {" ".join(mparts)}/></matrix>
                </DOMSymbolInstance>
              </elements>
            </DOMFrame>''')
        break

    if not prop_frames_xml:
        raise RuntimeError(f"'{target_symbol}' me '{parent_layer}' naam ki layer nahi mili.")

    layers_xml = []
    inserted = False
    for layer in root.iter():
        if _local(layer.tag) != "DOMLayer":
            continue
        name = layer.get("name")
        frames = [f for f in layer.iter() if _local(f.tag) == "DOMFrame"]
        out_frames = [ET.tostring(f, encoding="unicode") for f in frames]
        if name == "Face" and not inserted:
            layers_xml.append(f'        <DOMLayer name="Favda">\n          <frames>\n' +
                               "\n".join(prop_frames_xml) + "\n          </frames>\n        </DOMLayer>")
            inserted = True
        layers_xml.append(f'        <DOMLayer name="{name}">\n          <frames>\n' +
                           "\n".join(out_frames) + "\n          </frames>\n        </DOMLayer>")
    if not inserted:
        layers_xml.insert(0, f'        <DOMLayer name="Favda">\n          <frames>\n' +
                           "\n".join(prop_frames_xml) + "\n          </frames>\n        </DOMLayer>")

    xml = f'''<DOMSymbolItem xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns="http://ns.adobe.com/xfl/2008/" name="{out_symbol_name}" itemID="00bb00{uuid.uuid4().hex[:10]}" symbolType="graphic" lastModified="1" lastUniqueIdentifier="1">
  <timeline>
    <DOMTimeline name="{out_symbol_name}" layerDepthEnabled="true">
      <layers>
{os.linesep.join(layers_xml)}
      </layers>
    </DOMTimeline>
  </timeline>
</DOMSymbolItem>
'''
    out_xml_path = os.path.join(lib_dir, f"{out_symbol_name}.xml")
    open(out_xml_path, "w", encoding="utf-8").write(xml)

    doc = open(doc_path, encoding="utf-8").read()
    out_item_id = f"00cc00{uuid.uuid4().hex[:10]}"
    include = f'          <Include href="{out_symbol_name}.xml" itemIcon="1" loadImmediate="false" itemID="{out_item_id}" lastModified="1"/>\n'
    if f'{out_symbol_name}.xml"' not in doc:
        doc = doc.replace("     <symbols>\n", "     <symbols>\n" + include)
        open(doc_path, "w", encoding="utf-8").write(doc)

    return out_symbol_name


def doc_frame_rate(extract_dir, default=24):
    """The frame rate the artist authored the file at -- playing the frames
    back at any other rate makes the motion look sped-up or choppy."""
    doc_path = os.path.join(extract_dir, "DOMDocument.xml")
    try:
        root = ET.parse(doc_path).getroot()
        return float(root.get("frameRate", default))
    except (OSError, ET.ParseError, ValueError):
        return float(default)


def _rsvg(args):
    subprocess.run(["rsvg-convert", *args], check=True)


def render_preview(extract_dir, symbol_path, out_path, max_frames=300, out_size=1080, fps=None,
                   min_seconds=0.0):
    """Render a symbol's own timeline to an mp4 at the file's authored frame
    rate. If the timeline is shorter than `min_seconds`, it loops."""
    xml_path = os.path.join(extract_dir, "LIBRARY", *symbol_path.split("/")) + ".xml"
    if not os.path.exists(xml_path):
        raise RuntimeError(f"Symbol '{symbol_path}' library me nahi mila.")
    info = _analyze_symbol_file(xml_path)
    if info is None:
        raise RuntimeError(f"'{symbol_path}' ek valid symbol nahi hai.")

    if fps is None:
        fps = doc_frame_rate(extract_dir)
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
        coarse_jobs = []
        for svg_path in svgs:
            data = open(svg_path, encoding="utf-8").read()
            data = re.sub(r'viewBox="[^"]*"', f'viewBox="{wide_off} {wide_off} {wide_span} {wide_span}"', data)
            data = re.sub(r'width="[^"]*px"', f'width="{coarse_size}px"', data)
            data = re.sub(r'height="[^"]*px"', f'height="{coarse_size}px"', data)
            fixed_svg = svg_path + ".coarse.svg"
            open(fixed_svg, "w", encoding="utf-8").write(data)
            png_path = svg_path + ".coarse.png"
            coarse_jobs.append((["-w", str(coarse_size), "-h", str(coarse_size), fixed_svg, "-o", png_path], png_path))
        with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
            list(pool.map(_rsvg, [j[0] for j in coarse_jobs]))

        union = None
        for _, png_path in coarse_jobs:
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
        fine_jobs = []
        for svg_path in svgs:
            data = open(svg_path, encoding="utf-8").read()
            data = re.sub(r'viewBox="[^"]*"', f'viewBox="{cx0} {cy0} {side} {side}"', data)
            data = re.sub(r'width="[^"]*px"', f'width="{raster2}px"', data)
            data = re.sub(r'height="[^"]*px"', f'height="{raster2}px"', data)
            fixed_svg = svg_path + ".fine.svg"
            open(fixed_svg, "w", encoding="utf-8").write(data)
            raw_png = svg_path + ".fine.png"
            fine_jobs.append((["-w", str(raster2), "-h", str(raster2), fixed_svg, "-o", raw_png], raw_png))
        with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
            list(pool.map(_rsvg, [j[0] for j in fine_jobs]))

        n_unique = len(fine_jobs)
        for i, (_, raw_png) in enumerate(fine_jobs, start=1):
            im = Image.open(raw_png).convert("RGBA")
            if raster2 != out_size:
                im = im.resize((out_size, out_size))
            canvas = Image.new("RGBA", (out_size, out_size), (24, 24, 24, 255))
            canvas.alpha_composite(im, (0, 0))
            canvas.convert("RGB").save(os.path.join(frame_dir, f"f_{i:04d}.png"))

        n_out = max(n_unique, int(round(min_seconds * fps)))
        for i in range(n_unique + 1, n_out + 1):
            src = os.path.join(frame_dir, f"f_{(i - 1) % n_unique + 1:04d}.png")
            os.link(src, os.path.join(frame_dir, f"f_{i:04d}.png"))

        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-y", "-framerate", str(fps),
             "-i", os.path.join(frame_dir, "f_%04d.png"),
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", out_path],
            check=True, capture_output=True,
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)
