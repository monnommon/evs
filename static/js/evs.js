// EVS progressive enhancements. Kept dependency-free so voting still works
// when the installation has no access to third-party CDNs.
(function () {
  "use strict";

  async function sha256Hex(text) {
    if (window.crypto && crypto.subtle && crypto.subtle.digest) {
      const buffer = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
      return Array.from(new Uint8Array(buffer), (byte) => byte.toString(16).padStart(2, "0")).join("");
    }
    // No crypto.subtle (e.g. plain HTTP): no fingerprint.
    // The one-time link is the dedupe guarantee; the server accepts a
    // fingerprint-less vote (null) from a fresh link.
    return null;
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
      // No crypto.subtle → fingerprint is null: send an empty field; the
      // one-time link alone guarantees the vote is unique.
      fingerprintInput.value = fingerprint || "";
      submit.disabled = !updateCountdown();
      state.textContent = fingerprint ? root.dataset.ready : root.dataset.readyNoFp;
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

    // Ballot builder: additional fields (text/textarea/date/info).
    document.querySelectorAll(".js-questions").forEach(function (root) {
      const jsonField = root.querySelector(".js-questions-json");
      const list = root.querySelector(".js-questions-list");
      const typeSelect = root.querySelector(".js-qtype");
      const addBtn = root.querySelector(".js-add-question");
      const errBox = root.querySelector(".js-questions-error");
      let questions = [];
      try { questions = JSON.parse(jsonField.value || "[]"); } catch (_) { questions = []; }

      const typeLabels = { text: "text", textarea: "multi-line text", date: "date", info: "info" };

      const sync = function () { jsonField.value = JSON.stringify(questions); };

      const renderRow = function (q, index) {
        const row = document.createElement("div");
        row.className = "js-question-row choice-group";
        row.style.marginBottom = ".4rem";
        const isInfo = q.type === "info";
        row.innerHTML =
          '<span class="badge">' + typeLabels[q.type] + "</span>" +
          '<input type="text" class="js-q-label" placeholder="' + (isInfo ? root.dataset.labelHint || "Label (optional)" : "Label") + '" value="' + (q.label || "").replace(/"/g, "&quot;") + '" ' + (isInfo ? "" : "required") + ">" +
          (isInfo ? '<input type="text" class="js-q-value" placeholder="Info text" value="' + (q.value || "").replace(/"/g, "&quot;") + '">' : '<input type="text" class="js-q-help" placeholder="Hint (optional)" value="' + (q.help || "").replace(/"/g, "&quot;") + '">') +
          '<label class="option" style="min-height:34px"><input type="checkbox" class="js-q-required"' + (q.required ? " checked" : "") + "> required</label>" +
          '<button type="button" class="btn-sm btn-danger js-q-up" aria-label="up">↑</button>' +
          '<button type="button" class="btn-sm btn-danger js-q-down" aria-label="down">↓</button>' +
          '<button type="button" class="btn-sm btn-danger js-q-del" aria-label="remove">×</button>';
        row.querySelector(".js-q-label").addEventListener("input", function () { questions[index].label = this.value; sync(); });
        const helpEl = row.querySelector(".js-q-help");
        if (helpEl) helpEl.addEventListener("input", function () { questions[index].help = this.value; sync(); });
        const valueEl = row.querySelector(".js-q-value");
        if (valueEl) valueEl.addEventListener("input", function () { questions[index].value = this.value; sync(); });
        row.querySelector(".js-q-required").addEventListener("change", function () { questions[index].required = this.checked; sync(); });
        row.querySelector(".js-q-del").addEventListener("click", function () { questions.splice(index, 1); renderAll(); });
        row.querySelector(".js-q-up").addEventListener("click", function () { if (index > 0) { const t = questions[index - 1]; questions[index - 1] = questions[index]; questions[index] = t; renderAll(); } });
        row.querySelector(".js-q-down").addEventListener("click", function () { if (index < questions.length - 1) { const t = questions[index + 1]; questions[index + 1] = questions[index]; questions[index] = t; renderAll(); } });
        list.appendChild(row);
      };

      const renderAll = function () {
        list.textContent = "";
        questions.forEach(renderRow);
        sync();
        errBox.hidden = true;
      };

      addBtn.addEventListener("click", function () {
        questions.push({ id: "q" + (questions.length + 1) + "-" + Date.now().toString(36), type: typeSelect.value, label: "", help: "", required: false, value: "" });
        renderAll();
      });

      const form = root.closest("form");
      form.addEventListener("submit", function () {
        try {
          questions = questions.filter(function (q) { return q.type === "info" || q.label.trim(); });
          sync();
        } catch (e) {
          errBox.textContent = "Invalid field definitions.";
          errBox.hidden = false;
        }
      });
      renderAll();
    });
  });
}());
