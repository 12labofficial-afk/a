# Core rule for this project (non-negotiable)

Every character/animation request must go through the actual deployed FLA
tool (upload -> detect -> preview/lipsync via the API), never by hand-digging
into `.fla`/XFL XML and writing a one-off script for that one request.

- Never invent motion (guessed rotation angles, guessed matrices) that isn't
  actually in the file. Only use real per-part data: real pivots, real
  keyframes, real matrices already authored by the artist.
- Combining multiple REAL pieces (e.g. a real back-walk + a real sit-pose)
  is fine, but only once explicitly OK'd by the user for that case -- it is
  different from inventing new motion.
- When something looks "off" visually, check whether it's already present
  in the ORIGINAL unmodified render before assuming it's a bug you
  introduced (several "bugs" turned out to be genuine quirks/gaps in the
  original artist's rig).
- If a fix would require guessing without a concrete reproducible example,
  ask the user for a screenshot/timestamp rather than blindly changing
  code that might already be correct.

## Where things live

- `backend/app/fla_inspector.py` -- all FLA/XFL parsing, animation
  detection, preview rendering, lip-sync generation, and real-rig
  extraction (`extract_character_parts`, `render_part_cutout`).
- `backend/app/main.py` -- FastAPI endpoints: `/api/fla/upload`,
  `/api/fla/{fla_id}/animations`, `/api/fla/{fla_id}/preview`,
  `POST /api/fla/{fla_id}/lipsync`, `GET /api/fla/{fla_id}/rig`.
- `backend/app/audio_utils.py` -- `DialogueAudio` (RMS amplitude envelope
  from an uploaded audio file), reused by the lip-sync feature.
- `frontend/rig_editor.html` + `frontend/rig_editor.js` -- the manual
  rig-posing/animation editor (see its own section below).
- Deployed HF Space: `yashsharma463/Otsm` (flat file layout, no
  subfolders, since HF's browser upload doesn't preserve folder structure).

## xfl2svg layer-order convention

In a `<DOMTimeline><layers>` list, the layer listed FIRST renders FRONT-most
(on top); the layer listed LAST renders BACK-most. (`svg_renderer.py`
processes `reversed(list(enumerate(layers)))`, i.e. back-to-front, so the
first-listed layer is drawn last = on top.) Never reorder layers when
generating a composite symbol -- always preserve the original file's own
`<layers>` order exactly.

This reversal is `<DOMLayer>`-siblings-only. Multiple `<DOMSymbolInstance>`
elements sitting together inside ONE layer's `<elements>` block (a real
armature layer commonly holds every rig part this way) are walked by
`svg_renderer.py` with a plain `enumerate()`, no `reversed()` -- so THEIR
order is plain-SVG-native: first-in-document = drawn first = BACK-most,
last-in-document = FRONT-most. Applying the layer rule to these siblings
too (tried once while debugging the rig editor) is backwards and was
reverted -- always preserve their real file order as-is, don't reverse it.

## Lip-sync feature (`render_lipsync` in fla_inspector.py)

Auto-detects a real mouth/lip sub-symbol inside a target animation and
swaps it frame-by-frame based on an uploaded audio's amplitude. Every
mouth pose shown is a real keyframe lifted from the file; only *which* one
plays at each instant is audio-driven. Two real bugs already found and
fixed here -- don't reintroduce either:

