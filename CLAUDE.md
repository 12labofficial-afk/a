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
  detection, preview rendering, and lip-sync generation.
- `backend/app/main.py` -- FastAPI endpoints: `/api/fla/upload`,
  `/api/fla/{fla_id}/animations`, `/api/fla/{fla_id}/preview`,
  `POST /api/fla/{fla_id}/lipsync`.
- `backend/app/audio_utils.py` -- `DialogueAudio` (RMS amplitude envelope
  from an uploaded audio file), reused by the lip-sync feature.
- Deployed HF Space: `yashsharma463/Otsm` (flat file layout, no
  subfolders, since HF's browser upload doesn't preserve folder structure).

## xfl2svg layer-order convention

In a `<DOMTimeline><layers>` list, the layer listed FIRST renders FRONT-most
(on top); the layer listed LAST renders BACK-most. (`svg_renderer.py`
processes `reversed(list(enumerate(layers)))`, i.e. back-to-front, so the
first-listed layer is drawn last = on top.) Never reorder layers when
generating a composite symbol -- always preserve the original file's own
`<layers>` order exactly.

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
