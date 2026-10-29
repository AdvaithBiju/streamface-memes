const statusEl = document.getElementById("status");
const facesEl = document.getElementById("faces");
const emptyEl = document.getElementById("empty");
const video = document.getElementById("video");
const canvas = document.getElementById("canvas");
const camStart = document.getElementById("cam-start");
const camSnap = document.getElementById("cam-snap");
const camStop = document.getElementById("cam-stop");
let stream = null;

function setStatus(msg, kind = "") {
  statusEl.textContent = msg;
  statusEl.className = "status " + kind;
}

async function loadFaces() {
  const res = await fetch("/api/faces");
  const faces = await res.json();
  facesEl.innerHTML = "";
  emptyEl.hidden = faces.length > 0;
  for (const f of faces) {
    const card = document.createElement("figure");
    card.className = "face";
    card.innerHTML = `
      <div class="checker"><img alt="Face cutout ${f.id}"></div>
      <figcaption>#${f.id} · ${f.source}</figcaption>
      <button type="button" class="ghost danger">Delete</button>`;
    card.querySelector("img").src = f.url;
    card.querySelector("button").onclick = () => deleteFace(f.id);
    facesEl.appendChild(card);
  }
}

async function sendPhotos(formData) {
  setStatus("Detecting face…");
  const res = await fetch("/api/faces", { method: "POST", body: formData });
  const body = await res.json().catch(() => ({}));
  if (!res.ok && !body.created) {
    setStatus(body.error || (body.errors || []).join(" ") || "Upload failed.", "error");
    return;
  }
  const errs = body.errors || [];
  setStatus(
    `Saved ${body.created.length} cutout(s).` + (errs.length ? " " + errs.join(" ") : ""),
    errs.length ? "warn" : "ok"
  );
  await loadFaces();
}

document.getElementById("upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = document.getElementById("file-input");
  if (!input.files.length) return setStatus("Pick a photo first.", "error");
  const fd = new FormData();
  for (const f of input.files) fd.append("photos", f);
  fd.append("source", "upload");
  await sendPhotos(fd);
  input.value = "";
});

async function deleteFace(id) {
  await fetch(`/api/faces/${id}`, { method: "DELETE" });
  setStatus(`Deleted face #${id}.`);
  await loadFaces();
}

camStart.onclick = async () => {
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: { width: 1280, height: 720 } });
  } catch (err) {
    return setStatus("Couldn't open the camera: " + err.message, "error");
  }
  video.srcObject = stream;
  video.hidden = false;
  camSnap.disabled = false;
  camStop.disabled = false;
  camStart.disabled = true;
};

function stopCamera() {
  if (stream) stream.getTracks().forEach((t) => t.stop());
  stream = null;
  video.hidden = true;
  camSnap.disabled = true;
  camStop.disabled = true;
  camStart.disabled = false;
}
camStop.onclick = stopCamera;

camSnap.onclick = () => {
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  canvas.getContext("2d").drawImage(video, 0, 0);
  canvas.toBlob(async (blob) => {
    const fd = new FormData();
    fd.append("photos", blob, "webcam.png");
    fd.append("source", "webcam");
    await sendPhotos(fd);
  }, "image/png");
};

loadFaces();
