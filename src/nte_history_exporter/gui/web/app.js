"use strict";

// Thin renderer: the Python bridge owns all capture logic and hands this page
// a list of render operations from poll(). See docs/gui.md.

const POLL_MS = 80;

const $ = (id) => document.getElementById(id);
let api;
let TEXT = {};
let captureState = "idle"; // idle | running | stopping
let backend = "auto";
let logHasEntries = false;
const dialogs = [];
let dialogOpen = false;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// Setup ---------------------------------------------------------------------

function fillStaticText() {
  for (const node of document.querySelectorAll("[data-text]")) {
    node.textContent = TEXT[node.dataset.text];
  }
  for (const node of document.querySelectorAll("[data-placeholder]")) {
    node.placeholder = TEXT[node.dataset.placeholder];
  }
}

function buildBackends(backends) {
  const group = $("backends");
  group.setAttribute("role", "radiogroup");
  for (const name of backends) {
    const button = el("button", "", name);
    button.type = "button";
    button.setAttribute("role", "radio");
    button.addEventListener("click", () => selectBackend(name));
    group.append(button);
  }
  selectBackend(backend);
}

function buildTrackers(trackers) {
  const group = $("trackers");
  group.style.display = "contents";
  for (const { key, label } of trackers) {
    const button = el("button", "link-pill", `${label} ↗`);
    button.type = "button";
    button.addEventListener("click", () => openTracker(key, button));
    group.append(button);
  }
}

function selectBackend(name) {
  backend = name;
  for (const button of $("backends").children) {
    button.setAttribute("aria-checked", String(button.textContent === name));
  }
}

function renderInstructions() {
  const steps = el("div", "steps");
  steps.append(el("h3", "", TEXT.how_to));
  const list = el("ol");
  TEXT.instructions.forEach((step, index) => {
    const item = el("li");
    item.append(el("span", "step-number", String(index + 1)), el("span", "", step));
    list.append(item);
  });
  steps.append(list);
  $("log").replaceChildren(steps);
  logHasEntries = false;
}

// Render operations ---------------------------------------------------------

const ops = {
  reset() {
    $("rows").replaceChildren();
    $("rows-empty").hidden = false;
    $("log").replaceChildren();
    logHasEntries = false;
  },

  log({ segments }) {
    const log = $("log");
    if (!logHasEntries) {
      log.replaceChildren();
      logHasEntries = true;
    }
    const line = el("div");
    for (const [text, tag] of segments) line.append(el("span", tag, text));
    if (!segments.some(([text]) => text)) line.textContent = " ";
    log.append(line);
    log.scrollTop = log.scrollHeight;
  },

  row({ label, pages, status, tag }) {
    let row = [...$("rows").children].find((node) => node.dataset.label === label);
    if (!row) {
      row = el("div", "captured-row");
      row.dataset.label = label;
      row.append(el("span", "banner"), el("span", "pages"), el("span", "badge"));
      $("rows").append(row);
      $("rows-empty").hidden = true;
    }
    const [bannerNode, pagesNode, badge] = row.children;
    bannerNode.textContent = bannerNode.title = label;
    pagesNode.textContent = pagesNode.title = pages;
    badge.textContent = badge.title = status;
    badge.dataset.tag = tag;
    badge.hidden = !status;
  },

  status({ text }) {
    $("status").textContent = text;
  },

  state({ state }) {
    captureState = state;
    $("status-dot").dataset.state = state;
    const button = $("capture");
    button.classList.toggle("pill-primary", state === "idle");
    button.classList.toggle("pill-danger", state === "running");
    button.disabled = state === "stopping";
    button.textContent = { idle: TEXT.start, running: TEXT.stop, stopping: TEXT.stopping }[state];
    const locked = state !== "idle";
    for (const id of ["interface-ip", "user-uid", "copy-clipboard", "debug"]) $(id).disabled = locked;
    for (const option of $("backends").children) option.disabled = locked;
  },

  update({ text, busy }) {
    $("update").textContent = text;
    $("update").disabled = busy;
    $("update").hidden = false;
  },

  async copy({ text }) {
    api.report_copy(await copyToClipboard(text));
  },

  dialog(dialog) {
    dialogs.push(dialog);
    showNextDialog();
  },
};

async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // The async API needs window focus, which the capture usually took away.
    const area = el("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.append(area);
    area.select();
    const copied = document.execCommand("copy");
    area.remove();
    return copied;
  }
}

// Direct import -------------------------------------------------------------

// Protocol v1, described in docs/direct-import.md. The exports are gzipped, encrypted
// with AES-256-GCM and POSTed as { version: 1, ciphertext, iv }; the site answers
// { dropId }. The key stays on this machine until it is put after the # of the link,
// which browsers never send to a server.

