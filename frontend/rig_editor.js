// ---- matrix helpers (2D affine [a,b,c,d,tx,ty], same convention as backend) ----
function matCompose(p, c) {
  const [pa, pb, pc_, pd, ptx, pty] = p;
  const [ca, cb, cc, cd, ctx, cty] = c;
  return [
    pa * ca + pc_ * cb, pb * ca + pd * cb,
    pa * cc + pc_ * cd, pb * cc + pd * cd,
    pa * ctx + pc_ * cty + ptx, pb * ctx + pd * cty + pty,
  ];
}
function matInverse(m) {
  const [a, b, c, d, tx, ty] = m;
  const det = a * d - b * c;
  if (Math.abs(det) < 1e-12) return [1, 0, 0, 1, 0, 0];
  const ia = d / det, ib = -b / det, ic = -c / det, id_ = a / det;
  return [ia, ib, ic, id_, (c * ty - d * tx) / det, (b * tx - a * ty) / det];
}
function matDecomposeRotation(m) {
  const [a, b] = m;
  return Math.atan2(b, a) * 180 / Math.PI;
}
function matWithRotation(m, angleDeg) {
  const [a, b, c, d] = m;
  const scaleX = Math.hypot(a, b) || 1;
  const scaleY = Math.hypot(c, d) || 1;
  // preserve whether the local frame is mirrored (negative determinant)
  const mirrored = (a * d - b * c) < 0 ? -1 : 1;
  const rad = angleDeg * Math.PI / 180;
  const na = scaleX * Math.cos(rad), nb = scaleX * Math.sin(rad);
  const nc = -mirrored * scaleY * Math.sin(rad), nd = mirrored * scaleY * Math.cos(rad);
  return [na, nb, nc, nd, m[4], m[5]];
}
function matToStr(m) { return `matrix(${m[0]},${m[1]},${m[2]},${m[3]},${m[4]},${m[5]})`; }

// ---- app state ----
let rig = null;          // {flaId, symbol, fps, parts:[{name,parent,lib,matrix,pivot,image,half_extent}]}
let pose = {};           // partName -> current local matrix (live edit buffer)
let keyframes = [];      // [{frame, poses:{partName:[a,b,c,d,tx,ty]}}]
let selectedPart = null;
let dragState = null;
let playTimer = null;

let targetRig = null;
let targetPose = {};
let retargetKeyframes = null;
let retargetPlayTimer = null;

// ---------- upload (main) ----------
const rigFile = document.getElementById("rigFile");
const rigUploadBtn = document.getElementById("rigUploadBtn");
const uploadStatus = document.getElementById("uploadStatus");
const uploadErr = document.getElementById("uploadErr");
const symbolPickWrap = document.getElementById("symbolPickWrap");
const symbolPick = document.getElementById("symbolPick");
const loadRigBtn = document.getElementById("loadRigBtn");
const rigErr = document.getElementById("rigErr");
const editorCard = document.getElementById("editorCard");

let uploadedFlaId = null;

async function uploadFla(file, statusEl, errEl) {
  const form = new FormData();
  form.append("fla", file);
  const resp = await fetch("/api/fla/upload", { method: "POST", body: form });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.detail || "Upload fail ho gaya.");
  return data;
}

rigUploadBtn.addEventListener("click", async () => {
  const file = rigFile.files[0];
  uploadErr.textContent = "";
  if (!file) { uploadErr.textContent = "File select karo pehle."; return; }
  rigUploadBtn.disabled = true;
  uploadStatus.textContent = "Upload ho raha hai...";
  try {
    const data = await uploadFla(file);
    uploadedFlaId = data.fla_id;
    uploadStatus.textContent = `Scan ho gaya (${data.animations.length} real animations mile).`;
    const chars = data.animations.filter(a => a.role === "character");
    symbolPick.innerHTML = chars.map(a => `<option value="${encodeURIComponent(a.symbol)}">${a.display_name} (${a.keyframes}kf, ${a.layers} layers${a.has_ik_bones ? ", bone data" : ""})</option>`).join("");
    symbolPickWrap.style.display = "block";
  } catch (e) {
    uploadErr.textContent = e.message;
  } finally {
    rigUploadBtn.disabled = false;
  }
});

