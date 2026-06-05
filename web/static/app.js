const state = {
  view: "capture",
  ownerPhone: "",
  period: "TODAY",
  capturePending: false,
  recorder: null,
  audioChunks: [],
  recordedAudio: null,
  recordedMimeType: "audio/webm",
};

const titles = {
  capture: "Capture",
  dashboard: "Dashboard",
  customers: "Customers",
  transactions: "Transactions",
  inventory: "Inventory",
  reminders: "Reminders",
};

const view = document.querySelector("#view");
const pageTitle = document.querySelector("#page-title");
const filters = document.querySelector("#filters");
const ownerPhone = document.querySelector("#owner-phone");
const period = document.querySelector("#period");

function naira(value) {
  return `N${Number(value || 0).toLocaleString()}`;
}

function dateText(value) {
  if (!value) return "-";
  return new Date(value).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function queryString(extra = {}) {
  const params = new URLSearchParams();
  if (state.ownerPhone) params.set("owner_phone", state.ownerPhone);
  Object.entries(extra).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  const text = params.toString();
  return text ? `?${text}` : "";
}

async function api(path, extra = {}) {
  const response = await fetch(`/app/api/${path}${queryString(extra)}`);
  if (!response.ok) {
    throw new Error(`Could not load ${path}`);
  }
  return response.json();
}

function setLoading() {
  view.innerHTML = '<div class="panel loading">Loading...</div>';
}

function renderTable(columns, rows, emptyText) {
  if (!rows.length) {
    return `<div class="empty">${emptyText}</div>`;
  }

  const head = columns.map((column) => `<th>${column.label}</th>`).join("");
  const body = rows.map((row) => {
    const cells = columns.map((column) => `<td>${column.render(row)}</td>`).join("");
    return `<tr>${cells}</tr>`;
  }).join("");

  return `
    <div class="table-wrap">
      <table>
        <thead><tr>${head}</tr></thead>
        <tbody>${body}</tbody>
      </table>
    </div>
  `;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function panel(title, subtitle, body) {
  return `
    <section class="panel">
      <div class="panel-header">
        <h2>${title}</h2>
        <span>${subtitle || ""}</span>
      </div>
      ${body}
    </section>
  `;
}

function captureMessageBlock(messages) {
  if (!messages || !messages.length) return "";
  return messages.map((message) => `<pre class="message-preview">${escapeHtml(message)}</pre>`).join("");
}

function pendingSummary(pending) {
  if (!pending) return "";
  const items = [
    ["Action", pending.action],
    ["Customer", pending.customer_name || "Direct sale"],
    ["Product", pending.product || "-"],
    ["Quantity", pending.quantity ? `${pending.quantity} ${pending.unit || ""}`.trim() : "-"],
    ["Credit/Sale amount", naira(pending.buy_amount)],
    ["Payment", naira(pending.paid_amount)],
    ["Due date", pending.due_date ? dateText(pending.due_date) : "-"],
  ];
  return `
    <div class="summary-grid">
      ${items.map(([label, value]) => `
        <div>
          <span>${label}</span>
          <strong>${escapeHtml(value)}</strong>
        </div>
      `).join("")}
    </div>
  `;
}

async function blobToBase64(blob) {
  const buffer = await blob.arrayBuffer();
  let binary = "";
  const bytes = new Uint8Array(buffer);
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return btoa(binary);
}

function renderCapturePreview(result, data) {
  state.capturePending = Boolean(data.pending);
  result.className = "capture-result";
  result.innerHTML = `
    ${data.transcript ? `<div class="transcript"><span>Transcript</span><strong>${escapeHtml(data.transcript)}</strong></div>` : ""}
    ${captureMessageBlock(data.messages)}
    ${pendingSummary(data.pending)}
    <div class="button-row">
      <button type="button" id="capture-confirm" ${data.pending ? "" : "disabled"}>Confirm save</button>
    </div>
    ${data.message ? `<p class="notice">${escapeHtml(data.message)}</p>` : ""}
  `;

  const confirm = document.querySelector("#capture-confirm");
  confirm.addEventListener("click", async () => {
    confirm.disabled = true;
    confirm.textContent = "Saving...";
    const saveResponse = await fetch("/app/api/capture/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone: state.ownerPhone }),
    });
    const saved = await saveResponse.json();
    state.capturePending = false;
    result.innerHTML = `
      ${captureMessageBlock(saved.messages)}
      <p class="notice strong">Saved. The dashboard and transactions tabs now include this record.</p>
    `;
  });
}

async function renderCapture() {
  view.innerHTML = `
    <section class="capture-layout">
      <div class="panel capture-panel">
        <div class="panel-header">
          <h2>Record from text</h2>
          <span>Same style as WhatsApp</span>
        </div>
        <form class="capture-form" id="capture-form">
          <label>
            Registered phone
            <input id="capture-phone" autocomplete="tel" placeholder="234..." value="${escapeHtml(state.ownerPhone)}" />
          </label>
          <div class="voice-desk">
            <div>
              <span>Voice capture</span>
              <strong id="voice-status">Ready to record</strong>
            </div>
            <div class="button-row">
              <button type="button" class="secondary" id="voice-record">Record</button>
              <button type="button" class="secondary" id="voice-stop" disabled>Stop</button>
              <button type="button" id="voice-preview" disabled>Transcribe preview</button>
            </div>
            <audio id="voice-playback" controls hidden></audio>
          </div>
          <label>
            Transaction text
            <textarea id="capture-text" rows="7" placeholder="Amina bought 1 rice at 12000 paid 5000 due 20/06/2026"></textarea>
          </label>
          <div class="example-row" aria-label="Example transaction formats">
            <button type="button" data-example="Amina bought 1 rice at 12000 paid 5000 due 20/06/2026">Credit + payment</button>
            <button type="button" data-example="Amina bought 1 rice at 12000">Credit sale</button>
            <button type="button" data-example="Amina paid 5000">Payment</button>
          </div>
          <div class="button-row">
            <button type="submit">Preview</button>
            <button type="button" class="secondary" id="capture-clear">Clear</button>
          </div>
        </form>
      </div>
      <div class="panel">
        <div class="panel-header">
          <h2>Preview</h2>
          <span>Confirm before saving</span>
        </div>
        <div id="capture-result" class="capture-result empty">No preview yet.</div>
      </div>
    </section>
  `;

  const form = document.querySelector("#capture-form");
  const result = document.querySelector("#capture-result");
  const phoneInput = document.querySelector("#capture-phone");
  const textInput = document.querySelector("#capture-text");
  const clearButton = document.querySelector("#capture-clear");
  const recordButton = document.querySelector("#voice-record");
  const stopButton = document.querySelector("#voice-stop");
  const voicePreviewButton = document.querySelector("#voice-preview");
  const voiceStatus = document.querySelector("#voice-status");
  const voicePlayback = document.querySelector("#voice-playback");

  document.querySelectorAll("[data-example]").forEach((button) => {
    button.addEventListener("click", () => {
      textInput.value = button.dataset.example;
      textInput.focus();
    });
  });

  clearButton.addEventListener("click", () => {
    textInput.value = "";
    result.className = "capture-result empty";
    result.textContent = "No preview yet.";
    state.capturePending = false;
    state.recordedAudio = null;
    voicePlayback.hidden = true;
    voicePreviewButton.disabled = true;
    voiceStatus.textContent = "Ready to record";
  });

  recordButton.addEventListener("click", async () => {
    if (!navigator.mediaDevices || !window.MediaRecorder) {
      result.className = "capture-result empty";
      result.textContent = "Voice recording is not available in this browser.";
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      state.audioChunks = [];
      state.recordedMimeType = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "";
      state.recorder = new MediaRecorder(
        stream,
        state.recordedMimeType ? { mimeType: state.recordedMimeType } : undefined
      );
      state.recorder.addEventListener("dataavailable", (event) => {
        if (event.data.size > 0) state.audioChunks.push(event.data);
      });
      state.recorder.addEventListener("stop", () => {
        stream.getTracks().forEach((track) => track.stop());
        state.recordedAudio = new Blob(state.audioChunks, {
          type: state.recordedMimeType || "audio/webm",
        });
        voicePlayback.src = URL.createObjectURL(state.recordedAudio);
        voicePlayback.hidden = false;
        voicePreviewButton.disabled = false;
        recordButton.disabled = false;
        stopButton.disabled = true;
        voiceStatus.textContent = "Recording ready";
      });
      state.recorder.start();
      recordButton.disabled = true;
      stopButton.disabled = false;
      voicePreviewButton.disabled = true;
      voiceStatus.textContent = "Recording...";
    } catch (error) {
      result.className = "capture-result empty";
      result.textContent = "Microphone permission was not granted.";
    }
  });

  stopButton.addEventListener("click", () => {
    if (state.recorder && state.recorder.state !== "inactive") {
      state.recorder.stop();
    }
  });

  voicePreviewButton.addEventListener("click", async () => {
    state.ownerPhone = phoneInput.value.trim();
    ownerPhone.value = state.ownerPhone;
    if (!state.recordedAudio) return;

    result.className = "capture-result loading";
    result.textContent = "Transcribing voice...";
    try {
      const audioBase64 = await blobToBase64(state.recordedAudio);
      const response = await fetch("/app/api/capture/voice", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          phone: state.ownerPhone,
          audio_base64: audioBase64,
          mime_type: state.recordedAudio.type || "audio/webm",
        }),
      });
      const data = await response.json();
      if (data.transcript) textInput.value = data.transcript;
      renderCapturePreview(result, data);
    } catch (error) {
      result.className = "capture-result empty";
      result.textContent = error.message;
    }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    state.ownerPhone = phoneInput.value.trim();
    ownerPhone.value = state.ownerPhone;
    result.className = "capture-result loading";
    result.textContent = "Reading transaction...";

    try {
      const response = await fetch("/app/api/capture/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          phone: state.ownerPhone,
          text: textInput.value.trim(),
        }),
      });
      const data = await response.json();
      renderCapturePreview(result, data);
    } catch (error) {
      result.className = "capture-result empty";
      result.textContent = error.message;
    }
  });
}

