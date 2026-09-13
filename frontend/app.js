const generateBtn = document.getElementById("generateBtn");
const statusBox = document.getElementById("status");
const barFill = document.getElementById("barFill");
const msgBox = document.getElementById("msg");
const errBox = document.getElementById("errBox");
const resultVideo = document.getElementById("resultVideo");

let pollTimer = null;

generateBtn.addEventListener("click", async () => {
  errBox.textContent = "";
  resultVideo.style.display = "none";
  resultVideo.src = "";

  const projectJson = document.getElementById("projectJson").files[0];
  const audioZip = document.getElementById("audioZip").files[0];
  const charactersZip = document.getElementById("charactersZip").files[0];

  if (!projectJson || !audioZip || !charactersZip) {
    errBox.textContent = "Teeno files (JSON, audio zip, characters zip) upload karo.";
    return;
  }

  const form = new FormData();
  form.append("project_json", projectJson);
  form.append("audio_zip", audioZip);
  form.append("characters_zip", charactersZip);
  form.append("width", document.getElementById("width").value);
  form.append("height", document.getElementById("height").value);
  form.append("fps", document.getElementById("fps").value);

  generateBtn.disabled = true;
  statusBox.style.display = "block";
  setProgress(0, "Job submit ho raha hai...");

  try {
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
