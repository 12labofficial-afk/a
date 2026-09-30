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

### Real .ana export (not just .fla), and export must not hide behind a mode

Two real complaints: the export panel lived inside the Move-mode-only
section, so it was invisible whenever the user was in Animation mode --
easy to miss and easy to conclude "there's no export at all". And the
tool only ever exported a plain `.fla`, never a real `.ana` bundle, when
the original upload WAS one.

Fixed both: the "Rig Export" panel is now a normal, always-visible part
of the sidebar (not gated by `editMode` at all) -- exporting the current
corrected rig should never depend on which posing mode happens to be
selected. And `XflProject` now also keeps the ORIGINAL outer bundle zip
(`bundleOuterZip`) and the inner `.fla`'s own entry name
(`bundleInnerEntryName`) whenever `loadProjectFromZipBytes` had to unwrap
an `.ana.zip` bundle to find the real XFL underneath -- previously that
outer zip was simply discarded once unwrapped. `exportCorrectedAna`
reuses the exact same matrix-correction step as `exportCorrectedFla`
(factored out into `_writeCorrectedMatricesIntoZipObj`, shared by both),
then replaces ONLY the inner `.fla` entry inside that retained OUTER zip
-- the swf/preview-PNGs/manifest.json are carried over completely
unchanged, since nothing in this tool ever reads or needs to regenerate
them. Verified with a full round-trip: export a `.ana`, reload that exact
blob as a fresh project, confirm it's still detected as a bundle, and
confirm the corrected rig re-extracts correctly. The `.ana` button is
disabled (with an explanatory note) when the original upload was a plain
`.fla` with no outer bundle to write back into.

### Real bug: rotation ran backwards once the user actually zoomed in

Reported as "jab mai ghumata hu toh ulta ho jata hai" (rotating does the
opposite) right after pan/zoom shipped -- and only reproduced once the
test actually zoomed in first; at zoom 1 (the untouched default) it was
never wrong, which is exactly why it wasn't caught earlier. Root cause:
`svgPoint()` mapped a screen point through `svgEl.getScreenCTM()` alone --
correct for the pan/zoom bookkeeping itself (which stores its `tx/ty` in
that same fixed, un-zoomed root space, by design), but WRONG for
drag/pose math, which needs the point expressed in `viewGroup`'s own
local space (the space every part's real `worldMatrix()`/`pose` already
lives in). At zoom's identity transform the two spaces are numerically
identical, hiding the bug completely; any real zoom or pan exposed it,
including sign-flipping the rotation direction. Fixed with a second
method, `localPoint()`, that inverts `viewGroup.getScreenCTM()` instead
(which already reflects the FULL chain up to and including viewGroup's
own current transform) -- used only by the two drag/rotate call sites in
`_onPointerDown`/`_onPointerMove`; the pan/zoom code keeps using the
original `svgPoint()` on purpose. Verified two ways before believing the
fix: a live-browser test dragging a known clockwise arc while zoomed
(previously swept backwards and at the wrong magnitude, now swept exactly
the dragged angle), and a standalone port of the exact matrix math in
Node against an intentionally mirrored parent (to rule out a second,
independent hypothesis -- that a mirrored ancestor could also flip the
sign -- which measurement disproved: a mirror's effect on the angle
cancels out by construction once the same mirrored parent is recomposed
for rendering, so it was never actually a real bug).

### Adobe-Animate-style posing aids (timeline scrubber, onion skin, snap, nudge)

Four small additions that make manual posing feel closer to Animate's own
editor, without inventing anything about the real rig data itself:
- A visual timeline strip (a ruler track with keyframe diamonds and a
  draggable playhead) alongside the plain frame-number input -- click a
  diamond to jump, drag anywhere on the track to scrub, matching Animate's
  own timeline instead of only a bare number field.
