// Address of the StreamFace server (the Render deploy). Update it if your Render URL differs.
// When the site is opened from localhost, it talks to the app running on your PC instead.
window.STREAMFACE_API = ["localhost", "127.0.0.1"].includes(location.hostname)
  ? "http://localhost:5000"
  : "https://streamface-memes.onrender.com";