const DROP_TIMEOUT_MS = 20000;

function toBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(binary);
}

function toBase64Url(buffer) {
  return toBase64(buffer).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function encryptDrop(plaintext) {
  const gzip = new Blob([plaintext]).stream().pipeThrough(new CompressionStream("gzip"));
  const compressed = await new Response(gzip).arrayBuffer();
  const key = crypto.getRandomValues(new Uint8Array(32));
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const cryptoKey = await crypto.subtle.importKey("raw", key, "AES-GCM", false, ["encrypt"]);
  const ciphertext = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, cryptoKey, compressed);
  return { key: toBase64Url(key), ciphertext: toBase64(ciphertext), iv: toBase64(iv) };
}

async function uploadDrop({ upload_url, plaintext }) {
  const { key, ciphertext, iv } = await encryptDrop(plaintext);
  const response = await fetch(upload_url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ version: 1, ciphertext, iv }),
    signal: AbortSignal.timeout(DROP_TIMEOUT_MS),
  });
  if (response.status !== 201) throw new Error(`HTTP ${response.status}`);
  const { dropId } = await response.json();
  return `${dropId}.${key}`;
}

async function openTracker(key, button) {
  button.disabled = true;
  try {
    const drop = await api.import_drop(key);
    let fragment = null;
    if (drop) {
      try {
        fragment = await uploadDrop(drop);
      } catch (error) {
        await api.report_drop_failed(key, error.message);
      }
    }
    await api.open_tracker(key, fragment);
  } finally {
    button.disabled = false;
  }
}

// Dialogs -------------------------------------------------------------------

function showNextDialog() {
  if (dialogOpen || dialogs.length === 0) return;
  dialogOpen = true;
  const { kind, id, title, message, choices, buttons } = dialogs.shift();

  $("dialog-title").textContent = title;
  $("dialog-message").textContent = message;
  const input = $("dialog-input");
  input.replaceChildren();
  let readValue = () => null;

  if (kind === "prompt" && choices) {
    for (const [value, label] of choices) {
      const option = el("label", "radio");
      const radio = el("input");
      radio.type = "radio";
      radio.name = "dialog-choice";
      radio.value = value;
      option.append(radio, el("span", "", label));
      input.append(option);
    }
    readValue = () => input.querySelector("input:checked")?.value ?? null;
  } else if (kind === "prompt") {
    const field = el("input");
    field.type = "text";
    field.spellcheck = false;
    input.append(field);
    readValue = () => field.value;
  }

  const finish = (answer) => {
    document.removeEventListener("keydown", onKey);
    $("dialog").hidden = true;
    dialogOpen = false;
    if (kind === "prompt") api.answer_prompt(id, answer === "submit" ? readValue() : null);
    if (kind === "close") api.resolve_close(answer);
    showNextDialog();
  };
  const onKey = (event) => {
    if (event.key === "Escape") finish(buttons.find((button) => button.cancel).value);
    else if (event.key === "Enter" && event.target.tagName !== "BUTTON") {
      finish(buttons.find((button) => button.primary).value);
    }
  };
  document.addEventListener("keydown", onKey);

  const actions = $("dialog-actions");
  actions.replaceChildren();
  for (const button of buttons) {
    const node = el("button", button.primary ? "pill pill-primary" : "pill", button.label);
    node.type = "button";
    node.addEventListener("click", () => finish(button.value));
    actions.append(node);
  }

  $("dialog").hidden = false;
  (input.querySelector("input") ?? actions.lastChild).focus();
}

// Events --------------------------------------------------------------------

function bindEvents() {
  $("settings").addEventListener("submit", (event) => {
    event.preventDefault();
    if (captureState === "running") {
      api.stop_capture();
    } else if (captureState === "idle") {
      api.start_capture({
        backend,
        interface_ip: $("interface-ip").value,
        user_uid: $("user-uid").value,
        copy_clipboard: $("copy-clipboard").checked,
        debug: $("debug").checked,
      });
    }
  });
  $("open-exports").addEventListener("click", () => api.open_exports());
  $("update").addEventListener("click", () => api.open_update());
}

async function pollLoop() {
  try {
    for (const { op, ...fields } of await api.poll()) ops[op](fields);
  } catch (error) {
    console.error(error);
  }
  setTimeout(pollLoop, POLL_MS);
}

window.addEventListener("pywebviewready", async () => {
  api = window.pywebview.api;
  const boot = await api.bootstrap();
  TEXT = boot.text;
  fillStaticText();
  $("version").textContent = `v${boot.version}`;
  buildBackends(boot.backends);
  buildTrackers(boot.trackers);
  renderInstructions();
  bindEvents();
  ops.status({ text: TEXT.status_idle });
  ops.state({ state: "idle" });
  pollLoop();
  api.ready();
});
