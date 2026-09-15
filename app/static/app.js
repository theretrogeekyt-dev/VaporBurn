// ==============================================================================
// VaporBurn Web Client Application
// Matching VaporFetch UI Aesthetics and Interactive Architecture
// ==============================================================================

let currentTab = "library";
let libraryGames = [];
let activeEventSource = null;
let activeJobId = null;

// On Page Load
document.addEventListener("DOMContentLoaded", () => {
  loadLibrary();
  checkActiveJobs();
  loadIsos();
  loadStorage();
  loadSettings();

  // Poll storage and job status periodically
  setInterval(loadStorage, 15000);
  setInterval(checkActiveJobs, 8000);
});

// ---------------- Navigation & View Switching ---------------- //

function switchTab(tabName) {
  currentTab = tabName;

  document.querySelectorAll(".tab-btn").forEach(btn => btn.classList.remove("active"));
  document.querySelectorAll(".view-panel").forEach(panel => panel.classList.remove("active"));

  if (tabName === "library") {
    document.getElementById("tabLibraryBtn").classList.add("active");
    document.getElementById("libraryView").classList.add("active");
  } else if (tabName === "queue") {
    document.getElementById("tabQueueBtn").classList.add("active");
    document.getElementById("queueView").classList.add("active");
    checkActiveJobs();
  } else if (tabName === "isos") {
    document.getElementById("tabIsosBtn").classList.add("active");
    document.getElementById("isosView").classList.add("active");
    loadIsos();
  }
}

function refreshCurrentView() {
  if (currentTab === "library") loadLibrary();
  else if (currentTab === "queue") checkActiveJobs();
  else if (currentTab === "isos") loadIsos();
  loadStorage();
}

// ---------------- Storage Telemetry ---------------- //

async function loadStorage() {
  try {
    const res = await fetch("/api/system/storage");
    if (!res.ok) return;
    const data = await res.json();
    const out = data.output_storage;
    if (out) {
      document.getElementById("storageText").innerText = `${out.used_formatted} / ${out.total_formatted}`;
      document.getElementById("storageFill").style.width = `${out.percent}%`;
    }
  } catch (err) {
    console.warn("Error fetching storage:", err);
  }
}

// ---------------- Library Management ---------------- //

async function loadLibrary() {
  try {
    const res = await fetch("/api/library");
    const data = await res.json();
    libraryGames = data.games || [];

    document.getElementById("libraryBadge").innerText = libraryGames.length;
    document.getElementById("libraryBadge").style.display = libraryGames.length > 0 ? "inline-block" : "none";
    document.getElementById("libCountText").innerText = `${libraryGames.length} backup(s) detected`;

    renderGames(libraryGames);
  } catch (err) {
    console.error("Failed loading library:", err);
  }
}

function renderGames(games) {
  const grid = document.getElementById("gamesGrid");
  const empty = document.getElementById("emptyLibrary");

  if (!games || games.length === 0) {
    grid.innerHTML = "";
    empty.style.display = "block";
    return;
  }

  empty.style.display = "none";
  grid.innerHTML = games.map(game => {
    const goldbergBadge = game.has_goldberg
      ? `<span class="badge badge-steam" title="Goldberg Steam API detected">Goldberg Ready</span>`
      : "";
    const savesBadge = game.has_saves
      ? `<span class="badge badge-success" title="${game.save_count} save file(s) found">Saves (${game.save_count})</span>`
      : "";

    return `
      <div class="game-card">
        <div class="card-banner-wrapper">
          <img class="card-banner" src="${game.banner_url}" alt="${escapeHtml(game.title)}"
               onerror="this.onerror=null;this.src='/static/default_banner.svg';">
          <div class="card-banner-overlay">
            <span class="tag-pill" style="background: rgba(0,0,0,0.75); font-weight:700;">
              ${game.app_id ? `AppID: ${game.app_id}` : `Offline Game`}
            </span>
          </div>
        </div>
        <div class="card-body">
          <h3 class="card-title" title="${game.title}">${game.title}</h3>
          <div class="card-meta">
            <span>💾 ${game.size_formatted}</span>
            <span>📂 ${escapeHtml(game.folder_name)}</span>
          </div>
          <div class="card-tags">
            ${goldbergBadge}
            ${savesBadge}
            ${game.redist_count > 0 ? `<span class="tag-pill">📦 ${game.redist_count} Redist(s)</span>` : ""}
            ${game.primary_exe ? `<span class="tag-pill" style="max-width: 140px; overflow:hidden; text-overflow:ellipsis;" title="${game.primary_exe}">⚙️ ${game.primary_exe}</span>` : ""}
          </div>
          <div class="card-actions">
            <button class="btn btn-primary" onclick="openPackageModal('${encodeURIComponent(JSON.stringify(game))}')">
              🔥 Package to ISO
            </button>
          </div>
        </div>
      </div>
    `;
  }).join("");
}

