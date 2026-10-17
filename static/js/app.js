/**
 * Zillow LeadPulse Pro - Client Dashboard Application
 */

document.addEventListener("DOMContentLoaded", () => {
  // Application State
  const state = {
    activeTab: "tab-launchpad",
    selectedJobId: null,
    eventSource: null,
    leads: [],
    leadsPage: 1,
    leadsLimit: 50,
    leadsTotal: 0,
    leadsTotalPages: 1,
    jobs: [],
    autoScroll: true,
    pollingTimer: null
  };

  // DOM Elements Cache
  const elements = {
    // Nav
    tabs: document.querySelectorAll(".nav-tab"),
    tabPanes: document.querySelectorAll(".tab-pane"),
    activeJobsBadge: document.getElementById("active-jobs-badge"),

    // Header Metrics
    hdrEngineStatus: document.getElementById("hdr-engine-status"),
    hdrTotalLeads: document.getElementById("hdr-total-leads"),
    hdrTotalEmails: document.getElementById("hdr-total-emails"),
    hdrTotalPhones: document.getElementById("hdr-total-phones"),

    // Launchpad
    formNewJob: document.getElementById("form-new-job"),
    inputLocation: document.getElementById("input-location"),
    inputTotalPages: document.getElementById("input-total-pages"),
    selectJobAntibot: document.getElementById("select-job-antibot"),
    inputDelayMin: document.getElementById("input-delay-min"),
    inputDelayMax: document.getElementById("input-delay-max"),
    presetChips: document.querySelectorAll(".preset-chip"),
    btnStartScraping: document.getElementById("btn-start-scraping"),

    // Monitor
    jobsListContainer: document.getElementById("jobs-list-container"),
    btnRefreshJobs: document.getElementById("btn-refresh-jobs"),
    activeJobCard: document.getElementById("active-job-details-card"),
    jobStatusBadge: document.getElementById("job-status-badge"),
    jobTargetTitle: document.getElementById("job-target-title"),
    jobZillowLink: document.getElementById("job-zillow-link"),
    btnJobPause: document.getElementById("btn-job-pause"),
    btnJobResume: document.getElementById("btn-job-resume"),
    btnJobCancel: document.getElementById("btn-job-cancel"),
    btnJobDownloadCsv: document.getElementById("btn-job-download-csv"),
    btnJobDownloadExcel: document.getElementById("btn-job-download-excel"),
    jobProgressBar: document.getElementById("job-progress-bar"),
    jobProgressPercent: document.getElementById("job-progress-percent"),
    jobProgressPageText: document.getElementById("job-progress-page-text"),
    jobProgressCountText: document.getElementById("job-progress-count-text"),
    jobProgressErrorText: document.getElementById("job-progress-error-text"),
    terminalLogs: document.getElementById("terminal-logs"),
    chkAutoScroll: document.getElementById("chk-auto-scroll"),
    btnClearLogs: document.getElementById("btn-clear-logs"),

    // Leads Table
    leadsSearchInput: document.getElementById("leads-search-input"),
    filterHasEmail: document.getElementById("filter-has-email"),
    filterHasPhone: document.getElementById("filter-has-phone"),
    btnCopyTsv: document.getElementById("btn-copy-tsv"),
    btnExportAllCsv: document.getElementById("btn-export-all-csv"),
    btnOpenGoogleSheetsDialog: document.getElementById("btn-open-google-sheets-dialog"),
    leadsTableBody: document.getElementById("leads-table-body"),
    chkSelectAllLeads: document.getElementById("chk-select-all-leads"),
    tableStatsText: document.getElementById("table-stats-text"),
    pageIndicatorText: document.getElementById("page-indicator-text"),
    btnPrevPage: document.getElementById("btn-prev-page"),
    btnNextPage: document.getElementById("btn-next-page"),

    // Proxy Settings
    formProxySettings: document.getElementById("form-proxy-settings"),
    radioAntiBotModes: document.querySelectorAll('input[name="anti_bot_mode"]'),
    inputScraperapiKey: document.getElementById("input-scraperapi-key"),
    inputZenrowsKey: document.getElementById("input-zenrows-key"),
    textareaCustomProxies: document.getElementById("textarea-custom-proxies"),
    inputRotateEvery: document.getElementById("input-rotate-every"),
    settingsDelayMin: document.getElementById("settings-delay-min"),
    settingsDelayMax: document.getElementById("settings-delay-max"),
    settingsMaxRetries: document.getElementById("settings-max-retries"),
    btnTestProxy: document.getElementById("btn-test-proxy"),
    diagEngineVal: document.getElementById("diag-engine-val"),
    diagIpVal: document.getElementById("diag-ip-val"),
    diagLatencyVal: document.getElementById("diag-latency-val"),

    // Modal
    sheetsModal: document.getElementById("sheets-modal"),
    btnOpenSheetsModal: document.getElementById("btn-open-sheets-modal"),
    btnCloseSheetsModal: document.getElementById("btn-close-sheets-modal"),
    btnDoneSheetsModal: document.getElementById("btn-done-sheets-modal"),
    btnModalCopyTsv: document.getElementById("btn-modal-copy-tsv"),
    sheetsFormulaInput: document.getElementById("sheets-formula-input"),
    btnCopySheetsFormula: document.getElementById("btn-copy-sheets-formula"),

    // Toast
    toastContainer: document.getElementById("toast-container")
  };

  // -------------------------------------------------------------------------
  // INITIALIZATION
  // -------------------------------------------------------------------------
  function init() {
    setupTabNavigation();
    setupLaunchpad();
    setupMonitorControls();
    setupLeadsTable();
    setupProxySettings();
    setupSheetsModal();

    // Initial data fetch
    fetchGlobalMetrics();
    fetchJobs();
    fetchLeads();
    loadSettings();

    // Periodic metrics and jobs polling every 5 seconds
    state.pollingTimer = setInterval(() => {
      fetchGlobalMetrics();
      fetchJobs(false);
    }, 5000);
  }

  // -------------------------------------------------------------------------
  // TOAST NOTIFICATIONS
  // -------------------------------------------------------------------------
  function showToast(message, type = "info") {
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    const icon = type === "success" ? "✓" : type === "error" ? "⚠" : "ℹ";
    toast.innerHTML = `<span>${icon}</span> <span>${message}</span>`;
    elements.toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transform = "translateX(20px)";
      setTimeout(() => toast.remove(), 300);
    }, 4000);
  }

  // -------------------------------------------------------------------------
  // TAB NAVIGATION
  // -------------------------------------------------------------------------
  function setupTabNavigation() {
    elements.tabs.forEach(tab => {
      tab.addEventListener("click", () => {
        const targetId = tab.dataset.tab;
        switchTab(targetId);
      });
    });

    document.getElementById("btn-quick-new-job").addEventListener("click", () => {
      switchTab("tab-launchpad");
      elements.inputLocation.focus();
    });
  }

  function switchTab(tabId) {
    state.activeTab = tabId;
    elements.tabs.forEach(t => t.classList.toggle("active", t.dataset.tab === tabId));
    elements.tabPanes.forEach(pane => pane.classList.toggle("active", pane.id === tabId));

    if (tabId === "tab-leads") {
      fetchLeads();
    } else if (tabId === "tab-monitor") {
      fetchJobs();
    }
  }

  // -------------------------------------------------------------------------
  // METRICS
  // -------------------------------------------------------------------------
  async function fetchGlobalMetrics() {
    try {
      const res = await fetch("/api/metrics");
      if (!res.ok) return;
      const data = await res.json();
      elements.hdrTotalLeads.textContent = data.total_leads.toLocaleString();
      elements.hdrTotalEmails.textContent = data.emails_count.toLocaleString();
      elements.hdrTotalPhones.textContent = data.phones_count.toLocaleString();

      if (data.active_jobs > 0) {
        elements.activeJobsBadge.textContent = data.active_jobs;
        elements.activeJobsBadge.style.display = "inline-block";
        elements.hdrEngineStatus.textContent = `${data.active_jobs} Active Scraping`;
      } else {
        elements.activeJobsBadge.style.display = "none";
        elements.hdrEngineStatus.textContent = "Standby Ready";
      }
    } catch (err) {
      console.warn("Failed to fetch metrics:", err);
    }
  }

  // -------------------------------------------------------------------------
  // LAUNCHPAD
  // -------------------------------------------------------------------------
  function setupLaunchpad() {
    elements.presetChips.forEach(chip => {
      chip.addEventListener("click", () => {
        elements.inputLocation.value = chip.dataset.loc;
        elements.inputLocation.focus();
      });
    });

    elements.formNewJob.addEventListener("submit", async (e) => {
      e.preventDefault();
      const location = elements.inputLocation.value.trim();
      if (!location) return;

      const totalPages = parseInt(elements.inputTotalPages.value) || 25;
      const antiBot = elements.selectJobAntibot.value || null;
      const delayMin = parseFloat(elements.inputDelayMin.value) || null;
      const delayMax = parseFloat(elements.inputDelayMax.value) || null;

      elements.btnStartScraping.disabled = true;
      elements.btnStartScraping.querySelector(".btn-spinner").style.display = "inline-block";

      try {
        const res = await fetch("/api/jobs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            location: location,
            total_pages: totalPages,
            anti_bot_mode: antiBot,
            delay_min: delayMin,
            delay_max: delayMax
          })
        });

        if (!res.ok) {
          const errData = await res.json();
          throw new Error(errData.detail || "Failed to create job");
        }

        const job = await res.json();
        showToast(`Job launched for ${location}!`, "success");

        // Clear input and switch to Monitor tab
        elements.inputLocation.value = "";
        switchTab("tab-monitor");
        await fetchJobs();
        selectJob(job.id);

      } catch (err) {
        showToast(`Error: ${err.message}`, "error");
      } finally {
        elements.btnStartScraping.disabled = false;
        elements.btnStartScraping.querySelector(".btn-spinner").style.display = "none";
      }
    });
  }

  // -------------------------------------------------------------------------
  // MONITOR & JOBS
  // -------------------------------------------------------------------------
  async function fetchJobs(updateSelection = true) {
    try {
      const res = await fetch("/api/jobs");
      if (!res.ok) return;
      state.jobs = await res.json();
      renderJobsList();

      if (updateSelection && !state.selectedJobId && state.jobs.length > 0) {
        selectJob(state.jobs[0].id);
      }
    } catch (err) {
      console.warn("Failed to fetch jobs:", err);
    }
  }

  function renderJobsList() {
    if (state.jobs.length === 0) {
      elements.jobsListContainer.innerHTML = `<div class="empty-state">No scrape jobs yet. Start one in Launchpad!</div>`;
      return;
    }

    elements.jobsListContainer.innerHTML = state.jobs.map(j => {
      const isSelected = j.id === state.selectedJobId;
      const statusClass = `status-${j.status}`;
      return `
        <div class="job-item-card ${isSelected ? 'active' : ''}" data-job-id="${j.id}">
          <div class="job-item-top">
            <span class="job-item-title">${escapeHtml(j.target_location)}</span>
            <span class="status-badge ${statusClass}">${j.status.toUpperCase()}</span>
          </div>
          <div class="job-item-stats">
            <span>Pg ${j.current_page}/${j.total_pages}</span>
            <span>${j.scraped_count} leads</span>
            <span>${j.percent}%</span>
          </div>
          <div class="progress-bar-container" style="margin: 0; height: 4px;">
            <div class="progress-bar-fill" style="width: ${j.percent}%;"></div>
          </div>
        </div>
      `;
    }).join("");

    // Attach click handlers
    elements.jobsListContainer.querySelectorAll(".job-item-card").forEach(el => {
      el.addEventListener("click", () => {
        selectJob(el.dataset.jobId);
      });
    });
  }

  function selectJob(jobId) {
    state.selectedJobId = jobId;
    renderJobsList();

    const job = state.jobs.find(j => j.id === jobId);
    if (!job) return;

    elements.activeJobCard.style.display = "block";
    elements.jobTargetTitle.textContent = job.target_location;
    elements.jobZillowLink.textContent = job.zillow_url;
    elements.jobZillowLink.href = job.zillow_url;

    elements.jobStatusBadge.textContent = job.status.toUpperCase();
    elements.jobStatusBadge.className = `status-badge status-${job.status}`;

    elements.btnJobDownloadCsv.href = `/api/jobs/${job.id}/export/csv`;
    elements.btnJobDownloadExcel.href = `/api/jobs/${job.id}/export/excel`;

    updateActiveJobProgress(job);

    // Toggle Pause/Resume buttons
    if (job.status === "paused") {
      elements.btnJobPause.style.display = "none";
      elements.btnJobResume.style.display = "inline-flex";
    } else {
      elements.btnJobPause.style.display = "inline-flex";
      elements.btnJobResume.style.display = "none";
    }

    // Connect SSE Stream
    connectJobStream(jobId);
  }

  function updateActiveJobProgress(job) {
    const totalFound = job.total_found || 0;
    const scraped = job.scraped_count || 0;
    const percent = totalFound > 0 ? Math.round((scraped / totalFound) * 100) : 0;

    elements.jobProgressBar.style.width = `${percent}%`;
    elements.jobProgressPercent.textContent = `${percent}%`;
    elements.jobProgressPageText.textContent = `Page ${job.current_page} of ${job.total_pages}`;
    elements.jobProgressCountText.textContent = `${scraped} / ${totalFound} Leads Scraped`;
    elements.jobProgressErrorText.textContent = `${job.error_count || 0} Errors`;
  }

  function connectJobStream(jobId) {
    if (state.eventSource) {
      state.eventSource.close();
    }

    elements.terminalLogs.innerHTML = "";
    appendLogLine("INFO", `Connecting live stream for Job ID: ${jobId}...`);

    state.eventSource = new EventSource(`/api/jobs/${jobId}/stream`);

    state.eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.job) {
          updateActiveJobProgress(data.job);
          elements.jobStatusBadge.textContent = data.job.status.toUpperCase();
          elements.jobStatusBadge.className = `status-badge status-${data.job.status}`;
        }
        if (data.logs && data.logs.length > 0) {
          data.logs.forEach(l => appendLogLine(l.level, l.message));
        }
      } catch (err) {
        console.warn("SSE parse error:", err);
      }
    };

    state.eventSource.onerror = (err) => {
      console.warn("SSE connection error", err);
    };
  }

  function appendLogLine(level, message) {
    const line = document.createElement("div");
    const lowerLevel = (level || "info").toLowerCase();
    line.className = `log-line log-${lowerLevel}`;

    const timestamp = new Date().toLocaleTimeString();
    line.innerHTML = `<span style="color: #64748b;">[${timestamp}]</span> <strong>[${level}]</strong> ${escapeHtml(message)}`;

    elements.terminalLogs.appendChild(line);

    if (state.autoScroll) {
      elements.terminalLogs.scrollTop = elements.terminalLogs.scrollHeight;
    }
  }

  function setupMonitorControls() {
    elements.btnRefreshJobs.addEventListener("click", () => fetchJobs());

    elements.chkAutoScroll.addEventListener("change", (e) => {
      state.autoScroll = e.target.checked;
    });

    elements.btnClearLogs.addEventListener("click", () => {
      elements.terminalLogs.innerHTML = `<div class="log-line log-info">[SYSTEM] Console cleared.</div>`;
    });

    elements.btnJobPause.addEventListener("click", async () => {
      if (!state.selectedJobId) return;
      await fetch(`/api/jobs/${state.selectedJobId}/pause`, { method: "POST" });
      showToast("Job paused.", "info");
      fetchJobs();
    });

    elements.btnJobResume.addEventListener("click", async () => {
      if (!state.selectedJobId) return;
      await fetch(`/api/jobs/${state.selectedJobId}/resume`, { method: "POST" });
      showToast("Job resumed.", "success");
      fetchJobs();
    });

    elements.btnJobCancel.addEventListener("click", async () => {
      if (!state.selectedJobId) return;
      if (!confirm("Are you sure you want to cancel this scraping job?")) return;
      await fetch(`/api/jobs/${state.selectedJobId}/cancel`, { method: "POST" });
      showToast("Job cancelled.", "info");
      fetchJobs();
    });
  }

  // -------------------------------------------------------------------------
  // LEADS SPREADSHEET TABLE
  // -------------------------------------------------------------------------
  async function fetchLeads() {
    const search = elements.leadsSearchInput.value.trim();
    const hasEmail = elements.filterHasEmail.checked;
    const hasPhone = elements.filterHasPhone.checked;

    let url = `/api/leads?page=${state.leadsPage}&limit=${state.leadsLimit}`;
    if (search) url += `&search=${encodeURIComponent(search)}`;
    if (hasEmail) url += `&has_email=true`;
    if (hasPhone) url += `&has_phone=true`;

    try {
      const res = await fetch(url);
      if (!res.ok) return;
      const data = await res.json();
      state.leads = data.leads || [];
      state.leadsTotal = data.total || 0;
      state.leadsTotalPages = data.total_pages || 1;

      renderLeadsTable();
      updateTablePagination();
    } catch (err) {
      console.warn("Failed to fetch leads:", err);
    }
  }

  function renderLeadsTable() {
    if (state.leads.length === 0) {
      elements.leadsTableBody.innerHTML = `
        <tr>
          <td colspan="10" class="empty-table-cell">No leads match the filters. Try another search or launch a new job!</td>
        </tr>
      `;
      return;
    }

    elements.leadsTableBody.innerHTML = state.leads.map(l => {
      const phone = l.primary_phone || l.phone_cell || l.phone_business || "";
      const email = l.email || "";
      const rating = l.rating ? `⭐ ${l.rating} (${l.review_count || 0})` : "No reviews";
      const photoSrc = l.photo_url || "https://www.zillowstatic.com/static/images/blank_user.svg";

      return `
        <tr data-lead-id="${l.id}">
          <td><input type="checkbox" class="lead-checkbox" data-id="${l.id}"></td>
          <td>
            <div class="agent-profile-cell">
              <img src="${escapeHtml(photoSrc)}" alt="" class="agent-avatar" onerror="this.src='https://www.zillowstatic.com/static/images/blank_user.svg'">
              <div>
                <div class="agent-name-text">${escapeHtml(l.name)}</div>
                <div style="font-size: 11px; color: var(--text-muted);">${escapeHtml(l.city || "")} ${escapeHtml(l.state || "")}</div>
              </div>
            </div>
          </td>
          <td><strong>${escapeHtml(l.business_name || "Independent")}</strong></td>
          <td>
            ${phone ? `
              <div style="display:flex; align-items:center; gap:6px;">
                <a href="tel:${escapeHtml(phone)}" style="color:var(--accent-indigo); text-decoration:none; font-family:var(--font-mono); font-size:12px;">${escapeHtml(phone)}</a>
                <button class="btn-ghost btn-xs btn-copy-inline" data-copy="${escapeHtml(phone)}" title="Copy Phone">📋</button>
              </div>
            ` : '<span style="color:var(--text-muted); font-size:12px;">N/A</span>'}
          </td>
          <td>
            ${email ? `
              <div style="display:flex; align-items:center; gap:6px;">
                <a href="mailto:${escapeHtml(email)}" style="color:var(--accent-emerald); text-decoration:none; font-size:12px;">${escapeHtml(email)}</a>
                <button class="btn-ghost btn-xs btn-copy-inline" data-copy="${escapeHtml(email)}" title="Copy Email">📋</button>
              </div>
            ` : '<span style="color:var(--text-muted); font-size:12px;">Not listed</span>'}
          </td>
          <td style="max-width: 220px; font-size: 12px; color: var(--text-muted);">${escapeHtml(l.address || "N/A")}</td>
          <td><span class="rating-badge">${rating}</span></td>
          <td>
            ${l.website_url ? `<a href="${escapeHtml(l.website_url)}" target="_blank" class="link-external">Visit ↗</a>` : '-'}
          </td>
          <td>
            <a href="${escapeHtml(l.profile_url)}" target="_blank" class="link-external">Profile ↗</a>
          </td>
          <td>
            <button class="btn btn-ghost btn-xs btn-copy-lead-row" data-id="${l.id}" title="Copy Single Row">Copy</button>
          </td>
        </tr>
      `;
    }).join("");

    // Inline copy buttons
    elements.leadsTableBody.querySelectorAll(".btn-copy-inline").forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        copyToClipboard(btn.dataset.copy, "Copied to clipboard!");
      });
    });

    // Row copy buttons
    elements.leadsTableBody.querySelectorAll(".btn-copy-lead-row").forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const leadId = parseInt(btn.dataset.id);
        const item = state.leads.find(x => x.id === leadId);
        if (item) {
          const tsv = [
            item.name, item.business_name, item.primary_phone, item.email,
            item.address, item.city, item.state, item.rating, item.review_count, item.profile_url
          ].join("\t");
          copyToClipboard(tsv, `Copied ${item.name} for Google Sheets!`);
        }
      });
    });
  }

  function updateTablePagination() {
    const start = state.leadsTotal === 0 ? 0 : (state.leadsPage - 1) * state.leadsLimit + 1;
    const end = Math.min(state.leadsPage * state.leadsLimit, state.leadsTotal);
    elements.tableStatsText.textContent = `Showing ${start} - ${end} of ${state.leadsTotal} leads`;
    elements.pageIndicatorText.textContent = `Page ${state.leadsPage} of ${state.leadsTotalPages}`;

    elements.btnPrevPage.disabled = state.leadsPage <= 1;
    elements.btnNextPage.disabled = state.leadsPage >= state.leadsTotalPages;
  }

  function setupLeadsTable() {
    // Search with debounce
    let debounceTimer;
    elements.leadsSearchInput.addEventListener("input", () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        state.leadsPage = 1;
        fetchLeads();
      }, 300);
    });

    elements.filterHasEmail.addEventListener("change", () => {
      state.leadsPage = 1;
      fetchLeads();
    });

    elements.filterHasPhone.addEventListener("change", () => {
      state.leadsPage = 1;
      fetchLeads();
    });

    elements.btnPrevPage.addEventListener("click", () => {
      if (state.leadsPage > 1) {
        state.leadsPage--;
        fetchLeads();
      }
    });

    elements.btnNextPage.addEventListener("click", () => {
      if (state.leadsPage < state.leadsTotalPages) {
        state.leadsPage++;
        fetchLeads();
      }
    });

    // Select All Checkbox
    elements.chkSelectAllLeads.addEventListener("change", (e) => {
      const isChecked = e.target.checked;
      elements.leadsTableBody.querySelectorAll(".lead-checkbox").forEach(cb => {
        cb.checked = isChecked;
      });
    });

    // Export All CSV
    elements.btnExportAllCsv.addEventListener("click", () => {
      window.location.href = "/api/leads/export/csv";
    });

    // 1-Click Copy for Google Sheets (TSV formatted)
    elements.btnCopyTsv.addEventListener("click", () => copySelectedOrAllLeadsTsv());
  }

  function copySelectedOrAllLeadsTsv() {
    const selectedBoxes = elements.leadsTableBody.querySelectorAll(".lead-checkbox:checked");
    let targetLeads = [];

    if (selectedBoxes.length > 0) {
      const selectedIds = Array.from(selectedBoxes).map(cb => parseInt(cb.dataset.id));
      targetLeads = state.leads.filter(l => selectedIds.includes(l.id));
    } else {
      targetLeads = state.leads;
    }

    if (targetLeads.length === 0) {
      showToast("No leads available to copy.", "error");
      return;
    }

    const headers = ["Name", "Agency / Company", "Phone", "Email", "Address", "City", "State", "Rating", "Reviews", "Website", "Zillow Profile"];
    const rows = [headers.join("\t")];

    targetLeads.forEach(l => {
      rows.push([
        l.name || "",
        l.business_name || "",
        l.primary_phone || "",
        l.email || "",
        l.address || "",
        l.city || "",
        l.state || "",
        l.rating || "",
        l.review_count || 0,
        l.website_url || "",
        l.profile_url || ""
      ].join("\t"));
    });

    const fullTsv = rows.join("\n");
    copyToClipboard(fullTsv, `✅ Copied ${targetLeads.length} leads! Press Cmd+V in Google Sheets.`);
  }

  // -------------------------------------------------------------------------
  // PROXY & ANTI-BOT SETTINGS
  // -------------------------------------------------------------------------
  async function loadSettings() {
    try {
      const res = await fetch("/api/settings");
      if (!res.ok) return;
      const s = await res.json();

      const mode = s.anti_bot_mode || "stealth";
      const radio = document.querySelector(`input[name="anti_bot_mode"][value="${mode}"]`);
      if (radio) radio.checked = true;

      elements.inputScraperapiKey.value = s.scraperapi_key || "";
      elements.inputZenrowsKey.value = s.zenrows_key || "";
      elements.textareaCustomProxies.value = s.custom_proxies || "";
      elements.inputRotateEvery.value = s.rotate_proxy_every || "3";
      elements.settingsDelayMin.value = s.delay_min || "1.5";
      elements.settingsDelayMax.value = s.delay_max || "3.5";
      elements.settingsMaxRetries.value = s.max_retries || "3";

      updateProxyInputVisibility(mode);
    } catch (err) {
      console.warn("Failed to load settings:", err);
    }
  }

  function updateProxyInputVisibility(mode) {
    document.getElementById("group-scraperapi-key").style.display = (mode === "scraperapi") ? "flex" : "none";
    document.getElementById("group-zenrows-key").style.display = (mode === "zenrows") ? "flex" : "none";
    document.getElementById("group-custom-proxies").style.display = (mode === "custom_pool") ? "flex" : "none";
  }

  function setupProxySettings() {
    elements.radioAntiBotModes.forEach(radio => {
      radio.addEventListener("change", (e) => {
        updateProxyInputVisibility(e.target.value);
      });
    });

    elements.formProxySettings.addEventListener("submit", async (e) => {
      e.preventDefault();
      const selectedMode = document.querySelector('input[name="anti_bot_mode"]:checked')?.value || "stealth";

      const payload = {
        anti_bot_mode: selectedMode,
        scraperapi_key: elements.inputScraperapiKey.value.trim(),
        zenrows_key: elements.inputZenrowsKey.value.trim(),
        custom_proxies: elements.textareaCustomProxies.value.trim(),
        rotate_proxy_every: elements.inputRotateEvery.value,
        delay_min: elements.settingsDelayMin.value,
        delay_max: elements.settingsDelayMax.value,
        max_retries: elements.settingsMaxRetries.value
      };

      try {
        const res = await fetch("/api/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        if (res.ok) {
          showToast("Proxy and anti-bot settings saved!", "success");
        }
      } catch (err) {
        showToast(`Save failed: ${err.message}`, "error");
      }
    });

    elements.btnTestProxy.addEventListener("click", async () => {
      elements.btnTestProxy.disabled = true;
      elements.diagIpVal.textContent = "Testing connection...";
      elements.diagLatencyVal.textContent = "--";

      try {
        const res = await fetch("/api/proxies/test", { method: "POST" });
        const result = await res.json();
        if (result.success) {
          elements.diagEngineVal.textContent = result.engine_label || result.mode;
          elements.diagIpVal.textContent = result.detected_ip;
          elements.diagLatencyVal.textContent = `${result.latency_ms} ms`;
          showToast(`Connection verified via ${result.detected_ip}!`, "success");
        } else {
          elements.diagIpVal.textContent = "Test Failed";
          elements.diagLatencyVal.textContent = "--";
          showToast(result.message || "Proxy test failed", "error");
        }
      } catch (err) {
        elements.diagIpVal.textContent = "Error";
        showToast(`Test error: ${err.message}`, "error");
      } finally {
        elements.btnTestProxy.disabled = false;
      }
    });
  }

  // -------------------------------------------------------------------------
  // GOOGLE SHEETS MODAL
  // -------------------------------------------------------------------------
  function setupSheetsModal() {
    const formula = `=IMPORTDATA("${window.location.protocol}//${window.location.host}/api/leads/export/csv")`;
    elements.sheetsFormulaInput.value = formula;

    const openModal = () => {
      elements.sheetsFormulaInput.value = `=IMPORTDATA("${window.location.protocol}//${window.location.host}/api/leads/export/csv")`;
      elements.sheetsModal.style.display = "flex";
    };

    const closeModal = () => {
      elements.sheetsModal.style.display = "none";
    };

    elements.btnOpenSheetsModal.addEventListener("click", openModal);
    elements.btnOpenGoogleSheetsDialog.addEventListener("click", openModal);
    elements.btnCloseSheetsModal.addEventListener("click", closeModal);
    elements.btnDoneSheetsModal.addEventListener("click", closeModal);

    elements.btnCopySheetsFormula.addEventListener("click", () => {
      copyToClipboard(elements.sheetsFormulaInput.value, "Copied =IMPORTDATA formula for Google Sheets!");
    });

    elements.btnModalCopyTsv.addEventListener("click", () => {
      copySelectedOrAllLeadsTsv();
    });
  }

  // -------------------------------------------------------------------------
  // UTILITIES
  // -------------------------------------------------------------------------
  function copyToClipboard(text, successMessage) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(() => {
        showToast(successMessage, "success");
      }).catch(() => fallbackCopy(text, successMessage));
    } else {
      fallbackCopy(text, successMessage);
    }
  }

  function fallbackCopy(text, successMessage) {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
    showToast(successMessage, "success");
  }

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // Start application
  init();
});