1. **Gesture tweens must stay audio-driven too, not just holds.** A tween
   frame's own matrix/easing is real interpolated motion we must never
   invent -- so we never subdivide or recompute it. But early on, tween
   frames kept the mouth frozen on its pre-tween pose for the tween's whole
   duration (in "Long Talk" that was ~22% of the clip, in ~0.2s bursts),
   which made the mouth look like it was lagging behind the audio and then
   jump-cutting to catch up. Fix: for tween frames, keep the DOMFrame's
   matrix/tween attributes 100% untouched, but still swap the
   `libraryItemName` on the instance to the correct audio-driven mouth
   variant (sampled at the tween's midpoint).

2. **Calibrate mouth-state thresholds to the clip's own loudness, not a
   fixed constant.** A normal speaking voice's RMS envelope rarely gets
   anywhere near an absolute 0.5 ceiling, so a fixed threshold meant the
   loudest real mouth poses (wide-open/round-O) never got picked and the
   mouth kept cycling through just the bottom 1-2 states -- which reads as
   "the same shape repeating on loop". Fix: scale the amplitude-to-state
   bucketing against that clip's own 95th-percentile loudness
   (`np.percentile(audio.envelope, 95)`), so all the real captured mouth
   keyframes actually get used, for any audio file, not just one specific
   clip.

## Looping a short real animation to cover longer audio (render_lipsync)

A short real animation (e.g. a ~20-frame walk cycle) needs its real
keyframes REPEATED to cover a longer audio track -- never invented, just
looped, same as render_preview's own min_seconds looping.

Watch out: some characters' rig (e.g. Motu Sheth's "Mukhiya copy 2" walk)
has EVERY body part natively using `loop="loop"` + `firstFrame=` internally
(unlike "Long Talk", which uses plain tween/hold matrices and only ONE
nested loop). Confirmed by direct timing: xfl2svg renders such a rig's
body alone just fine (177 frames in ~0.3s) and the audio-swapped face
alone is fine up to ~40 fragments, but rendering body + face TOGETHER in
one symbol -- or pushing the face past ~40 fragments alone -- triggers a
severe, sharply nonlinear slowdown in xfl2svg's own nested-loop resolution
(44 fragments: 25s+ and still climbing; not a bug in our own XML, and not
fixable by restructuring it further -- confirmed by isolating body-only,
face-only, and combined renders separately with direct timing before
concluding this). The fix already in `render_lipsync`: when looping is
needed, render the body-only and face-only layers as two SEPARATE symbols
against one shared, precomputed viewBox, then alpha-composite them in
Python; the face render is additionally capped at a safe fragment count
(`2 * cycle_len`) and loops at the PNG level past that. Don't try to fix
this by tweaking XML generation again without re-confirming with direct
`subprocess` timing first -- several plausible-looking XML fixes (stripping
inherited `loop`/`firstFrame` attributes, wrapping in a single loop
symbol) were tried and directly measured to NOT help; the split-render
approach is the one that's actually proven fast.

## Real bone/IK animations (list_scene_timelines, has_ik_bones)