function handleSearch() {
  const query = document.getElementById("searchInput").value.toLowerCase().trim();
  const filtered = libraryGames.filter(g =>
    g.title.toLowerCase().includes(query) ||
    g.app_id.includes(query) ||
    g.folder_name.toLowerCase().includes(query)
  );
  renderGames(filtered);
}

function handleSort() {
  const mode = document.getElementById("sortSelect").value;
  let sorted = [...libraryGames];

  if (mode === "title_asc") {
    sorted.sort((a, b) => a.title.localeCompare(b.title));
  } else if (mode === "title_desc") {
    sorted.sort((a, b) => b.title.localeCompare(a.title));
  } else if (mode === "size_desc") {
    sorted.sort((a, b) => b.size_bytes - a.size_bytes);
  } else if (mode === "appid_asc") {
    sorted.sort((a, b) => Number(a.app_id) - Number(b.app_id));
  }
  renderGames(sorted);
}

// ---------------- Packaging Modal ---------------- //

function openPackageModal(encodedGame) {
  const game = JSON.parse(decodeURIComponent(encodedGame));

  document.getElementById("modalFolderName").value = game.folder_name;
  document.getElementById("modalGameTitle").value = game.title;
  document.getElementById("modalAppId").value = game.app_id;

  const saveRow = document.getElementById("saveRow");
  if (game.has_saves) {
    saveRow.style.display = "flex";
    document.getElementById("modalRestoreSaves").checked = true;
  } else {
    saveRow.style.display = "none";
    document.getElementById("modalRestoreSaves").checked = false;
  }

  document.getElementById("packageModal").classList.add("open");
}

function closePackageModal() {
  document.getElementById("packageModal").classList.remove("open");
}

function handleDiscTypeChange() {
  const type = document.getElementById("modalDiscType").value;
  document.getElementById("customSizeGroup").style.display = (type === "custom") ? "block" : "none";
}

async function submitPackageJob(e) {
  e.preventDefault();

  const payload = {
    folder_name: document.getElementById("modalFolderName").value,
    game_title: document.getElementById("modalGameTitle").value,
    app_id: document.getElementById("modalAppId").value,
    disc_type: document.getElementById("modalDiscType").value,
    disc_size_mb: parseInt(document.getElementById("modalCustomSize")?.value || "0") || 0,
    limit_ram: document.getElementById("modalLimitRam").checked,
    player_name: document.getElementById("modalPlayerName").value,
    language: document.getElementById("modalLanguage").value,
    steam_id: document.getElementById("modalSteamId").value,
    firewall_rule: document.getElementById("modalFirewall").checked,
  };

  try {
    const res = await fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      const err = await res.json();
      alert("Failed to enqueue job: " + (err.detail || "Server error"));
      return;
    }

    const data = await res.json();
    closePackageModal();
    switchTab("queue");
    checkActiveJobs();
    connectJobStream(data.job_id);
  } catch (err) {
    alert("Network error enqueuing packaging job: " + err);
  }
}

// ---------------- Queue & SSE Streaming ---------------- //

async function checkActiveJobs() {
  try {
    const res = await fetch("/api/jobs");
    const data = await res.json();
    const jobs = data.jobs || [];
    const activeId = data.active_job_id;

    // Badge count for unfinished jobs
    const pendingCount = jobs.filter(j => j.status === "queued" || j.status === "running").length;
    document.getElementById("queueBadge").innerText = pendingCount;
    document.getElementById("queueBadge").style.display = pendingCount > 0 ? "inline-block" : "none";

    renderJobHistory(jobs);

    if (activeId) {
      const activeJob = jobs.find(j => j.id === activeId);
      if (activeJob) {
        showActiveJob(activeJob);
        if (activeJobId !== activeId) {
          connectJobStream(activeId);
        }
      }
    } else {
      document.getElementById("activeJobSection").style.display = "none";
      document.getElementById("noActiveJob").style.display = "block";
    }
  } catch (err) {
    console.warn("Failed checking jobs:", err);
  }
}