async function renderDashboard() {
  const data = await api("dashboard", { period: state.period });
  const summary = data.summary;
  view.innerHTML = `
    <section class="metrics">
      <div class="metric accent-green"><span>Total sales, ${data.period_label}</span><strong>${naira(summary.total_sales_amount)}</strong></div>
      <div class="metric accent-blue"><span>Payments received</span><strong>${naira(summary.total_pay_amount)}</strong></div>
      <div class="metric accent-amber"><span>Outstanding balance</span><strong>${naira(summary.total_outstanding)}</strong></div>
      <div class="metric accent-rose"><span>Total customers</span><strong>${Number(summary.total_customers || 0).toLocaleString()}</strong></div>
    </section>
    ${panel(
      "Top debtors",
      "Highest balances first",
      renderTable(
        [
          { label: "Customer", render: (row) => row.name || "-" },
          { label: "Balance", render: (row) => naira(row.balance) },
        ],
        data.top_debtors,
        "No unpaid debtors found."
      )
    )}
  `;
}

async function renderCustomers() {
  const data = await api("customers");
  view.innerHTML = panel(
    "Customers",
    "Latest 100 records",
    renderTable(
      [
        { label: "Name", render: (row) => row.name || "-" },
        { label: "Phone", render: (row) => row.phone || "-" },
        { label: "Owner", render: (row) => row.owner_phone || "-" },
        { label: "Balance", render: (row) => naira(row.balance) },
        { label: "Created", render: (row) => dateText(row.created_at) },
      ],
      data.customers,
      "No customers found."
    )
  );
}

