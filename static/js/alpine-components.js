// EVS progressive enhancements. Kept dependency-free so voting still works
// when the installation has no access to third-party CDNs.
(function () {
  "use strict";

  async function sha256Hex(text) {
    if (window.crypto && crypto.subtle && crypto.subtle.digest) {
      try {
        const buffer = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
        return Array.from(new Uint8Array(buffer), (byte) => byte.toString(16).padStart(2, "0")).join("");
      } catch (_) { /* fall through to a stable local hash */ }
    }
    let hash = 0x811c9dc5;
    for (let index = 0; index < text.length; index += 1) {
      hash ^= text.charCodeAt(index);
      hash = (hash + (hash << 1) + (hash << 4) + (hash << 7) + (hash << 8) + (hash << 24)) >>> 0;
    }
    return "fnv-" + hash.toString(16).padStart(8, "0");
  }

  async function browserFingerprint() {
    const parts = [
      navigator.userAgent,
      navigator.language,
      window.screen.width + "x" + window.screen.height,
      window.screen.colorDepth,
      Intl.DateTimeFormat().resolvedOptions().timeZone || "",
    ];
    try {
      const canvas = document.createElement("canvas");
      canvas.width = 200;
      canvas.height = 40;
      const context = canvas.getContext("2d");
      context.font = "16px Arial";
      context.fillStyle = "#235bd7";
      context.fillText("EVS ballot", 8, 22);
      parts.push(canvas.toDataURL());
    } catch (_) { /* privacy settings may block canvas */ }
    return sha256Hex(parts.join("~"));
  }

  function initBallot(root) {
    const form = root.querySelector("#ballot-form");
    const fingerprintInput = root.querySelector("#fingerprint-input");
    const submit = form.querySelector("button[type='submit']");
    const state = root.querySelector(".js-fingerprint-state");
    const selectionError = root.querySelector(".js-selection-error");
    const countdown = root.querySelector(".js-countdown");
    const endAt = new Date(root.dataset.endAt).getTime();

    const updateCountdown = function () {
      const remaining = endAt - Date.now();
      if (!Number.isFinite(remaining) || remaining <= 0) {
        countdown.textContent = root.dataset.closed;
        submit.disabled = true;
        return false;
      }
      const hours = Math.floor(remaining / 3600000);
      const minutes = Math.floor((remaining % 3600000) / 60000);
      const seconds = Math.floor((remaining % 60000) / 1000);
      countdown.textContent = hours + "h " + minutes + "m " + seconds + "s";
      return true;
    };
    updateCountdown();
    const timer = window.setInterval(function () { if (!updateCountdown()) window.clearInterval(timer); }, 1000);

    browserFingerprint().then(function (fingerprint) {
      fingerprintInput.value = fingerprint;
      submit.disabled = !updateCountdown();
      state.textContent = root.dataset.ready;
    }).catch(function () {
      state.textContent = root.dataset.failed;
    });

    form.addEventListener("submit", function (event) {
      const selected = form.querySelectorAll("input[name='option_ids']:checked");
      if (!selected.length) {
        event.preventDefault();
        selectionError.hidden = false;
        form.querySelector("input[name='option_ids']").focus();
        return;
      }
      selectionError.hidden = true;
      submit.disabled = true;
      submit.textContent = root.dataset.recording;
    });
  }

  function initCopy(button) {
    button.addEventListener("click", async function () {
      const target = document.getElementById(button.dataset.copyTarget);
      const status = button.closest(".card").querySelector(".copy-status");
      try {
        await navigator.clipboard.writeText(target.textContent.trim());
        status.textContent = button.dataset.copied;
      } catch (_) {
        const range = document.createRange();
        range.selectNodeContents(target);
        window.getSelection().removeAllRanges();
        window.getSelection().addRange(range);
        status.textContent = button.dataset.selected;
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".js-vote").forEach(initBallot);
    document.querySelectorAll(".js-copy").forEach(initCopy);
    document.querySelectorAll("[data-confirm]").forEach(function (button) {
      button.addEventListener("click", function (event) {
        if (!window.confirm(button.dataset.confirm)) event.preventDefault();
      });
    });
    document.querySelectorAll(".js-poll-form").forEach(function (form) {
      const textarea = form.querySelector("textarea[name='options_text']");
      const output = form.querySelector(".js-option-count");
      const update = function () {
        const count = textarea.value.split("\n").filter((line) => line.trim()).length;
        output.textContent = output.dataset.label + " " + count;
      };
      textarea.addEventListener("input", update);
      update();
    });
  });
}());