function showActiveJob(job) {
  document.getElementById("noActiveJob").style.display = "none";
  document.getElementById("activeJobSection").style.display = "block";

  document.getElementById("activeJobTitle").innerText = job.game_title;
  document.getElementById("activeJobMeta").innerText = `Job ID: ${job.id} | Mode: ${job.params.disc_type.toUpperCase()} | AppID: ${job.app_id}`;
  document.getElementById("activeJobStage").innerText = job.stage;
  document.getElementById("activeJobPercent").innerText = `${job.progress}%`;
  document.getElementById("activeJobBar").style.width = `${job.progress}%`;

  const badge = document.getElementById("activeJobBadge");
  if (job.status === "running") {
    badge.className = "badge badge-iso pulse-glow";
    badge.innerText = "PACKAGING";
  } else if (job.status === "queued") {
    badge.className = "badge badge-steam";
    badge.innerText = "QUEUED";
  }
}

function connectJobStream(jobId) {
  if (activeEventSource) {
    activeEventSource.close();
  }

  activeJobId = jobId;
  const terminal = document.getElementById("terminalLogs");
  terminal.innerHTML = "";

  activeEventSource = new EventSource(`/api/jobs/${jobId}/stream`);

  activeEventSource.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data);

      if (msg.type === "log") {
        appendLogLine(msg.line);
      } else if (msg.type === "progress") {
        document.getElementById("activeJobStage").innerText = msg.stage;
        document.getElementById("activeJobPercent").innerText = `${msg.progress}%`;
        document.getElementById("activeJobBar").style.width = `${msg.progress}%`;
      } else if (msg.type === "complete" || msg.type === "cancelled" || msg.type === "error") {
        checkActiveJobs();
        loadIsos();
        loadStorage();
      }
    } catch (err) {
      console.error("Error parsing SSE frame:", err);
    }
  };

  activeEventSource.onerror = () => {
    activeEventSource.close();
    activeEventSource = null;
  };
}

function appendLogLine(line) {
  const terminal = document.getElementById("terminalLogs");
  const div = document.createElement("div");

  if (line.includes("ERROR") || line.includes("failed")) {
    div.className = "log-error";
  } else if (line.includes("Successfully") || line.includes("complete")) {
    div.className = "log-success";
  } else if (line.includes("Warning") || line.includes("⚠")) {
    div.className = "log-warn";
  }

  div.textContent = line;
  terminal.appendChild(div);

  if (document.getElementById("autoScrollCheck").checked) {
    terminal.scrollTop = terminal.scrollHeight;
  }
}

function clearLogs() {
  document.getElementById("terminalLogs").innerHTML = "";
}

async function cancelActiveJob() {
  if (!activeJobId) return;
  if (!confirm("Are you sure you want to abort the current packaging job?")) return;

  try {
    await fetch(`/api/jobs/${activeJobId}/cancel`, { method: "POST" });
    checkActiveJobs();
  } catch (err) {
    alert("Failed cancelling job: " + err);
  }
}

function renderJobHistory(jobs) {
  const tbody = document.getElementById("jobsHistoryBody");
  if (!jobs || jobs.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; color: var(--text-dim);">No packaging jobs recorded.</td></tr>`;
    return;
  }

  tbody.innerHTML = jobs.map(j => {
    let statusBadge = `<span class="badge">${j.status}</span>`;
    if (j.status === "completed") statusBadge = `<span class="badge badge-success">COMPLETED</span>`;
    else if (j.status === "running") statusBadge = `<span class="badge badge-iso pulse-glow">RUNNING</span>`;
    else if (j.status === "failed") statusBadge = `<span class="badge" style="background: rgba(239,68,68,0.2); color: #ef4444;">FAILED</span>`;
    else if (j.status === "cancelled") statusBadge = `<span class="badge" style="background: rgba(148,163,184,0.2); color: #94a3b8;">CANCELLED</span>`;

    const artifacts = (j.output_files && j.output_files.length > 0)
      ? j.output_files.map(f => `<span class="tag-pill" style="color:#38bdf8;">${escapeHtml(f)}</span>`).join(" ")
      : (j.error ? `<span style="color:#ef4444; font-size:12px;">${escapeHtml(j.error.slice(0, 50))}</span>` : "--");

    const dateStr = j.created_at ? new Date(j.created_at * 1000).toLocaleString() : "--";

    return `
      <tr>
        <td><strong>${escapeHtml(j.game_title)}</strong></td>
        <td><span class="tag-pill">${escapeHtml(j.params.disc_type.toUpperCase())}</span></td>
        <td>${statusBadge}</td>
        <td>${artifacts}</td>
        <td style="font-size:12px; color:var(--text-dim);">${dateStr}</td>
      </tr>
    `;
  }).join("");
}