loadRigBtn.addEventListener("click", async () => {
  rigErr.textContent = "";
  loadRigBtn.disabled = true;
  try {
    const symbol = decodeURIComponent(symbolPick.value);
    const resp = await fetch(`/api/fla/${uploadedFlaId}/rig?symbol=${encodeURIComponent(symbol)}`);
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "Rig load nahi hua.");
    rig = { flaId: uploadedFlaId, symbol, fps: data.fps, parts: data.parts };
    pose = {};
    rig.parts.forEach(p => { pose[p.name] = p.matrix.slice(); });
    selectedPart = null;
    keyframes = [];
    editorCard.style.display = "block";
    renderStage();
    renderPartList();
    renderKfList();
  } catch (e) {
    rigErr.textContent = e.message;
  } finally {
    loadRigBtn.disabled = false;
  }
});

// ---------- SVG stage rendering (main editor) ----------
const stageSvg = document.getElementById("stageSvg");

// NOTE: the "first-in-list = front-most" rule only applies to <DOMLayer>
// siblings (xfl2svg reverses those -- svg_renderer.py's own
// `reversed(list(enumerate(layers)))`). Elements WITHIN one layer's
// <elements> block are walked in plain document order with no reversal
// (svg_renderer.py: `for element_idx, element in enumerate(frame[...])`),
// same as native SVG (later in the document = on top). Since a real
// multi-part armature layer holds all its parts in one <elements> block,
// sibling parts here must keep their real file order, not be reversed.
function childrenOf(parts, name) {
  return parts.filter(p => p.parent === name).map(p => p.name);
}
function rootsOf(parts) {
  const names = new Set(parts.map(p => p.name));
  return parts.filter(p => !p.parent || !names.has(p.parent)).map(p => p.name);
}

function buildPartSvg(svgEl, parts, poseMap, name, opts) {
  const part = parts.find(p => p.name === name);
  if (!part) return "";
  const m = poseMap[name] || part.matrix;
  const he = part.half_extent || 900;
  const kids = childrenOf(parts, name).map(cn => buildPartSvg(svgEl, parts, poseMap, cn, opts)).join("");
  const selAttr = opts.selectable ? ` data-part="${name}" style="cursor:grab"` : "";
  // Selection marker is a small FIXED-size box at the part's own origin, not
  // the full half_extent cutout canvas -- that canvas is mostly transparent
  // padding sized the same for every part regardless of its real drawn size,
  // so outlining it made small/deeply-nested parts (e.g. a finger several
  // levels deep) show a huge, misleadingly rotated box once ancestor
  // rotations composed into it.
  const markAttr = opts.selectable ? ` data-outline-for="${name}"` : "";
  return `<g transform="${matToStr(m)}"><g${selAttr}>
    <image href="${part.image}" x="${-he}" y="${-he}" width="${he * 2}" height="${he * 2}" />
    <rect class="part-outline"${markAttr} x="-40" y="-40" width="80" height="80" />
  </g>${kids}</g>`;
}

function renderStage() {
  if (!rig) return;
  const roots = rootsOf(rig.parts);
  stageSvg.innerHTML = roots.map(r => buildPartSvg(stageSvg, rig.parts, pose, r, { selectable: true })).join("");
  wireDrag();
  highlightSelected();
}

function wireDrag() {
  stageSvg.querySelectorAll("[data-part]").forEach(g => {
    g.addEventListener("pointerdown", onPartPointerDown);
  });
}

function svgPoint(evt) {
  const pt = stageSvg.createSVGPoint();
  pt.x = evt.clientX; pt.y = evt.clientY;
  const ctm = stageSvg.getScreenCTM().inverse();
  return pt.matrixTransform(ctm);
}

// world (root-space) position of a part = compose of all ancestor matrices
function worldMatrix(name) {
  const part = rig.parts.find(p => p.name === name);
  if (!part) return [1, 0, 0, 1, 0, 0];
  const m = pose[name] || part.matrix;
  if (!part.parent) return m;
  return matCompose(worldMatrix(part.parent), m);
}