- Onion skinning: the neighboring keyframes' REAL poses (same real
  `poses[name]` data already stored on each keyframe) rendered a second
  time at low opacity via a fresh `worldMatrix`-style composition against
  that keyframe's own pose map (`_worldMatrixFromPoses`, a pure function
  parallel to `worldMatrix()` but reading an arbitrary pose map instead of
  live `this.pose`) -- a comparison guide, never new/interpolated data.
- 15° rotation snapping (a checkbox, since touch has no Shift key; Shift
  also works on desktop) -- same idea as Animate's Free Transform
  constrain-angle behavior.
- Arrow-key rotation nudge (±1°, Shift=15°) for precise correction
  without dragging. Only the FIRST keydown of a held-key OS auto-repeat
  run (`!evt.repeat`) pushes undo history, or holding the key floods the
  undo stack with one entry per repeat tick instead of one per gesture --
  same reasoning already applied to the rotation slider's `pointerdown`-
  gated history push. Also: only skip the shortcut for a focused
  TEXT-entry field (`input[type=text/number]`, `select`, `textarea`) --
  checking only `tagName === "INPUT"` blocked the shortcut whenever a
  checkbox merely had focus, since a checkbox is an `<input>` too.

### Bone-overlay legibility: root joint color, and direction arrows

Two small but real usability requests once bones were actually visible: a
distinct color for the RIG's root joint (no real parent) so it reads as
"the anchor" at a glance -- purple, vs. yellow for a normal joint and red
for a real rotation-locked one (data-root="1" set once, in `_buildDom`,
never guessed at render time). And a direction arrow on every bone line,
parent -> child. First attempt used a real SVG `<marker>` (`marker-end`)
at the LINE's own endpoint -- which is exactly where the CHILD's own
joint dot also sits, and since dots are drawn after lines, the dot fully
covered the (much smaller) arrowhead marker; it never showed up in an
actual screenshot despite being "correctly" wired. Fixed by drawing the
arrow by hand instead, as a small triangle `<polygon>` positioned and
rotated (via `atan2` of the parent->child vector) at the line's MIDPOINT
-- nothing else sits there, so it can't be covered by any dot.

### Pan/zoom and undo/redo (mobile precision + editing safety)

Mobile precision problem: a tiny bone (a finger, an eyebrow) is hard to
grab accurately on a small touchscreen with no way to zoom in, since
`touch-action: none` on the stage deliberately disables the browser's own
pinch/pan (needed so a one-finger drag can pose a part instead of
scrolling the page). Fixed with the editor's OWN pinch/pan, implemented as
a single wrapper `<g class="view-transform">` around all rendered content,
transformed on top of the (otherwise fixed) fitted viewBox -- deliberately
NOT by rewriting the viewBox itself. This matters: `svgPoint()` (used for
all drag/pose math) maps screen -> the SVG root's own user space via
`getScreenCTM()`, which reflects only the fixed viewBox, never a
descendant group's own transform -- so pan/zoom is provably a pure display
convenience that cannot perturb pose math, at any zoom level. Pinch-to-
zoom anchors on the real pinch midpoint (mapped to that same fixed root
space) so the point under your fingers stays put as you zoom, not the
character's origin. `+`/`-`/`Fit` buttons give the same control without
a touchscreen. A real gotcha hit while testing multi-pointer (pinch) input
programmatically: `setPointerCapture()` can throw for a second
simultaneous pointer, and an uncaught throw there aborted the rest of that
pointerdown handler -- so the pinch's second finger never got past
`onDown` far enough to actually start the pinch. Fixed by wrapping every
`setPointerCapture()` call in try/catch, since it's a best-effort
reliability aid (keeps delivering move events if a finger slides off the
element), never a precondition for the gesture to work at all.

Undo/redo: a full JSON-cloned snapshot (every part's matrix + parent,
current `pose`, and `keyframes`) is pushed onto `RigView.undoStack` BEFORE
every mutating action (drag start, a rotation-slider interaction's first
`input` tick -- not every tick, or one slider drag would fill the stack
with useless intermediate states --, reparent, reset, keyframe record,
JSON import). This is deliberately a whole-state snapshot, not a diff or
an action log: with pose data this small (tens of parts, a handful of
numbers each), a snapshot is cheap enough that there's no need to
correctly enumerate every possible mutation's inverse by hand -- and a
missed inverse would silently corrupt history, while a missed snapshot
call just means one action isn't undoable, a far safer failure mode.