async function renderTransactions() {
  const data = await api("transactions", { period: state.period });
  view.innerHTML = panel(
    "Transactions",
    "Latest 100 records",
    renderTable(
      [
        { label: "ID", render: (row) => `#${row.id}` },
        { label: "Type", render: (row) => `<span class="status">${row.type}</span>` },
        { label: "Customer", render: (row) => row.customer || "-" },
        { label: "Product", render: (row) => row.product || "-" },
        { label: "Amount", render: (row) => naira(row.amount) },
        { label: "Due", render: (row) => dateText(row.due_date) },
        { label: "Date", render: (row) => dateText(row.created_at) },
      ],
      data.transactions,
      "No transactions found."
    )
  );
}

async function renderInventory() {
  const data = await api("inventory");
  view.innerHTML = panel(
    "Inventory",
    "Latest 100 products",
    renderTable(
      [
        { label: "Product", render: (row) => row.name || "-" },
        { label: "Qty", render: (row) => `${row.quantity} ${row.unit || ""}`.trim() },
        { label: "Selling price", render: (row) => naira(row.selling_price) },
        { label: "Cost price", render: (row) => naira(row.cost_price) },
        {
          label: "Status",
          render: (row) => {
            if (!row.is_available) return '<span class="status bad">Unavailable</span>';
            if (row.low_stock_alert !== null && row.quantity <= row.low_stock_alert) return '<span class="status warn">Low stock</span>';
            return '<span class="status">Available</span>';
          },
        },
        { label: "Updated", render: (row) => dateText(row.updated_at) },
      ],
      data.items,
      "No inventory items found."
    )
  );
}

async function renderReminders() {
  const data = await api("reminders");
  view.innerHTML = panel(
    "Reminders",
    "Latest 100 queued reminders",
    renderTable(
      [
        { label: "Customer", render: (row) => row.customer_name || "-" },
        { label: "Balance", render: (row) => naira(row.balance) },
        { label: "Due", render: (row) => dateText(row.due_date) },
        { label: "Type", render: (row) => row.type || "-" },
        { label: "Status", render: (row) => `<span class="status">${row.status || "-"}</span>` },
        { label: "Message", render: (row) => row.message_text || "-" },
      ],
      data.reminders,
      "No reminders queued."
    )
  );
}

async function render() {
  pageTitle.textContent = titles[state.view];
  setLoading();
  try {
    if (state.view === "capture") await renderCapture();
    if (state.view === "dashboard") await renderDashboard();
    if (state.view === "customers") await renderCustomers();
    if (state.view === "transactions") await renderTransactions();
    if (state.view === "inventory") await renderInventory();
    if (state.view === "reminders") await renderReminders();
  } catch (error) {
    view.innerHTML = `<div class="panel empty">${error.message}</div>`;
  }
}

document.querySelectorAll(".nav-item").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".nav-item").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    state.view = button.dataset.view;
    render();
  });
});

filters.addEventListener("submit", (event) => {
  event.preventDefault();
  state.ownerPhone = ownerPhone.value.trim();
  state.period = period.value;
  render();
});

render();