function onPartPointerDown(evt) {
  evt.stopPropagation();
  const name = evt.currentTarget.getAttribute("data-part");
  selectPart(name);
  const part = rig.parts.find(p => p.name === name);
  const parentWorld = part.parent ? worldMatrix(part.parent) : [1, 0, 0, 1, 0, 0];
  const parentInv = matInverse(parentWorld);
  const start = svgPoint(evt);
  const startLocal = pose[name].slice();
  dragState = { name, parentInv, start, startLocal };
  evt.currentTarget.setPointerCapture(evt.pointerId);
  evt.currentTarget.addEventListener("pointermove", onPartPointerMove);
  evt.currentTarget.addEventListener("pointerup", onPartPointerUp);
}
function onPartPointerMove(evt) {
  if (!dragState) return;
  const cur = svgPoint(evt);
  // delta in the part's PARENT local space (so drag distance feels right
  // regardless of how the parent chain is itself scaled/rotated)
  const d0 = applyMatToPoint(dragState.parentInv, dragState.start);
  const d1 = applyMatToPoint(dragState.parentInv, cur);
  const dx = d1.x - d0.x, dy = d1.y - d0.y;
  const m = dragState.startLocal.slice();
  m[4] += dx; m[5] += dy;
  pose[dragState.name] = m;
  renderStage();
}
function onPartPointerUp(evt) {
  dragState = null;
  evt.currentTarget.removeEventListener("pointermove", onPartPointerMove);
  evt.currentTarget.removeEventListener("pointerup", onPartPointerUp);
}
function applyMatToPoint(m, pt) {
  return { x: m[0] * pt.x + m[2] * pt.y + m[4], y: m[1] * pt.x + m[3] * pt.y + m[5] };
}

function highlightSelected() {
  stageSvg.querySelectorAll("[data-outline-for]").forEach(r => {
    r.style.opacity = r.getAttribute("data-outline-for") === selectedPart ? "1" : "0";
  });
}

// ---------- part list + selection panel ----------
const partList = document.getElementById("partList");
const selectedPanel = document.getElementById("selectedPanel");
const selName = document.getElementById("selName");
const parentPick = document.getElementById("parentPick");
const rotSlider = document.getElementById("rotSlider");
const resetPoseBtn = document.getElementById("resetPoseBtn");

function renderPartList() {
  partList.innerHTML = rig.parts.map(p =>
    `<li data-name="${p.name}" class="${p.name === selectedPart ? "selected" : ""}">
      <span class="pname">${p.name}</span>
      <span class="pparent">${p.parent ? "↳ " + p.parent : "(root)"}</span>
    </li>`).join("");
  partList.querySelectorAll("li").forEach(li => {
    li.addEventListener("click", () => selectPart(li.getAttribute("data-name")));
  });
}

function selectPart(name) {
  selectedPart = name;
  highlightSelected();
  renderPartList();
  const part = rig.parts.find(p => p.name === name);
  if (!part) { selectedPanel.style.display = "none"; return; }
  selectedPanel.style.display = "block";
  selName.textContent = name;
  const others = rig.parts.filter(p => p.name !== name).map(p => p.name);
  parentPick.innerHTML = `<option value="">(root -- koi parent nahi)</option>` +
    others.map(n => `<option value="${n}" ${part.parent === n ? "selected" : ""}>${n}</option>`).join("");
  rotSlider.value = Math.round(matDecomposeRotation(pose[name]));
}

parentPick.addEventListener("change", () => {
  if (!selectedPart) return;
  const part = rig.parts.find(p => p.name === selectedPart);
  const newParent = parentPick.value || null;
  // re-express current pose in the NEW parent's local space so the part
  // doesn't visually jump when you reassign it
  const curWorld = worldMatrix(selectedPart);
  part.parent = newParent;
  const parentWorld = newParent ? worldMatrix(newParent) : [1, 0, 0, 1, 0, 0];
  pose[selectedPart] = matCompose(matInverse(parentWorld), curWorld);
  renderStage();
  renderPartList();
});

rotSlider.addEventListener("input", () => {
  if (!selectedPart) return;
  pose[selectedPart] = matWithRotation(pose[selectedPart], parseFloat(rotSlider.value));
  renderStage();
});

resetPoseBtn.addEventListener("click", () => {
  if (!selectedPart) return;
  const part = rig.parts.find(p => p.name === selectedPart);
  pose[selectedPart] = part.matrix.slice();
  renderStage();
  rotSlider.value = Math.round(matDecomposeRotation(pose[selectedPart]));
});

// ---------- timeline / keyframes ----------
const frameNum = document.getElementById("frameNum");
const recordBtn = document.getElementById("recordBtn");
const kfList = document.getElementById("kfList");
const playBtn = document.getElementById("playBtn");
const stopBtn = document.getElementById("stopBtn");
const exportBtn = document.getElementById("exportBtn");