### Two edit modes: Animation (rotate-only) vs Move Parts (rig calibration)

The rotate-only drag above is correct for POSING, but sometimes a part's
own art genuinely doesn't sit exactly on its bone (the artist's registration
point wasn't quite at the visual joint) and needs a one-time correction,
not a pose. So the editor has an explicit mode toggle:
- **Animation** (default): drag rotates around the fixed real joint, as
  above -- for posing/keyframing, parts can never separate.
- **Move Parts**: drag free-translates (and the rotation slider free-
  rotates) a part, and COMMITS the result as that part's new REST matrix
  (`RigView._commitBase`) -- this is rig calibration, not a pose to record,
  so it must persist as the new baseline rather than live in `pose` only.
Never let Move-mode edits leak into `pose` alone without also committing
to `part.matrix`, or the correction is lost the moment a keyframe/frame
change resets `pose` back to the old base.

### Exporting a calibrated rig back to a real, re-uploadable .fla

`exportCorrectedFla` writes Move-mode corrections back into the REAL XFL
XML they came from and re-zips it as an actual `.fla` the tool's own
upload flow accepts unchanged -- not a custom/invented format. It touches
ONLY the exact `<DOMSymbolInstance>` elements this rig's parts came from
(matched by their own real `name` attribute, kept internally as
`part._ikName` specifically for this -- never deleted like the public
`ikName` field, since without it there'd be no way to find the same
instance again to correct it) and leaves every other file in the project
zip byte-for-byte untouched. Requires the ORIGINAL zip object, not just
the XML-text cache used for reading (`XflProject.zipObj`, retained from
`loadProjectFromZipBytes`'s already-unwrapped real `.fla` zip -- an
`.ana.zip` bundle's outer wrapper (swf/previews/manifest) is deliberately
NOT reproduced, since a plain `.fla` round-trips through this same tool's
upload just fine and there's nothing real to regenerate for the rest).
Corrected matrices are each part's real ABSOLUTE matrix (parent-local
`part.matrix` composed up the real parent chain, root's own matrix already
being absolute) -- writing back the parent-local value directly would be
wrong, since the file's own `<Matrix>` attributes are always absolute.
Verified by a full round-trip: export, reload the exported blob as a
fresh project, re-run `extractCharacterParts` on it, and confirm the same
part count, same hierarchy, and the corrected matrix survives (to float-
rounding noise from the text round-trip, same ~1e-13 order as every other
matrix check in this tool).

### Dragging must rotate a bone around its own joint, never translate it

First posing pass let a drag freely translate the dragged part's own local
matrix -- which moves its joint (the point it's rigidly attached to its
parent at) away from where it's really anchored, so any real seam (a
sleeve meeting a shoulder, a head meeting a neck) visibly pulls apart the
moment you drag. A real bone doesn't stretch or slide at its own joint --
only the ANGLE there changes. Fixed by never touching `startLocal[4],[5]`
(the part's real, authored joint position) during a drag: the pointer's
motion is converted to an angle around that fixed point (in the parent's
own local frame, via `parentInv`) and only the ROTATION component of the
part's matrix is ever updated. A part with NO parent (the rig's own root)
has no joint to preserve, so it still free-translates -- that's how the
whole character gets repositioned on stage. This guarantees a bone can
never visually detach from its parent no matter how far it's dragged.

### Real z-order (paint order) is INDEPENDENT of the real bone hierarchy

