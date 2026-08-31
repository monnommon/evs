// EVS Alpine.js components — loaded from base.html.
// No npm build step: plain ES5-ish JS, globals registered on alpine:init.

// Lightweight async SHA-256 hex digest via SubtleCrypto (fallback: simple hash).
async function evsSha256Hex(text) {
  if (window.crypto && crypto.subtle && crypto.subtle.digest) {
    try {
      const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
      return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, "0")).join("");
    } catch (e) { /* fall through */ }
  }
  // Fallback (non-crypto contexts): FNV-1a — still unique per session, hex-only.
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = (h + (h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24)) >>> 0;
  }
  return ("fnv-" + h.toString(16)).padStart(11, "0");
}

// Compute a coarse browser fingerprint (canvas + UA + screen + tz + language).
async function evsFingerprint() {
  const parts = [navigator.userAgent, navigator.language, screen.width + "x" + screen.height,
                 screen.colorDepth, Intl.DateTimeFormat().resolvedOptions().timeZone || ""];
  try {
    const c = document.createElement("canvas");
    c.width = 200; c.height = 40;
    const ctx = c.getContext("2d");
    ctx.textBaseline = "top";
    ctx.font = "16px 'Arial'";
    ctx.fillStyle = "#f60";
    ctx.fillRect(10, 5, 80, 20);
    ctx.fillStyle = "#069";
    ctx.fillText("EVS-fp:\u263B", 12, 10);
    parts.push(c.toDataURL());
  } catch (e) { /* canvas blocked — other signals still differ */ }
  return evsSha256Hex(parts.join("~"));
}

document.addEventListener("alpine:init", () => {
  window.EVS = window.EVS || {};

  // Ballot component: fingerprint + countdown + selection state.
  Alpine.data("evsVote", (opts) => ({
    fingerprint: "",
    fingerprintReady: false,
    countdown: opts && opts.endAtIso ? opts.endAtIso : "",
    multiple: !!(opts && opts.multiple),
    selected: [],
    async init() {
      try {
        this.fingerprint = await evsFingerprint();
      } catch (e) {
        this.fingerprint = "fp-error";
      }
      this.fingerprintReady = true;
      if (opts && opts.endAtIso) this.tick();
    },
    tick() {
      const end = new Date(opts.endAtIso).getTime();
      const update = () => {
        const ms = end - Date.now();
        if (ms <= 0) { this.countdown = "closed"; clearInterval(timer); return; }
        const h = Math.floor(ms / 3600000), m = Math.floor((ms % 3600000) / 60000), s = Math.floor((ms % 60000) / 1000);
        this.countdown = h + "h " + m + "m " + s + "s";
      };
      const timer = setInterval(update, 1000);
      update();
    },
  }));

  // Poll form: live option preview (reactive bits for the admin panel).
  Alpine.data("evsPollForm", () => ({
    get optionList() {
      const ta = this.$root.querySelector("textarea[name='options_text']");
      return (ta ? ta.value : "").split("\n").map(s => s.trim()).filter(Boolean);
    },
  }));
});