recordBtn.addEventListener("click", () => {
  const frame = parseInt(frameNum.value, 10) || 0;
  const poses = {};
  rig.parts.forEach(p => { poses[p.name] = (pose[p.name] || p.matrix).slice(); });
  const existing = keyframes.find(k => k.frame === frame);
  if (existing) existing.poses = poses;
  else keyframes.push({ frame, poses });
  keyframes.sort((a, b) => a.frame - b.frame);
  renderKfList();
});

function renderKfList() {
  kfList.innerHTML = keyframes.map(k =>
    `<span class="kf-chip ${k.frame === parseInt(frameNum.value) ? "active" : ""}" data-frame="${k.frame}">#${k.frame}</span>`).join("");
  kfList.querySelectorAll(".kf-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      const f = parseInt(chip.getAttribute("data-frame"), 10);
      frameNum.value = f;
      const kf = keyframes.find(k => k.frame === f);
      if (kf) {
        pose = {};
        rig.parts.forEach(p => { pose[p.name] = (kf.poses[p.name] || p.matrix).slice(); });
        renderStage();
        if (selectedPart) rotSlider.value = Math.round(matDecomposeRotation(pose[selectedPart]));
      }
      renderKfList();
    });
  });
}

function interpPose(parts, kfs, frame) {
  if (kfs.length === 0) return null;
  if (frame <= kfs[0].frame) return kfs[0].poses;
  if (frame >= kfs[kfs.length - 1].frame) return kfs[kfs.length - 1].poses;
  let i = 0;
  while (i < kfs.length - 1 && kfs[i + 1].frame < frame) i++;
  const a = kfs[i], b = kfs[i + 1];
  const t = (frame - a.frame) / (b.frame - a.frame || 1);
  const out = {};
  parts.forEach(p => {
    const ma = a.poses[p.name], mb = b.poses[p.name];
    if (!ma || !mb) { out[p.name] = ma || mb || p.matrix; return; }
    out[p.name] = ma.map((v, idx) => v + (mb[idx] - v) * t);
  });
  return out;
}

playBtn.addEventListener("click", () => {
  if (keyframes.length < 2) { alert("Kam se kam 2 keyframes record karo pehle."); return; }
  playBtn.style.display = "none";
  stopBtn.style.display = "inline-block";
  const first = keyframes[0].frame, last = keyframes[keyframes.length - 1].frame;
  let f = first;
  const fps = rig.fps || 24;
  playTimer = setInterval(() => {
    const p = interpPose(rig.parts, keyframes, f);
    if (p) { pose = p; renderStage(); }
    f += 1;
    if (f > last) f = first;
  }, 1000 / fps);
});
stopBtn.addEventListener("click", () => {
  clearInterval(playTimer);
  playBtn.style.display = "inline-block";
  stopBtn.style.display = "none";
});