A second, more serious bug this same rotate-drag fix exposed once bones
were rotated far from rest: a part rotated near/behind its own parent's
own art started rendering IN FRONT of it every time, however it was
posed -- e.g. a real right-arm bone (`UP HND R`) whose real file position
comes BEFORE (i.e. paints behind) its own parent (`TORSO`), confirmed
directly against the real file open in Adobe Animate's own Library/Stage
(a real hand meant to sit on a layer behind the body). The bug: the first
version nested every part's rendered content inside its PARENT's own SVG
`<g>` (parent's own art, then children's `<g>`s appended after it) --
which conflates two things that are actually independent real facts about
an XFL file: the IK bone tree (parent/child, for pose inheritance only)
and the real paint/stacking order (which part of the file gets drawn over
which other part, completely independent of whose bone is whose parent).
Nesting-for-render always paints a child over its own parent's art, which
is wrong whenever the real file's own z-order says otherwise.

Fixed by decoupling the two: `extractCharacterParts` now also records each
part's real `paintOrder` (walking layers back-to-front and elements within
a layer in real file order -- the exact same traversal `renderTimeline`
already uses, just recording a running index instead of appending SVG
nodes). The editor renders every part in its OWN flat, un-nested SVG `<g>`,
inserted into the DOM in real `paintOrder` (not hierarchy order) so SVG's
own painter's-order semantics do the right thing regardless of bone
depth. The bone tree is used ONLY for `worldMatrix()` -- a pure function,
no DOM nesting involved -- and every part's flat group's `transform` is
set directly to its own live world matrix, recomputed for every part on
every pose change. Bone-tree depth and paint order can now differ freely,
exactly like the real file. (A welcome side effect: joint-dot circles,
now positioned by world coordinates directly instead of inheriting
compounded per-branch scale from nested ancestors, finally render at a
consistent, real screen size everywhere instead of varying wildly by how
deep a bone sat in its own chain.)

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

### Real bug: joint dots/bone lines and rotation itself used the wrong anchor point

Reported as "rigging toh body parts ke upar ki hui hai... hamari html file
mein toh vaisa hai hi nahi" (in the real reference the rig sits ON the
body parts; ours didn't). Root cause: every joint dot, bone-line endpoint,
and the CENTER OF ROTATION during a drag all assumed a part's real joint
sits at its own local origin (0,0), i.e. wherever the world matrix's raw
translation (`wm[4], wm[5]`) places it. False for many real parts -- the
artist's actual registration point is the file's own real
`transformationPoint`, already extracted per part into `part.pivot` by
`instancePivot()` but never actually used anywhere until now. Verified by
direct visual A/B, not by guessing: overlaying both the origin's world
position (red dots) and the pivot's world position (green dots) on the
same real render (`RAJ  BHAI`) showed green landing exactly on the real
neck/shoulder/elbow/wrist/hip/knee/ankle joints across the WHOLE
character, while red floated off the body entirely for several parts
(e.g. one leg joint sitting in empty space beside the leg, the head joint
floating above the hair).

Fixed in the standalone editor's `ui.js`/`app.js`:
- `matWithRotation(m, angleDeg)` (always rotated around local origin) was
  replaced outright with `matWithRotationAroundPivot(m, pivot, angleDeg)`,
  which rotates while keeping a GIVEN local point's WORLD position fixed.
  Reduces exactly to the old behavior when `pivot=(0,0)`, confirming it's
  a correct generalization, not a new/different formula.
- The drag handlers (`_onPointerDown`/`_onPointerMove`) now track the
  rotation angle relative to `part.pivot` (transformed into the parent's
  local frame), not the part's local origin, and call
  `matWithRotationAroundPivot(startLocal, part.pivot, targetDeg)`.
- The rotation slider and the arrow-key nudge handler (both in `app.js`)
  now look up the selected part's real pivot and pass it through the same
  way -- three call sites total, all updated together (a partial update
  would have been a real regression, since the old function was deleted,
  not kept alongside the new one).
- `updateTransforms()` now positions every joint dot and bone-line
  endpoint (and the bone-arrow midpoint/angle) via
  `applyMatToPoint(worldMatrix, part.pivot)` instead of the raw
  `wm[4], wm[5]` translation.