// ---------------- Completed ISOs Management ---------------- //

async function loadIsos() {
  try {
    const res = await fetch("/api/isos");
    const data = await res.json();
    const isos = data.isos || [];

    document.getElementById("isosBadge").innerText = isos.length;
    document.getElementById("isosBadge").style.display = isos.length > 0 ? "inline-block" : "none";

    const tbody = document.getElementById("isosTableBody");
    const empty = document.getElementById("emptyIsos");

    if (isos.length === 0) {
      tbody.innerHTML = "";
      empty.style.display = "block";
      return;
    }

    empty.style.display = "none";
    tbody.innerHTML = isos.map(iso => {
      const shaShort = iso.sha256 ? `${iso.sha256.slice(0, 12)}...` : "--";

      return `
        <tr>
          <td>
            <strong style="color: #f1f5f9;">💿 ${escapeHtml(iso.filename)}</strong>
          </td>
          <td>${iso.size_formatted}</td>
          <td class="sha256-cell" title="${iso.sha256}">
            ${shaShort}
            ${iso.sha256 ? `<button class="btn btn-secondary btn-sm" style="padding: 2px 6px; margin-left: 6px;" onclick="copyToClipboard('${iso.sha256}')">Copy</button>` : ""}
          </td>
          <td>
            <div style="display: flex; gap: 8px;">
              <a href="${iso.download_url}" class="btn btn-primary btn-sm" download>Download ISO</a>
              ${iso.checksum_url ? `<a href="${iso.checksum_url}" class="btn btn-secondary btn-sm" download>.sha256</a>` : ""}
            </div>
          </td>
        </tr>
      `;
    }).join("");
  } catch (err) {
    console.error("Failed loading ISOs:", err);
  }
}

// ---------------- Settings Modal ---------------- //

async function loadSettings() {
  try {
    const res = await fetch("/api/settings");
    if (!res.ok) return;
    const s = await res.json();

    document.getElementById("settingDefaultDisc").value = s.default_disc_type || "single";
    document.getElementById("settingDefaultPlayer").value = s.default_player_name || "VaporPlayer";
    document.getElementById("settingDefaultLang").value = s.default_language || "english";

    document.getElementById("modalPlayerName").value = s.default_player_name || "VaporPlayer";
    document.getElementById("modalLanguage").value = s.default_language || "english";
    document.getElementById("modalSteamId").value = s.default_steamid || "76561197960287930";
  } catch (err) {
    console.warn("Failed loading settings:", err);
  }
}

async function saveGlobalSettings() {
  const payload = {
    default_disc_type: document.getElementById("settingDefaultDisc").value,
    default_player_name: document.getElementById("settingDefaultPlayer").value,
    default_language: document.getElementById("settingDefaultLang").value,
  };

  try {
    await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    closeSettingsModal();
    loadSettings();
    alert("Settings saved successfully!");
  } catch (err) {
    alert("Failed saving settings: " + err);
  }
}

function openSettingsModal() {
  document.getElementById("settingsModal").classList.add("open");
}

function closeSettingsModal() {
  document.getElementById("settingsModal").classList.remove("open");
}

// ---------------- Helpers ---------------- //

function copyToClipboard(text) {
  navigator.clipboard.writeText(text).then(() => {
    alert("SHA-256 Checksum copied to clipboard:\n" + text);
  }).catch(() => {
    prompt("Copy Checksum:", text);
  });
}

function escapeHtml(unsafe) {
  if (!unsafe) return "";
  return unsafe
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

