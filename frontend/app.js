const charList = document.getElementById("charList");
const addCharBtn = document.getElementById("addCharBtn");
const generateBtn = document.getElementById("generateBtn");
const statusBox = document.getElementById("status");
const barFill = document.getElementById("barFill");
const msgBox = document.getElementById("msg");
const errBox = document.getElementById("errBox");
const resultVideo = document.getElementById("resultVideo");

let characters = []; // { id, name, file }
let charIdSeq = 0;
let pollTimer = null;

function addCharacterRow(defaultName) {
  const id = ++charIdSeq;
  characters.push({ id, name: defaultName || "", file: null });
  renderCharList();
}

function removeCharacter(id) {
  characters = characters.filter((c) => c.id !== id);
  renderCharList();
}

function renderCharList() {
  charList.innerHTML = "";
  characters.forEach((c) => {
    const card = document.createElement("div");
    card.className = "char-card";
    card.innerHTML = `
      <div class="char-preview" id="preview-${c.id}">
        <div class="placeholder">Sheet PNG upload karo</div>
      </div>
      <div class="fields">
        <label>Character ka naam (JSON me jaisa likha hai)</label>
        <input type="text" placeholder="e.g. मोहन" value="${c.name || ""}" data-role="name" />
        <label style="margin-top:8px">Character Sheet PNG</label>
        <input type="file" accept=".png" data-role="file" />
        <div class="char-status" id="status-${c.id}"></div>
        <button type="button" class="danger" style="margin-top:8px" data-role="remove">Remove</button>
      </div>
    `;
    card.querySelector('[data-role="name"]').addEventListener("input", (e) => {
      c.name = e.target.value;
    });
    card.querySelector('[data-role="file"]').addEventListener("change", (e) => {
      const file = e.target.files[0];
      if (!file) return;
      c.file = file;
      previewCharacter(c);
    });
    card.querySelector('[data-role="remove"]').addEventListener("click", () => removeCharacter(c.id));
    charList.appendChild(card);
  });
}

async function previewCharacter(c) {
  const statusEl = document.getElementById(`status-${c.id}`);
  const previewEl = document.getElementById(`preview-${c.id}`);
  statusEl.textContent = "Preview ban raha hai...";
  statusEl.className = "char-status loading";

  const form = new FormData();
  form.append("sheet", c.file);
  try {
    const resp = await fetch("/api/preview-character", { method: "POST", body: form });
    if (!resp.ok) {
      const detail = await resp.json().catch(() => ({}));
      throw new Error(detail.detail || `Error ${resp.status}`);
    }
    const partCount = resp.headers.get("X-Part-Count") || "?";
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    previewEl.innerHTML = `<img src="${url}" />`;
    statusEl.textContent = `${partCount} parts pehchane gaye — rig theek lag raha hai to aage badho.`;
    statusEl.className = "char-status ok";
  } catch (e) {
    previewEl.innerHTML = `<div class="placeholder">Preview fail</div>`;
    statusEl.textContent = e.message;
    statusEl.className = "char-status bad";
  }
}

addCharBtn.addEventListener("click", () => addCharacterRow());

generateBtn.addEventListener("click", async () => {
  errBox.textContent = "";
  resultVideo.style.display = "none";
  resultVideo.src = "";

  const bundleZip = document.getElementById("bundleZip").files[0];
  const projectJson = document.getElementById("projectJson").files[0];
  const audioZip = document.getElementById("audioZip").files[0];

  if (characters.length === 0 || characters.some((c) => !c.file || !c.name.trim())) {
    errBox.textContent = "Har character ka naam aur sheet PNG dono chahiye.";
    return;
  }
  if (!bundleZip && !(projectJson && audioZip)) {
    errBox.textContent = "Ya toh Studio bundle zip do, ya Project JSON + Audio ZIP dono alag-alag.";
    return;
  }

  generateBtn.disabled = true;
  statusBox.style.display = "block";
  setProgress(0, "Characters ZIP bandh rahe hain...");

  try {
    const zip = new JSZip();
    for (const c of characters) {
      const folder = zip.folder(c.name.trim());
      const arrBuf = await c.file.arrayBuffer();
      folder.file(c.file.name, arrBuf);
    }
    const charactersZipBlob = await zip.generateAsync({ type: "blob" });

    const form = new FormData();
    if (bundleZip) {
      form.append("bundle_zip", bundleZip);
    } else {
      form.append("project_json", projectJson);
      form.append("audio_zip", audioZip);
    }
    form.append("characters_zip", charactersZipBlob, "characters.zip");
    form.append("width", document.getElementById("width").value);
    form.append("height", document.getElementById("height").value);
    form.append("fps", document.getElementById("fps").value);

    setProgress(0, "Job submit ho raha hai...");
    const resp = await fetch("/api/jobs", { method: "POST", body: form });
    if (!resp.ok) {
      const detail = await resp.json().catch(() => ({}));
      throw new Error(detail.detail || `Server error: ${resp.status}`);
    }
    const data = await resp.json();
    pollStatus(data.job_id);
  } catch (e) {
    errBox.textContent = e.message;
    generateBtn.disabled = false;
  }
});

function setProgress(pct, message) {
  barFill.style.width = pct + "%";
  barFill.textContent = pct + "%";
  msgBox.textContent = message || "";
}

function pollStatus(jobId) {
  pollTimer = setInterval(async () => {
    try {
      const resp = await fetch(`/api/jobs/${jobId}`);
      const job = await resp.json();
      setProgress(job.progress, job.message);

      if (job.state === "done") {
        clearInterval(pollTimer);
        setProgress(100, "Video taiyaar hai!");
        resultVideo.src = `/api/jobs/${jobId}/video`;
        resultVideo.style.display = "block";
        generateBtn.disabled = false;
      } else if (job.state === "error") {
        clearInterval(pollTimer);
        errBox.textContent = "Error: " + (job.error || "Kuch galat ho gaya.");
        generateBtn.disabled = false;
      }
    } catch (e) {
      clearInterval(pollTimer);
      errBox.textContent = "Status check karne me error: " + e.message;
      generateBtn.disabled = false;
    }
  }, 1500);
}

addCharacterRow();