Verified after the fix: re-ran the full existing regression suite
(drag/keyframe/export, retarget, move-mode `.fla`/`.ana` round-trips, JSON
import, zoom/undo/redo, timeline/onion/snap/nudge, rotation-direction
sweep tests) with zero behavior changes other than the anchor point
itself, then re-captured the same overlay screenshots against the
ACTUAL shipped file -- every joint now sits precisely on real anatomy.

### Mobile: Timeline moved out of the sidebar, right under the stage

Reported: "keyframe vagera jo h usko vaisa karo ki mobile screen pe baar
baaar scroll na karna pade vahi par animation karke mai kaam saku" (don't
make me scroll back and forth for keyframe controls -- let me animate
right there at the stage). Root cause: the Timeline panel (frame number,
Keyframe Record, Play/Stop, keyframe chip list) lived at the BOTTOM of
`.sidebar`, after the Parts list and the Rig Export panel -- and on
mobile, `.editor-layout`'s grid collapses to one column, so the sidebar
renders entirely BELOW the stage. Posing a part (drag on stage) and then
recording a keyframe for it meant scrolling down past the stage, then
further down past Parts and Export, hitting Record, then scrolling all
the way back up to see the character again for the next pose -- on every
single keyframe.

Fixed by moving the whole Timeline `<div>` out of `.sidebar` and into the
SAME grid column as the stage, directly after `.stage-wrap`'s closing tag
(`frontend/rig_editor_standalone.html`, inside `.editor-layout`). This is
a pure DOM relocation -- every element id is unchanged and none are
duplicated, so no JS needed to change. Effect: on desktop (2-column grid)
Timeline now sits right under the stage instead of at the bottom of a
separate sidebar column, which is also the more natural pairing (posing
and keyframing are one continuous action); on mobile (1-column collapse)
Timeline is now the very next thing after the stage -- measured directly
in a real mobile-viewport (390x844) browser test: 12px gap from the
bottom of the stage to the top of the Timeline panel, versus ~368px down
to where the Parts/Export sidebar now starts. Parts list, the
selected-part panel (rotation slider, reparent), and Rig Export stayed in
`.sidebar` -- they're secondary to the pose-then-keyframe loop the
complaint was actually about.

### Keyframe Record now auto-advances; bones/joints hidden by default; a real bone-arrow CSS bug

Requested: "maine keyframe pe click kar diya apne aap ek keyframe us frame
ko capture kar lega then next time keyframe pe click karu toh vo collect
ho jayega" (click Record, it captures the current frame; click again
later, it collects another) -- `recordKeyframe()` already did the actual
capturing/collecting correctly (`RigView.recordKeyframe` in `ui.js`), but
the Frame number never moved on its own, so a second click without
manually retyping a new frame number just overwrote the SAME keyframe.
Fixed: `recordBtn`'s click handler now bumps `currentFrame` by 1 and
updates the Frame field right after recording, so posing + tapping Record
repeatedly (no typing) naturally builds up a whole keyframe sequence.
Recording again at a frame that already has a keyframe still just
overwrites that one (unchanged, deliberate).

Also requested: "joint dikhe nahi, parts me hi accha sa shape rahe human
body jaisa" (don't show joints, just a clean human-body shape). The
"Bones dikhao" checkbox already existed for exactly this and doesn't
affect posing at all -- drag targets are each part's own `[data-part]`
SVG group, completely separate elements from the `.bone-line`/
`.bone-joint` overlay, so hiding the overlay never disables dragging.
Made it the DEFAULT (checkbox starts unchecked) so the character looks
clean immediately on load, toggle-able back on when precise joint
selection is needed. While doing this, found a real (if minor) CSS bug:
the "hide bones" rule (`.hide-bones .bone-line, .hide-bones .bone-joint`)
never listed `.bone-arrow-head` -- so unchecking "Bones dikhao" hid the
lines and dots but left the little direction-arrow triangles floating on
their own. Fixed by adding `.bone-arrow-head` to that same CSS rule.

### Real vs. by-design "part separated from its parent" -- Move Parts mode is a free drag, Animation mode never is