Adobe's real Bone Tool data does NOT use a `<DOMArmature>` tag in modern
exports (an earlier wrong assumption) -- it's `<DOMLayer animationType="IK
pose">` containing `<DOMFrame tweenType="IK pose" isIKPose="true"
poseLocations="...">` with a real `<IKTree>`/`<IKNode>`/`boneName=` bone
hierarchy. `grep -ril "IKTree\|animationType=\"IK pose\""` finds it;
`DOMArmature` does not. Every symbol/scene analysis now sets
`has_ik_bones` -- check that field, don't grep for the wrong tag again.

Real bone-rigged animations can live in TWO different places, and both
must be checked -- an earlier turn wrongly told the user a file had no
walk cycle because it only checked LIBRARY symbols:
- Inside a LIBRARY symbol (`_analyze_symbol_file` catches this normally).
- Directly on the Stage/Scene timeline (`DOMDocument.xml`'s own
  `<DOMTimeline>`, e.g. "Scene 1") -- INVISIBLE to any LIBRARY-only scan.
  `list_scene_timelines()` finds these and `list_animated_symbols()`
  includes them automatically now, as `"Scene/<name>"` entries.
  `render_preview()` renders a `"Scene/<name>"` path via xfl2svg's own
  `--timeline-type scene` instead of treating it as a library symbol.
xfl2svg renders real IK-pose animation correctly (confirmed: two separate
files, both a clean real walk cycle, rendered with no crash beyond the
usual gradient/mask warnings) -- so once found, it's just as renderable
as any other real animation, nothing special needed beyond `--timeline-type
scene`.

## Manual rig-posing/animation editor (rig_editor.html/js, extract_character_parts)

`GET /api/fla/{fla_id}/rig?symbol=...` -> `extract_character_parts` pulls a
symbol's REAL parts out of the file: each part's real matrix, and -- only
when the file genuinely has one -- its real parent from the `<IKTree>` bone
hierarchy (walked recursively via ElementTree over nested `childNodes`, not
a flat regex, or nesting depth is lost). When there's no real IK tree, parts
come back with no parent and the human assigns one by hand in the editor;
hierarchy is never guessed. `render_part_cutout` renders each part to its
own transparent PNG on a FIXED viewBox centered on the part's local origin
(not auto-fit), so a real per-frame matrix can be reapplied to it later and
land it correctly.

Real per-part matrices as stored in the file are ABSOLUTE (in the character
symbol's own coordinate space), not relative to a parent part.
`extract_character_parts` converts each non-root part to a PARENT-LOCAL
matrix (`local = inverse(parent_absolute) . child_absolute`) so the editor
can nest each part inside its parent's SVG `<g>` and get "child follows
parent" for free from SVG's own transform composition, instead of
propagating drags by hand. Verified by recomposing: `parent_world .
local` reproduces the original absolute matrix to ~1e-13 (float noise).

Two real bugs already hit building this -- don't reintroduce either:

1. **A code fix on disk means nothing to an already-running server.** The
   absolute-to-local conversion above was correct in `fla_inspector.py`
   the whole time it was being debugged, but the running `uvicorn`
   process had been started BEFORE that code was written, so every
   `/rig` request it served was still returning raw absolute matrices
   (Python doesn't hot-reload a module already imported into a running
   process; this server is started with no `--reload`). Symptom looked
   exactly like a math bug: each part's world matrix ended up scaled by
   an extra copy of its parent's scale (a 3-deep chain literally rendered
   at scale^3, e.g. the head buried tiny behind the torso). Before
   concluding a math/data bug when server output disagrees with a
   `python3 -c` check of the same function, restart the actual server
   process and recheck -- a stale process is a real, recurring trap in
   this sandbox (see also the earlier `nohup ... & disown` unreliability
   noted in session history; prefer the Bash tool's `run_in_background`).
2. **The selection-highlight box must not outline the full cutout
   canvas.** Every part's PNG is rendered onto the SAME fixed-size
   `half_extent` box regardless of that part's real on-screen size (a
   tiny fingertip gets the identical box as the head). Outlining that
   whole box (via CSS `outline` on the image's own element) looked fine
   for big parts but, for a small part several bone-levels deep, turned
   into a huge misleadingly rotated box once every ancestor's rotation
   composed into it. Fixed with a small FIXED-size marker `<rect>` at the
   part's own origin instead of outlining the cutout canvas.

The retarget tab matches a recorded/loaded animation JSON's parts to a
DIFFERENT character's real parts by NAME and reports any that don't match
(`missingParts`) instead of silently dropping or guessing a substitute --
never invent a mapping between two characters' differently-named parts.

## Standalone browser-only rig editor (frontend/rig_editor_standalone.html)

A second, fully self-contained edition of the rig editor above -- ONE html
file (JSZip + a from-scratch XFL-to-SVG renderer + the pose editor UI all
inlined), zero backend, zero network calls once opened. Built because the
first edition needs `backend/app/main.py` + `fla_inspector.py` running
somewhere; this one needs nothing but a browser, including on a phone.

It is NOT a shortcut or a rewrite-from-guesswork -- the renderer is a
line-for-line JS port of xfl2svg's own modules (`shape/edge.py`,
`shape/gradient.py`, `shape/style.py`, `shape/shape.py`, `color_effect.py`,
`svg_renderer.py`), cross-checked against them:
- `extractCharacterParts`'s output for RAJ BHAI matches
  `fla_inspector.extract_character_parts`'s output bit-for-bit (same
  parent-local matrices, e.g. TORSO/HEAF local scale exactly `1.0`, root
  MIDLE PRT scale `0.39996337890625`).
- The renderer's frame-0 output for a whole character was compared against
  `render_preview`'s own proven-correct frame-0 render of the same file --
  matched closely enough (same pose, proportions, colors) to confirm the
  port is faithful, not just "looks plausible".
One deliberate improvement over xfl2svg: RadialGradient IS rendered here
(xfl2svg has zero support for it -- confirmed by reading its own
`parse_fill_style()`), as a real SVG `<radialGradient>` built from the
file's own real gradient stops, not the flatten-to-solid-color workaround
`_repair_unsupported_radial_gradients` needs for the Python pipeline.

Real, reproducible bugs hit while building this -- don't reintroduce any:

1. **A zip's declared central-directory size can be 54 bytes too high.**
   Same Animate export quirk `xfl_reader.py`'s `open_fla()` already works
   around for Python's `zipfile` -- JSZip chokes on it identically. Fixed
   by reading the raw End-Of-Central-Directory record's `cdir_size` field
   and patching it back down by 54 when the math (`file_size - cdir_offset
   - 22`) says that's exactly the discrepancy, before handing the bytes to
   JSZip -- same math as the Python fix, just applied to raw bytes instead
   of intercepting `seek()`/`read()`.
2. **`querySelector('g')` on a whole rendered SVG can silently grab the
   wrong node.** A `<mask>` element (sitting in `<defs>`, appended BEFORE
   the real body) can itself contain a `<g>` -- so a naive `svg.querySelector('g')`
   returns THAT one (document order) instead of the actual top-level
   content group, if the defs happen to be appended first. Symptom looked
   exactly like a broken renderer (tiny wrong-content bounding box, only
   one part visible) even though the renderer was already correct --
   caught by testing the SAME render call two different ways and getting
   two different answers, not by trusting the first measurement. Fixed by
   tagging the real content group (`data-root="1"`) and querying for that
   specifically, never a bare tag name.
3. **`event.currentTarget` is null once the handler that received it
   returns.** A pointerdown handler that saves `evt` itself and reads
   `evt.currentTarget` later from a `pointermove`/`pointerup` closure gets
   `null` -- the DOM clears it after dispatch. Fixed by capturing
   `evt.currentTarget` into a plain variable inside the handler and using
   that in the later closures, never `evt.currentTarget` again after the
   handler that received the event has returned.
4. **`getBBox()` on an SVG inside a `display:none` ancestor fails
   silently.** Auto-fitting the stage's viewBox right after building it
   returned nothing and left a stale viewBox (character invisible, stage
   looked empty) because the parent card was still hidden at that exact
   moment. Fixed by making the container visible BEFORE building/measuring
   the stage, not after.

### Visible skeleton overlay (real joints + bone lines, real constraints)

The real `<IKTree>` carries more than just parent/child names -- each real
`IKNode`/`ChildNode` also has a real `boneName`, and some real files set a
real `rotationEnabled="false"` (seen: 4 joints in RAJ BHAI's own rig, e.g.
TORSO relative to MIDLE PRT) or real translation-constraint attributes
(`xTranslationMin/Max` etc) -- the artist's own limits on that joint, not
something to invent OR ignore. `extractCharacterParts` now also returns
each part's real `boneName` and `rotationEnabled`.

The editor draws a live skeleton (a joint dot at each part's own local
origin, a line from each parent's origin to each child's) using ONLY
numbers already driving the real pose -- a joint dot nested inside that
part's own pose `<g>` lands at its live world position for free (SVG's own
transform composition), and a bone line's endpoint is just that child's
own real matrix translation (`matrix[4], matrix[5]`), kept in sync in
`updateTransforms()`. This is not extra/invented geometry -- decoding the
IKNode's own `location` attribute (a separate, syntactically-similar-to-
edge-format hex-encoded field) was deliberately NOT used for this, since
its exact coordinate space was never verified against ground truth the way
everything else here was; the already-proven real matrices were sufficient
and safer. A joint whose real `rotationEnabled` is `false` renders red
instead of yellow, and the rotation slider shows a note (still usable --
manual posing is allowed to exceed the original rig's own limits, since
the human is explicitly overriding it here -- but the note makes that an
informed choice, not a silent one).

## Real rendering bugs auto-repaired at upload time (repair_and_extract)

`repair_and_extract` now runs a few automatic, non-inventive repair passes
on every uploaded FLA before anything else touches it:

- `_repair_broken_library_refs`: a `libraryItemName` reference that doesn't
  resolve to a real file at that exact path (seen: "DHOTI&#032" vs the real
  file sitting in a subfolder) gets the SAME real file copied to the path
  its instances actually reference -- only when exactly one real file with
  that basename exists; never guesses when ambiguous. Must `html.unescape()`
  the raw regex-captured reference before comparing/copying -- a raw
  "DHOTI&amp;#032" in the file text is the reference "DHOTI&#032" once an
  XML parser (what xfl2svg uses) decodes it, and comparing the undecoded
  form against real filenames silently fails to match.
- `_repair_unsupported_radial_gradients`: xfl2svg has NO RadialGradient
  support at all (confirmed by reading its own `parse_fill_style()` --  it
  just warns and leaves `fill` unset, which then defaults to SVG's implicit
  black). A shape shaded with one -- skin tone is a common case -- renders
  as a solid black silhouette. Fixed by flattening each RadialGradient to a
  flat SolidColor averaged from that SAME gradient's own real stops.
- `_repair_missing_fill_colors`: a separate, unrelated bug with the same
  symptom -- some real shapes have a bare `<SolidColor/>` with no `color`
  attribute (a genuine data gap in the source file), which xfl2svg defaults
  to opaque black too (seen: a black blob across a foot/toes in a sitting
  pose). Unlike the gradient case there's no real color to recover, so
  don't guess one -- make it transparent (`alpha="0"`) instead. A missing
  detail not rendering is honest; a wrong color rendering is not.

If a character's face/hands/skin render solid black, or some other shape
is an inexplicable black blob, check for these two DIFFERENT root causes
(gradient vs. missing color attribute) before assuming a new bug --
`grep -c "RadialGradient"` / `grep -c "<SolidColor/>"` in the relevant
LIBRARY file settles which one it is in seconds.

## Prop attachment (`attach_prop` in fla_inspector.py)

`POST /api/fla/{fla_id}/attach-prop` rigidly attaches a static prop from a
*different* uploaded FLA (e.g. a weapon/tool drawn on its own, like
"favda.fla") to one real layer of a character's animation (e.g. "Body").
Every frame, the prop gets that layer's own real matrix (rotation and all)
composed with a fixed local `(offset_x, offset_y)` -- it rides along with
whatever real motion that layer already has; nothing about the character's
motion is invented. The offset itself is a placement choice (found by
rendering and looking, the same way the Shikari sit-on-rock composite was
built), not a fabricated animation -- that distinction matters if this
comes up again: never skip the "render it and actually look" step before
picking/adjusting an offset.

Prefer parenting to the actual HAND layer (not just "Body") when the prop
should look gripped/held -- attach with `offset=(0,0)` first (that puts the
prop's own origin exactly on the hand's real position), then find the hold
angle with `rotation_deg` alone by rendering and looking; only add a
nonzero offset if the grip point genuinely isn't at the prop's local
origin. This is how Motu Sheth's favda ended up slung from his real right
hand at the hip up over the opposite shoulder (`rotation_deg=-40`), instead
of just resting across both shoulders unheld.

If a request needs a walk cycle and the target character's file doesn't
have one (check every candidate symbol's leg layers for real tx/ty
movement across frames, don't assume from the name) -- say so plainly and
ask how to proceed, don't invent leg motion. Motu Sheth's "Long Talk", for
instance, is a standing/talking animation with zero real leg movement, even
though it has 121 total detected animations.

## Known non-bugs (don't re-investigate these)

- A small black-wedge gap near the shoulder/sleeve seam in some renders is
  present in the ORIGINAL unmodified art at that arm angle -- not something
  the lip-sync/rigging code introduced.
- "Symbol 5" (Motu Sheth file) is a static pose-reference sheet with a
  hard cut, not a choppy animation -- there's no real in-between data to
  smooth.
- "Long Talk"'s brief-tween-then-long-hold rhythm, and its nested
  independently-looping "Right Hand" gesture during holds, are the artist's
  own real keyframe design (limited-animation secondary motion), not a
  frame-rate or smoothness defect.
