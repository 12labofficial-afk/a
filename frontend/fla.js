const flaFileInput = document.getElementById("flaFile");
const uploadBtn = document.getElementById("uploadBtn");
const uploadStatus = document.getElementById("uploadStatus");
const uploadErr = document.getElementById("uploadErr");
const resultsCard = document.getElementById("resultsCard");
const summaryEl = document.getElementById("summary");
const animGrid = document.getElementById("animGrid");

let currentFlaId = null;

uploadBtn.addEventListener("click", async () => {
  const file = flaFileInput.files[0];
  uploadErr.textContent = "";
  if (!file) {
    uploadErr.textContent = ".fla file select karo pehle.";
    return;
  }

  uploadBtn.disabled = true;
  uploadStatus.textContent = "Upload ho rahi hai aur library scan ho rahi hai — isme thoda time lag sakta hai...";
  resultsCard.style.display = "none";

  const form = new FormData();
  form.append("fla", file);

  try {
    const resp = await fetch("/api/fla/upload", { method: "POST", body: form });
    if (!resp.ok) {
      const detail = await resp.json().catch(() => ({}));
      throw new Error(detail.detail || `Error ${resp.status}`);
    }
    const data = await resp.json();
    currentFlaId = data.fla_id;
    uploadStatus.textContent = `"${data.filename}" scan ho gayi.`;
    renderAnimations(data.animations);
  } catch (e) {
    uploadStatus.textContent = "";
    uploadErr.textContent = e.message;
  } finally {
    uploadBtn.disabled = false;
  }
});

function renderAnimations(animations) {
  animGrid.innerHTML = "";
  if (!animations.length) {
    summaryEl.textContent = "Is file me koi multi-keyframe (real) animation nahi mili — sab symbols static single-pose lag rahe hain.";
    resultsCard.style.display = "block";
    return;
  }

  summaryEl.textContent = `${animations.length} animated symbol mile (sabse zyada motion wale pehle):`;

  animations.forEach((a) => {
    const card = document.createElement("div");
    card.className = "anim-card";
    card.innerHTML = `
      <div class="anim-stage" id="stage-${cssSafe(a.symbol)}">
        <button class="play-btn" data-symbol="${escapeAttr(a.symbol)}">▶ Play</button>
      </div>
      <div class="anim-name">${escapeHtml(a.display_name)}</div>
      <div class="anim-meta">${escapeHtml(a.symbol)}</div>
      <div class="anim-meta">${a.keyframes} keyframes · ${a.duration} frames · ${a.layers} layers</div>
    `;
    card.querySelector(".play-btn").addEventListener("click", (e) => loadPreview(a.symbol, e.target));
    animGrid.appendChild(card);
  });

  resultsCard.style.display = "block";
}

async function loadPreview(symbol, btnEl) {
  const stage = document.getElementById(`stage-${cssSafe(symbol)}`);
  stage.innerHTML = `<div class="spinner"></div>`;
  try {
    const url = `/api/fla/${currentFlaId}/preview?symbol=${encodeURIComponent(symbol)}`;
    const resp = await fetch(url);
    if (!resp.ok) {
      const detail = await resp.json().catch(() => ({}));
      throw new Error(detail.detail || `Error ${resp.status}`);
    }
    const blob = await resp.blob();
    const objUrl = URL.createObjectURL(blob);
    stage.innerHTML = `<video src="${objUrl}" autoplay loop muted controls></video>`;
  } catch (e) {
    stage.innerHTML = `<div class="anim-error">${escapeHtml(e.message)}</div>`;
  }
}

function cssSafe(s) {
  return s.replace(/[^A-Za-z0-9_-]/g, "_");
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function escapeAttr(s) {
  return escapeHtml(s);
}