Reported with a screenshot: a part appeared disconnected from the part
above it, unlike Adobe's own rig where a part never detaches ("rubber"
behavior) when you rotate something. Investigated by direct reproduction
rather than guessing: in "Animation" mode, a drag is proven rotate-only
around the part's real pivot (`matWithRotationAroundPivot`, see the pivot
fix above) -- the joint's world position is mathematically fixed during
the whole drag, so a part CANNOT detach this way, verified again here by
directly mutating a part's pose translation in a live render and
comparing: only a changed TRANSLATION (`pose[name][4]`/`[5]`) produces
the visible gap-with-a-long-stretched-bone-line the user described, never
a pure rotation. "Move Parts" mode's whole point IS a free
translate/rotate (see "Two edit modes" above) -- it's for one-time rig
calibration (re-anchoring art that wasn't drawn exactly on its bone), not
for posing, and dragging there WILL visually separate a part from its
parent by design, matching exactly the reported symptom. If a real
detachment shows up while the mode toggle is on "Animation", that would
be a genuine new bug worth its own repro -- but check which mode was
active first before assuming one, since this is the one case in the tool
where a part intentionally moving away from its parent is correct,
expected behavior, not something to fix.

### Animation mode's root part now rotates in place instead of free-translating

Requested: "position fix rakho bones ki, full body move nahi hogi kahi par
bhi... matlab mai walk karwau toh mujhe bas haath per hilane h only and
walk ho jayega" -- build a walk cycle (or any animation) by only rotating
limbs, with the character's on-stage position never drifting. Previously
the ROOT part (no real parent) was the one exception to "Animation" mode's
rotate-only rule -- it free-translated, "so the whole character can be
placed" -- so an accidental drag on the root during posing would shift the
ENTIRE rig off its base stage position, which is exactly the kind of drift
that makes building a keyframe sequence fiddly.

Fixed: `_onPointerDown`'s mode selection is now simply
`this.editMode === "move" ? "translate" : "rotate"` -- EVERY part rotates
around its own real pivot in Animation mode, including the root. A root
has no real joint (nothing above it to preserve), but it still has its own
real pivot, so dragging it now spins the WHOLE character in place around
that fixed point instead of sliding it anywhere -- verified directly:
computed the root's pivot world position before and after a large drag
(34° rotation) and it's bit-for-bit identical, while a screenshot
comparison shows the whole rig rotating in place around a fixed point, no
drift. Deliberate whole-character repositioning is still possible, but
only in "Move Parts" mode (still a true free drag for every part,
including root) -- updated both the on-screen drag hint and the mode's
own tooltip text to describe this instead of the old "drag root to move
the character" guidance, which is no longer true in Animation mode.

**Follow-up: rotating the root in place still LOOKS like the character
moved, so it's now not draggable at all.** Reported straight back with a
screenshot: "move kyu ho raha hai ye?" -- the fix above kept the root's
PIVOT world position provably fixed, but rotating the whole character by
even a moderate angle (e.g. 34°) still visibly swings the ENTIRE body
across the stage into a completely different-looking silhouette (in the
screenshot: the character now diagonal, half off the visible stage area)
-- which reads as "it moved" to the user even though, technically, only
its orientation changed around a fixed point. That's not what "position
fix rakho" meant. Fixed harder: in Animation mode, a pointerdown on the
root now does nothing at all beyond selecting it (`_onPointerDown`
returns immediately after `if (this.editMode !== "move" && !part.parent)
return;`, before `pushHistory()` and before any dragState is created) --
verified directly: dispatching a real drag on the root now leaves its
pose matrix byte-for-byte identical and pushes no undo entry. The root's
transform is only ever touched in "Move Parts" mode now (deliberate
whole-character repositioning/calibration); in Animation mode the base is
100% locked and posing is exclusively the limbs articulating around it,
matching "bones data fixed rakhdo" literally rather than just
approximately (fixed pivot, but still visibly swinging).

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