exportBtn.addEventListener("click", () => {
  if (keyframes.length === 0) { alert("Pehle kam se kam ek keyframe record karo."); return; }
  const data = {
    source: { flaId: rig.flaId, symbol: rig.symbol },
    fps: rig.fps,
    parts: rig.parts.map(p => ({ name: p.name, parent: p.parent, base_matrix: p.matrix })),
    keyframes,
  };
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${rig.symbol.replace(/[^A-Za-z0-9_-]/g, "_")}_animation.json`;
  a.click();
});

// ---------- tabs ----------
const tabPose = document.getElementById("tabPose");
const tabRetarget = document.getElementById("tabRetarget");
const poseTab = document.getElementById("poseTab");
const retargetTab = document.getElementById("retargetTab");
tabPose.addEventListener("click", () => {
  tabPose.classList.remove("inactive"); tabRetarget.classList.add("inactive");
  poseTab.style.display = "block"; retargetTab.style.display = "none";
});
tabRetarget.addEventListener("click", () => {
  tabRetarget.classList.remove("inactive"); tabPose.classList.add("inactive");
  poseTab.style.display = "none"; retargetTab.style.display = "block";
});

// ---------- retarget tab ----------
const animJsonFile = document.getElementById("animJsonFile");
const targetFile = document.getElementById("targetFile");
const targetUploadBtn = document.getElementById("targetUploadBtn");
const targetSymbolPickWrap = document.getElementById("targetSymbolPickWrap");
const targetSymbolPick = document.getElementById("targetSymbolPick");
const loadTargetRigBtn = document.getElementById("loadTargetRigBtn");
const targetErr = document.getElementById("targetErr");
const retargetStageCard = document.getElementById("retargetStageCard");
const retargetSvg = document.getElementById("retargetSvg");
const missingPartsEl = document.getElementById("missingParts");
const retargetPlayBtn = document.getElementById("retargetPlayBtn");
const retargetStopBtn = document.getElementById("retargetStopBtn");

let uploadedTargetFlaId = null;

targetUploadBtn.addEventListener("click", async () => {
  const file = targetFile.files[0];
  targetErr.textContent = "";
  if (!file) { targetErr.textContent = "File select karo pehle."; return; }
  targetUploadBtn.disabled = true;
  try {
    const data = await uploadFla(file);
    uploadedTargetFlaId = data.fla_id;
    const chars = data.animations.filter(a => a.role === "character");
    targetSymbolPick.innerHTML = chars.map(a => `<option value="${encodeURIComponent(a.symbol)}">${a.display_name}</option>`).join("");
    targetSymbolPickWrap.style.display = "block";
  } catch (e) {
    targetErr.textContent = e.message;
  } finally {
    targetUploadBtn.disabled = false;
  }
});

loadTargetRigBtn.addEventListener("click", async () => {
  targetErr.textContent = "";
  loadTargetRigBtn.disabled = true;
  try {
    const symbol = decodeURIComponent(targetSymbolPick.value);
    const resp = await fetch(`/api/fla/${uploadedTargetFlaId}/rig?symbol=${encodeURIComponent(symbol)}`);
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "Rig load nahi hua.");
    targetRig = { flaId: uploadedTargetFlaId, symbol, fps: data.fps, parts: data.parts };
    targetPose = {};
    targetRig.parts.forEach(p => { targetPose[p.name] = p.matrix.slice(); });

    let sourceKfs = keyframes;
    let sourceParts = rig ? rig.parts : null;
    if (animJsonFile.files[0]) {
      const text = await animJsonFile.files[0].text();
      const loaded = JSON.parse(text);
      sourceKfs = loaded.keyframes;
      sourceParts = loaded.parts.map(p => ({ name: p.name, parent: p.parent, matrix: p.base_matrix }));
    }
    if (!sourceKfs || sourceKfs.length === 0) {
      throw new Error("Koi animation JSON nahi mila -- pehle Pose tab mein record karo ya JSON upload karo.");
    }
    retargetKeyframes = sourceKfs;

    const sourceNames = new Set(sourceParts.map(p => p.name));
    const targetNames = new Set(targetRig.parts.map(p => p.name));
    const missing = [...sourceNames].filter(n => !targetNames.has(n));
    missingPartsEl.textContent = missing.length
      ? `⚠ Ye parts naye character mein nahi mile (naam match nahi hua), skip ho jayenge: ${missing.join(", ")}`
      : "Saare parts match ho gaye ✓";

    retargetStageCard.style.display = "block";
    const first = sourceKfs[0].poses;
    targetRig.parts.forEach(p => { if (first[p.name]) targetPose[p.name] = first[p.name].slice(); });
    renderRetargetStage();
  } catch (e) {
    targetErr.textContent = e.message;
  } finally {
    loadTargetRigBtn.disabled = false;
  }
});

function renderRetargetStage() {
  if (!targetRig) return;
  const roots = rootsOf(targetRig.parts);
  retargetSvg.innerHTML = roots.map(r => buildPartSvg(retargetSvg, targetRig.parts, targetPose, r, { selectable: false })).join("");
}

retargetPlayBtn.addEventListener("click", () => {
  if (!retargetKeyframes || retargetKeyframes.length < 2) { alert("Animation mein kam se kam 2 keyframes chahiye."); return; }
  retargetPlayBtn.style.display = "none";
  retargetStopBtn.style.display = "inline-block";
  const first = retargetKeyframes[0].frame, last = retargetKeyframes[retargetKeyframes.length - 1].frame;
  let f = first;
  const fps = targetRig.fps || 24;
  retargetPlayTimer = setInterval(() => {
    const p = interpPose(targetRig.parts, retargetKeyframes, f);
    if (p) {
      targetRig.parts.forEach(part => { if (p[part.name]) targetPose[part.name] = p[part.name]; });
      renderRetargetStage();
    }
    f += 1;
    if (f > last) f = first;
  }, 1000 / fps);
});
retargetStopBtn.addEventListener("click", () => {
  clearInterval(retargetPlayTimer);
  retargetPlayBtn.style.display = "inline-block";
  retargetStopBtn.style.display = "none";
});
