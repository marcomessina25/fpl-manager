// FPL Manager Pro — Interactive Dashboard Client Controller

const state = {
  appMode: "live", // "live" | "historical"
  activeTeamId: null,
  teams: [],
  currentSquad: null,
  currentLineup: null,
  activeGameweek: 1,
  selectedGameweek: null,
  lineupMode: "auto",
  subbingPlayer: null,
  allLeaguePlayers: [],
  overviewPastGw: null,
  overviewFutureGw: null,
  overviewData: null,
};

// Toast notification helper
function showToast(message, isError = false) {
  const container = document.getElementById("toast-container");
  if (!container) return;
  const toast = document.createElement("div");
  toast.className = `toast ${isError ? "toast-error" : ""}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

// HTML Escaping Helper
function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// Simple Markdown Formatter Helper
function formatMarkdown(str) {
  if (!str) return "";
  let html = escapeHtml(str);
  html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
  html = html.replace(/`([^`]+)`/g, '<code style="background: rgba(255,255,255,0.1); padding: 1px 4px; border-radius: 3px;">$1</code>');
  html = html.replace(/^### (.*$)/gim, '<h4 style="margin: 0.8rem 0 0.3rem 0; font-size: 0.95rem; color: #fbbf24;">$1</h4>');
  html = html.replace(/^## (.*$)/gim, '<h3 style="margin: 1rem 0 0.4rem 0; font-size: 1.05rem;">$1</h3>');
  html = html.replace(/^# (.*$)/gim, '<h2 style="margin: 1.2rem 0 0.5rem 0; font-size: 1.15rem;">$1</h2>');
  html = html.replace(/^- (.*$)/gim, '• $1<br>');
  html = html.replace(/\n\n/g, '<br><br>');
  html = html.replace(/\n/g, '<br>');
  return html;
}

// API Request Wrapper
async function api(endpoint, options = {}) {
  try {
    const res = await fetch(endpoint, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || `HTTP ${res.status}`);
    }
    return data;
  } catch (err) {
    console.error(`API Error on ${endpoint}:`, err);
    throw err;
  }
}

// Modality Switching: Live Manager vs Historical Time Machine
function initModality() {
  const btnLive = document.getElementById("btn-mode-live");
  const btnHist = document.getElementById("btn-mode-historical");
  const liveSwitcher = document.getElementById("live-switcher-bar");
  const histSwitcher = document.getElementById("hist-switcher-bar");
  const liveHud = document.getElementById("live-hud-bar");
  const histHud = document.getElementById("hist-hud-bar");

  // Pitch wrappers
  const livePitchWrap = document.getElementById("live-pitch-wrapper");
  const histPitchWrap = document.getElementById("hist-pitch-wrapper");

  // Transfers wrappers
  const liveTxWrap = document.getElementById("live-transfers-wrapper");
  const histTxWrap = document.getElementById("hist-transfers-wrapper");

  // Evaluation wrappers
  const liveEvalWrap = document.getElementById("live-evaluation-wrapper");
  const histEvalWrap = document.getElementById("hist-evaluation-wrapper");

  const liveOnlyTabs = document.querySelectorAll(".mode-live-only");

  const setMode = async (mode) => {
    state.appMode = mode;

    if (mode === "live") {
      if (btnLive) btnLive.classList.add("active");
      if (btnHist) btnHist.classList.remove("active");

      if (liveSwitcher) liveSwitcher.style.display = "flex";
      if (histSwitcher) histSwitcher.style.display = "none";
      if (liveHud) liveHud.style.display = "flex";
      if (histHud) histHud.style.display = "none";

      if (livePitchWrap) livePitchWrap.style.display = "flex";
      if (histPitchWrap) histPitchWrap.style.display = "none";

      if (liveTxWrap) liveTxWrap.style.display = "block";
      if (histTxWrap) histTxWrap.style.display = "none";

      if (liveEvalWrap) liveEvalWrap.style.display = "block";
      if (histEvalWrap) histEvalWrap.style.display = "none";

      liveOnlyTabs.forEach(tab => { tab.style.display = ""; });

      await loadOverview();
      await refreshActiveTeamData();
      const activeTabLive = document.querySelector('.tabs-nav .tab-btn.active');
      if (activeTabLive && activeTabLive.dataset.tab === "strategic") {
        await loadStrategicStudio();
      }
    } else {
      if (btnHist) btnHist.classList.add("active");
      if (btnLive) btnLive.classList.remove("active");

      if (liveSwitcher) liveSwitcher.style.display = "none";
      if (histSwitcher) histSwitcher.style.display = "flex";
      if (liveHud) liveHud.style.display = "none";
      if (histHud) histHud.style.display = "flex";

      if (livePitchWrap) livePitchWrap.style.display = "none";
      if (histPitchWrap) histPitchWrap.style.display = "block";

      if (liveTxWrap) liveTxWrap.style.display = "none";
      if (histTxWrap) histTxWrap.style.display = "block";

      if (liveEvalWrap) liveEvalWrap.style.display = "none";
      if (histEvalWrap) histEvalWrap.style.display = "block";

      liveOnlyTabs.forEach(tab => {
        tab.style.display = "none";
        if (tab.classList.contains("active")) {
          // Switch to overview or pitch tab if user was on a live-only tab
          const overviewBtn = document.querySelector('.tabs-nav .tab-btn[data-tab="overview"]');
          if (overviewBtn) overviewBtn.click();
        }
      });

      await loadHistoricalSimulationsList();
      await loadOverview();
      const activeTabHist = document.querySelector('.tabs-nav .tab-btn.active');
      if (activeTabHist && activeTabHist.dataset.tab === "strategic") {
        await loadStrategicStudio();
      }
    }
  };

  if (btnLive) {
    btnLive.addEventListener("click", () => setMode("live"));
  }
  if (btnHist) {
    btnHist.addEventListener("click", () => setMode("historical"));
  }

  // Top run matchday button in historical HUD
  const btnTopRun = document.getElementById("btn-hist-run-gw-top");
  if (btnTopRun) {
    btnTopRun.addEventListener("click", async () => {
      const btnRun = document.getElementById("btn-hist-run-gw");
      if (btnRun) {
        btnRun.click();
      } else if (histState.sessionId) {
        try {
          btnTopRun.disabled = true;
          btnTopRun.textContent = "Resolving...";
          const res = await api(`/api/historical/simulations/${histState.sessionId}/run-gw`, {
            method: "POST",
            body: JSON.stringify({}),
          });
          showHistoricalResolutionModal(res.resolution);
          await loadHistoricalSession(histState.sessionId);
          await loadOverview();
        } catch (err) {
          showToast(`Failed to run matchday: ${err.message}`, true);
        } finally {
          btnTopRun.disabled = false;
          btnTopRun.textContent = "▶ Run Matchday";
        }
      } else {
        showToast("Please select or create a historical simulation session first.", true);
      }
    });
  }

  // Header "+ New Sim" button
  const btnOpenCreateSim = document.getElementById("btn-open-create-sim");
  if (btnOpenCreateSim) {
    btnOpenCreateSim.addEventListener("click", () => {
      openCreateSimulationModal();
    });
  }

  // Header "Delete Sim" button
  const btnDeleteSim = document.getElementById("btn-delete-sim");
  if (btnDeleteSim) {
    btnDeleteSim.addEventListener("click", async () => {
      if (!histState.sessionId) {
        showToast("No simulation selected to delete.", true);
        return;
      }
      if (!confirm(`Are you sure you want to delete simulation '${histState.sessionId}'?`)) return;
      try {
        await api(`/api/historical/simulations/${histState.sessionId}`, { method: "DELETE" });
        showToast(`Deleted simulation '${histState.sessionId}'`);
        histState.sessionId = null;
        histState.sessionData = null;
        await loadHistoricalSimulationsList();
        await loadOverview();
      } catch (err) {
        showToast(`Failed to delete simulation: ${err.message}`, true);
      }
    });
  }
}

// Unified Overview Tab Controller (Live & Historical)
async function loadOverview() {
  const isHist = state.appMode === "historical";
  const titleEl = document.getElementById("overview-title");
  const subEl = document.getElementById("overview-subtitle");
  const modeBadge = document.getElementById("overview-mode-badge");
  const gwBadge = document.getElementById("overview-gw-badge");
  const countEl = document.getElementById("overview-standings-count");
  const resLabel = document.getElementById("overview-results-gw-label");

  if (isHist) {
    if (titleEl) titleEl.textContent = `🏆 Premier League Overview & Standings (${histState.season})`;
    if (subEl) subEl.textContent = `Point-in-time official table for Season ${histState.season} up to GW ${histState.gameweek}. Zero future results revealed.`;
    if (modeBadge) {
      modeBadge.textContent = `Time Machine (${histState.season})`;
      modeBadge.className = "badge badge-secondary";
    }
    if (gwBadge) gwBadge.textContent = `Simulated GW ${histState.gameweek}`;
  } else {
    if (titleEl) titleEl.textContent = "🏆 Premier League Overview & Standings";
    if (subEl) subEl.textContent = "Point-in-time official table, completed match scores, and upcoming fixtures (zero-leakage blind replay).";
    if (modeBadge) {
      modeBadge.textContent = "2026/27 Live";
      modeBadge.className = "badge badge-accent";
    }
    if (gwBadge) gwBadge.textContent = `GW ${state.activeGameweek || 1}`;
  }

  const currentGw = isHist ? (histState.gameweek || 1) : (state.activeGameweek || 1);
  const pastGw = isHist ? histState.overviewPastGw : state.overviewPastGw;
  const futureGw = isHist ? histState.overviewFutureGw : state.overviewFutureGw;

  try {
    let endpoint = isHist
      ? `/api/historical/overview?season=${encodeURIComponent(histState.season)}&gameweek=${currentGw}`
      : `/api/overview?gameweek=${currentGw}`;

    if (pastGw !== null && pastGw !== undefined) {
      endpoint += `&past_gw=${pastGw}`;
    }
    if (futureGw !== null && futureGw !== undefined) {
      endpoint += `&future_gw=${futureGw}`;
    }

    const data = await api(endpoint);

    // Save overview data
    if (isHist) {
      histState.overviewData = data;
    } else {
      state.overviewData = data;
    }

    // Render Standings
    renderOverviewStandings(data.standings || []);
    if (countEl) countEl.textContent = `${(data.standings || []).length} Clubs`;

    // Render Past Results with Navigation
    renderOverviewPastResults(data);
    if (resLabel) {
      if (data.past_gw_viewed) {
        resLabel.textContent = `Gameweek ${data.past_gw_viewed}`;
      } else {
        resLabel.textContent = isHist ? `GW 1 – GW ${Math.max(1, currentGw - 1)}` : `Completed Matches`;
      }
    }

    // Render Upcoming Fixtures with Navigation
    renderOverviewUpcomingFixtures(data);
  } catch (err) {
    console.error("Failed to load overview data:", err);
    showToast(`Failed to load overview: ${err.message}`, true);
  }
}

function renderOverviewStandings(standings) {
  const tbody = document.getElementById("overview-standings-body");
  if (!tbody) return;

  if (!standings || standings.length === 0) {
    tbody.innerHTML = `<tr><td colspan="11" class="text-center text-muted" style="padding: 1.5rem;">No standings data available.</td></tr>`;
    return;
  }

  tbody.innerHTML = standings.map(s => {
    let posClass = "";
    if (s.position <= 4) posClass = "pos-ucl";
    else if (s.position === 5) posClass = "pos-uel";
    else if (s.position >= 18) posClass = "pos-rel";

    const formHtml = (s.form || []).map(f => {
      const cls = f === "W" ? "form-w" : (f === "D" ? "form-d" : "form-l");
      return `<span class="form-badge ${cls}">${f}</span>`;
    }).join("");

    const gdFormatted = s.goal_difference > 0 ? `+${s.goal_difference}` : s.goal_difference;

    return `
      <tr class="${posClass}">
        <td style="text-align: center; font-weight: bold; color: #94a3b8;">${s.position}</td>
        <td style="font-weight: 600;">
          <span>${escapeHtml(s.name)}</span>
          <span style="font-size: 0.72rem; color: #64748b; margin-left: 4px;">(${escapeHtml(s.short_name)})</span>
        </td>
        <td style="text-align: center;">${s.played}</td>
        <td style="text-align: center;">${s.won}</td>
        <td style="text-align: center;">${s.drawn}</td>
        <td style="text-align: center;">${s.lost}</td>
        <td style="text-align: center;">${s.goals_for}</td>
        <td style="text-align: center;">${s.goals_against}</td>
        <td style="text-align: center; color: ${s.goal_difference > 0 ? '#34d399' : (s.goal_difference < 0 ? '#f87171' : '#94a3b8')};">${gdFormatted}</td>
        <td style="text-align: center; font-weight: bold; font-size: 0.95rem; color: #fbbf24;">${s.points}</td>
        <td style="text-align: center;"><div class="form-badge-strip">${formHtml || "-"}</div></td>
      </tr>
    `;
  }).join("");
}

function renderOverviewPastResults(overviewData) {
  const list = document.getElementById("overview-past-results-list");
  const select = document.getElementById("overview-results-gw-select");
  const btnPrev = document.getElementById("btn-results-prev-gw");
  const btnNext = document.getElementById("btn-results-next-gw");
  if (!list) return;

  const results = overviewData?.past_results || [];
  const availableGws = overviewData?.available_past_gws || [];
  const selectedGw = overviewData?.past_gw_viewed ?? "all";

  // Update dropdown options
  if (select) {
    let optionsHtml = `<option value="all">All Past GWs</option>`;
    availableGws.forEach(gw => {
      const isSel = (selectedGw !== "all" && Number(selectedGw) === Number(gw)) ? "selected" : "";
      optionsHtml += `<option value="${gw}" ${isSel}>GW ${gw}</option>`;
    });
    select.innerHTML = optionsHtml;
    select.value = selectedGw.toString();

    // Attach change handler once
    if (!select._hasChangeHandler) {
      select._hasChangeHandler = true;
      select.addEventListener("change", async (e) => {
        const val = e.target.value === "all" ? null : parseInt(e.target.value, 10);
        if (state.appMode === "historical") {
          histState.overviewPastGw = val;
        } else {
          state.overviewPastGw = val;
        }
        await loadOverview();
      });
    }
  }

  // Update Prev / Next buttons
  if (btnPrev && !btnPrev._hasClickHandler) {
    btnPrev._hasClickHandler = true;
    btnPrev.addEventListener("click", async () => {
      const isHist = state.appMode === "historical";
      const gws = (isHist ? histState.overviewData : state.overviewData)?.available_past_gws || [];
      if (gws.length === 0) return;
      const current = isHist ? histState.overviewPastGw : state.overviewPastGw;
      let nextGw = gws[0];
      if (current === null || current === undefined) {
        nextGw = gws[gws.length - 1]; // jump to most recent past GW
      } else {
        const idx = gws.indexOf(Number(current));
        if (idx > 0) nextGw = gws[idx - 1];
        else nextGw = gws[0];
      }
      if (isHist) histState.overviewPastGw = nextGw;
      else state.overviewPastGw = nextGw;
      await loadOverview();
    });
  }

  if (btnNext && !btnNext._hasClickHandler) {
    btnNext._hasClickHandler = true;
    btnNext.addEventListener("click", async () => {
      const isHist = state.appMode === "historical";
      const gws = (isHist ? histState.overviewData : state.overviewData)?.available_past_gws || [];
      if (gws.length === 0) return;
      const current = isHist ? histState.overviewPastGw : state.overviewPastGw;
      if (current === null || current === undefined) return;
      const idx = gws.indexOf(Number(current));
      if (idx !== -1 && idx < gws.length - 1) {
        const nextGw = gws[idx + 1];
        if (isHist) histState.overviewPastGw = nextGw;
        else state.overviewPastGw = nextGw;
      } else {
        if (isHist) histState.overviewPastGw = null;
        else state.overviewPastGw = null;
      }
      await loadOverview();
    });
  }

  if (!results || results.length === 0) {
    list.innerHTML = `<div class="text-center text-muted" style="padding: 1.5rem;">No previous gameweeks completed yet.</div>`;
    return;
  }

  const sorted = [...results].reverse();
  list.innerHTML = sorted.map(r => {
    const hWin = r.team_h_score > r.team_a_score;
    const aWin = r.team_a_score > r.team_h_score;
    const kickoffFormatted = r.kickoff_time
      ? new Date(r.kickoff_time).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })
      : `GW ${r.event}`;

    return `
      <div class="fixture-row-card">
        <div style="font-size: 0.72rem; color: #64748b; width: 55px;">GW ${r.event}</div>
        <div class="fixture-teams">
          <div class="fixture-team-h" style="color: ${hWin ? '#fff' : '#94a3b8'};">
            ${escapeHtml(r.team_h_name)}
          </div>
          <div class="fixture-score">
            ${r.team_h_score} - ${r.team_a_score}
          </div>
          <div class="fixture-team-a" style="color: ${aWin ? '#fff' : '#94a3b8'};">
            ${escapeHtml(r.team_a_name)}
          </div>
        </div>
        <div style="font-size: 0.72rem; color: #64748b; width: 75px; text-align: right;">${kickoffFormatted}</div>
      </div>
    `;
  }).join("");
}

function renderOverviewUpcomingFixtures(overviewData) {
  const list = document.getElementById("overview-upcoming-fixtures-list");
  const select = document.getElementById("overview-fixtures-gw-select");
  const btnPrev = document.getElementById("btn-fixtures-prev-gw");
  const btnNext = document.getElementById("btn-fixtures-next-gw");
  if (!list) return;

  const upcoming = overviewData?.upcoming_fixtures || [];
  const availableGws = overviewData?.available_future_gws || [];
  const viewedGw = overviewData?.future_gw_viewed || overviewData?.gameweek || 1;

  // Update dropdown options
  if (select) {
    let optionsHtml = "";
    availableGws.forEach(gw => {
      const isSel = Number(gw) === Number(viewedGw) ? "selected" : "";
      optionsHtml += `<option value="${gw}" ${isSel}>GW ${gw}</option>`;
    });
    select.innerHTML = optionsHtml || `<option value="${viewedGw}">GW ${viewedGw}</option>`;
    select.value = viewedGw.toString();

    if (!select._hasChangeHandler) {
      select._hasChangeHandler = true;
      select.addEventListener("change", async (e) => {
        const val = parseInt(e.target.value, 10);
        if (state.appMode === "historical") {
          histState.overviewFutureGw = val;
        } else {
          state.overviewFutureGw = val;
        }
        await loadOverview();
      });
    }
  }

  // Update Prev / Next buttons
  if (btnPrev && !btnPrev._hasClickHandler) {
    btnPrev._hasClickHandler = true;
    btnPrev.addEventListener("click", async () => {
      const isHist = state.appMode === "historical";
      const gws = (isHist ? histState.overviewData : state.overviewData)?.available_future_gws || [];
      if (gws.length === 0) return;
      const current = isHist ? (histState.overviewFutureGw || histState.gameweek) : (state.overviewFutureGw || state.activeGameweek || 1);
      const idx = gws.indexOf(Number(current));
      if (idx > 0) {
        const nextGw = gws[idx - 1];
        if (isHist) histState.overviewFutureGw = nextGw;
        else state.overviewFutureGw = nextGw;
        await loadOverview();
      }
    });
  }

  if (btnNext && !btnNext._hasClickHandler) {
    btnNext._hasClickHandler = true;
    btnNext.addEventListener("click", async () => {
      const isHist = state.appMode === "historical";
      const gws = (isHist ? histState.overviewData : state.overviewData)?.available_future_gws || [];
      if (gws.length === 0) return;
      const current = isHist ? (histState.overviewFutureGw || histState.gameweek) : (state.overviewFutureGw || state.activeGameweek || 1);
      const idx = gws.indexOf(Number(current));
      if (idx !== -1 && idx < gws.length - 1) {
        const nextGw = gws[idx + 1];
        if (isHist) histState.overviewFutureGw = nextGw;
        else state.overviewFutureGw = nextGw;
        await loadOverview();
      }
    });
  }

  if (!upcoming || upcoming.length === 0) {
    list.innerHTML = `<div class="text-center text-muted" style="padding: 1.5rem;">No upcoming fixtures scheduled for GW ${viewedGw}.</div>`;
    return;
  }

  list.innerHTML = upcoming.map(u => {
    const kickoffFormatted = u.kickoff_time
      ? new Date(u.kickoff_time).toLocaleString(undefined, { weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
      : `GW ${u.event}`;

    return `
      <div class="fixture-row-card">
        <div style="font-size: 0.72rem; color: #38bdf8; font-weight: bold; width: 50px;">GW ${u.event}</div>
        <div class="fixture-teams">
          <div class="fixture-team-h">
            ${escapeHtml(u.team_h_name)}
            <span class="fdr-pill fdr-${u.team_h_difficulty}" title="FDR: ${u.team_h_difficulty}">${u.team_h_difficulty}</span>
          </div>
          <div class="fixture-vs">vs</div>
          <div class="fixture-team-a">
            <span class="fdr-pill fdr-${u.team_a_difficulty}" title="FDR: ${u.team_a_difficulty}">${u.team_a_difficulty}</span>
            ${escapeHtml(u.team_a_name)}
          </div>
        </div>
        <div style="font-size: 0.72rem; color: #94a3b8; width: 100px; text-align: right;">${kickoffFormatted}</div>
      </div>
    `;
  }).join("");
}

// Tab Switching
function initTabs() {
  const tabBtns = document.querySelectorAll(".tabs-nav .tab-btn");
  const tabPanes = document.querySelectorAll(".tab-pane");

  tabBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      const target = btn.getAttribute("data-tab");
      tabBtns.forEach(b => b.classList.remove("active"));
      tabPanes.forEach(p => p.classList.remove("active"));
      btn.classList.add("active");
      const targetPane = document.getElementById(`tab-${target}`);
      if (targetPane) targetPane.classList.add("active");

      // Lazy load tab contents when switching
      if (target === "overview") {
        loadOverview();
      }
      if (target === "pitch") {
        if (state.appMode === "historical") {
          if (histState.sessionId) loadHistoricalSession(histState.sessionId);
          else loadHistoricalSimulationsList();
        } else {
          loadLineup();
        }
      }
      if (target === "transfers") {
        if (state.appMode === "historical") {
          if (histState.sessionId) loadHistoricalSession(histState.sessionId);
        }
      }
      if (target === "decisions") {
        loadDecisions();
        loadAllLeaguePlayers();
        if (state.currentSquad && state.currentSquad.players) {
          populateDecisionLoggerSquad(state.currentSquad.players);
        }
      }
      if (target === "strategic") loadStrategicStudio();
      if (target === "chips") loadChipStrategy();
      if (target === "evaluation") {
        if (state.appMode === "historical") {
          renderHistoricalEvaluationSummary();
        } else {
          loadEvaluation();
        }
      }
      if (target === "live") loadLiveMatchday();
      if (target === "advisor") loadAdvisor();
    });
  });

  // Refresh Overview button handler
  const btnRefreshOverview = document.getElementById("btn-refresh-overview");
  if (btnRefreshOverview) {
    btnRefreshOverview.addEventListener("click", () => loadOverview());
  }

  // Subtab switching in transfers
  const subtabBtns = document.querySelectorAll(".subtab-btn");
  const subtabPanes = document.querySelectorAll(".subtab-pane");
  subtabBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      const target = btn.getAttribute("data-subtab");
      subtabBtns.forEach(b => b.classList.remove("active"));
      subtabPanes.forEach(p => p.classList.remove("active"));
      btn.classList.add("active");
      const p = document.getElementById(`subtab-${target}`);
      if (p) p.classList.add("active");
    });
  });
}

// Team Management
async function loadTeams() {
  try {
    const data = await api("/api/teams");
    state.teams = data.teams || [];
    state.activeTeamId = data.active_team_id || "default";

    if (data.version) {
      state.version = data.version;
      const badge = document.getElementById("app-version-badge");
      if (badge) {
        badge.textContent = `v${data.version}`;
      }
    }

    const select = document.getElementById("team-select");
    const copySelect = document.getElementById("new-team-copy");
    select.innerHTML = "";
    copySelect.innerHTML = '<option value="">Current Active Team Squad</option>';

    state.teams.forEach(t => {
      const opt = document.createElement("option");
      opt.value = t.team_id;
      opt.textContent = `${t.name} (${t.team_id})`;
      if (t.team_id === state.activeTeamId) opt.selected = true;
      select.appendChild(opt);

      const copyOpt = document.createElement("option");
      copyOpt.value = t.team_id;
      copyOpt.textContent = t.name;
      copySelect.appendChild(copyOpt);
    });

    const activeObj = state.teams.find(t => t.team_id === state.activeTeamId);
    if (data.current_gameweek) {
      state.currentGameweek = data.current_gameweek;
    }
    if (activeObj && activeObj.gameweek) {
      state.activeGameweek = activeObj.gameweek;
    } else if (data.current_gameweek) {
      state.activeGameweek = data.current_gameweek;
    }

    await refreshActiveTeamData();
  } catch (err) {
    showToast(`Failed to load teams: ${err.message}`, true);
  }
}

async function switchTeam(teamId) {
  try {
    const res = await api("/api/teams/switch", {
      method: "POST",
      body: JSON.stringify({ team_id: teamId }),
    });
    state.activeTeamId = teamId;
    state.selectedGameweek = null;
    state.lineupMode = "auto";
    if (res.gameweek) {
      state.activeGameweek = res.gameweek;
    }
    showToast(`Switched active team to ${res.name}`);
    await refreshActiveTeamData();
  } catch (err) {
    showToast(`Could not switch team: ${err.message}`, true);
  }
}

async function deleteActiveTeam() {
  if (!state.activeTeamId || state.activeTeamId === "default") {
    showToast("Cannot delete default team.", true);
    return;
  }
  if (!confirm(`Are you sure you want to delete team '${state.activeTeamId}'?`)) return;

  try {
    const res = await api("/api/teams/delete", {
      method: "POST",
      body: JSON.stringify({ team_id: state.activeTeamId }),
    });
    showToast(`Deleted team '${res.deleted_team_id}'`);
    await loadTeams();
  } catch (err) {
    showToast(`Failed to delete team: ${err.message}`, true);
  }
}

// Refresh all views for current active team
async function refreshActiveTeamData() {
  await loadSquadHUD();
  await loadLineup(state.activeGameweek);
}

async function loadSquadHUD() {
  try {
    const data = await api(`/api/squad?team=${state.activeTeamId}`);
    state.currentSquad = data;
    const activeObj = state.teams.find(t => t.team_id === state.activeTeamId);
    state.activeGameweek = data.gameweek || (activeObj && activeObj.gameweek) || (data.state && data.state.gameweek) || state.currentGameweek || 4;

    const fin = data.financials || {};
    const st = data.state || {};

    document.getElementById("hud-gw").textContent = `GW${state.activeGameweek}`;
    document.getElementById("hud-bank").textContent = fin.bank_fmt || `£${((fin.bank_tenths || 0) / 10).toFixed(1)}m`;
    document.getElementById("hud-value").textContent = fin.total_team_value_fmt || "£0.0m";
    document.getElementById("hud-ft").textContent = st.free_transfers !== undefined ? st.free_transfers : 1;
    
    // Normalize chips (e.g. 4 unique chips: wildcard, free_hit, bench_boost, triple_captain)
    const rawChips = st.chips_remaining || [];
    const uniqueChips = new Set(rawChips.map(c => c.replace(/_\d+$/, "").replace(/_/g, "")));
    document.getElementById("hud-chips").textContent = uniqueChips.size;

    if (data.players) {
      populateDecisionLoggerSquad(data.players);
    }

    // Prefill Gameweek in decision logger, lineup, chips, and evaluation
    const decGw = document.getElementById("dec-gw");
    if (decGw) decGw.value = state.activeGameweek;
    const lineupGw = document.getElementById("lineup-gw-select");
    if (lineupGw) lineupGw.value = state.activeGameweek;
    const chipStartGw = document.getElementById("chip-start-gw");
    if (chipStartGw) chipStartGw.value = state.activeGameweek;
    const evalGw = document.getElementById("eval-gw");
    if (evalGw && !evalGw.value) evalGw.value = state.activeGameweek;
    const advGw = document.getElementById("adv-gw");
    if (advGw && !advGw.value) advGw.value = state.activeGameweek;
    const liveGw = document.getElementById("live-gw");
    if (liveGw && !liveGw.value) liveGw.value = state.activeGameweek;
  } catch (err) {
    console.error("Could not load squad HUD:", err);
  }
}

// Pitch and Lineup Rendering
async function loadLineup(gw = null, mode = "auto") {
  try {
    const targetGw = gw !== null ? gw : (state.selectedGameweek || state.activeGameweek);
    state.selectedGameweek = targetGw;
    state.lineupMode = mode;
    const url = `/api/lineup?team=${state.activeTeamId}&gameweek=${targetGw}&mode=${mode}`;
    const data = await api(url);
    state.currentLineup = data;
    renderPitch(data);
    await renderLineupGWPills(targetGw);
  } catch (err) {
    showToast(`Failed to load lineup: ${err.message}`, true);
  }
}

// Alias for backwards compatibility
const loadPitchAndLineup = loadLineup;

async function renderLineupGWPills(currentGw) {
  const container = document.getElementById("lineup-gw-pills");
  if (!container) return;

  try {
    const decData = await api(`/api/decisions?team=${state.activeTeamId}`);
    const decisions = decData.decisions || [];
    const decMap = {};
    decisions.forEach(d => { decMap[d.gameweek] = d; });

    const maxGw = Math.max(3, state.activeGameweek || 1, ...decisions.map(d => d.gameweek));
    container.innerHTML = "";

    for (let g = 1; g <= Math.min(38, maxGw + 1); g++) {
      const pill = document.createElement("button");
      pill.className = `gw-pill ${g === currentGw ? "active" : ""}`;
      const dec = decMap[g];

      let badge = "";
      const pts = (dec && dec.actual_points !== null && dec.actual_points !== undefined)
        ? dec.actual_points
        : (state.currentLineup && state.currentLineup.gameweek === g && state.currentLineup.actual_points !== null && state.currentLineup.actual_points !== undefined
            ? state.currentLineup.actual_points
            : null);

      if (pts !== null) {
        badge = `<span class="gw-pill-score">${pts} pts</span>`;
      } else if (dec) {
        badge = `<span class="gw-pill-tag">Logged</span>`;
      } else if (g === state.activeGameweek) {
        badge = `<span class="gw-pill-tag">Active</span>`;
      }

      pill.innerHTML = `<span>GW${g}</span> ${badge}`;
      pill.addEventListener("click", () => {
        state.lineupMode = "auto";
        const gwInput = document.getElementById("lineup-gw-select");
        if (gwInput) gwInput.value = g;
        loadLineup(g, "auto");
      });
      container.appendChild(pill);
    }
  } catch (err) {
    console.error("Failed to render GW pills:", err);
  }
}

function renderPitch(lineup) {
  const gwInput = document.getElementById("lineup-gw-select");
  if (gwInput) gwInput.value = lineup.gameweek;

  const pitchChipSelect = document.getElementById("pitch-chip-select");
  if (pitchChipSelect) {
    if (lineup.chip_played) {
      const chipNorm = String(lineup.chip_played).toLowerCase().replace(/[\s_-]/g, "");
      if (chipNorm.startsWith("wildcard") || chipNorm === "wc") {
        pitchChipSelect.value = "wildcard";
      } else if (chipNorm.startsWith("freehit") || chipNorm === "fh") {
        pitchChipSelect.value = "freehit";
      } else if (chipNorm.startsWith("benchboost") || chipNorm === "bb") {
        pitchChipSelect.value = "benchboost";
      } else if (chipNorm.startsWith("triplecaptain") || chipNorm === "tc") {
        pitchChipSelect.value = "triplecaptain";
      } else {
        pitchChipSelect.value = lineup.chip_played;
      }
    } else {
      pitchChipSelect.value = "";
    }
  }

  const isLogged = !!lineup.is_logged;
  const hasActualScore = lineup.actual_points !== null && lineup.actual_points !== undefined;

  const titleSuffix = isLogged
    ? (hasActualScore ? " · Logged Matchday" : " · Logged Plan")
    : (state.lineupMode === "model" ? " · Model Recommended" : "");
  document.getElementById("lineup-headline").textContent = `Matchday Lineup (GW${lineup.gameweek})${titleSuffix}`;

  const scoreText = hasActualScore
    ? `Actual Score: ${lineup.actual_points} pts | Predicted: ${lineup.projected_points.total_xp.toFixed(1)} xP`
    : `Projected: ${lineup.projected_points.total_xp.toFixed(1)} xP`;
  document.getElementById("lineup-meta").textContent = `Formation: ${lineup.formation} | ${scoreText}`;

  // Matchday Status Banner & Model Toggle
  const bannerEl = document.getElementById("lineup-status-banner");
  const toggleBtn = document.getElementById("btn-toggle-model-view");

  if (bannerEl) {
    if (isLogged) {
      bannerEl.classList.remove("hidden");
      bannerEl.classList.remove("model-view");
      document.getElementById("banner-icon").textContent = "🔒";
      document.getElementById("banner-title").textContent = `Gameweek ${lineup.gameweek} Logged Team State`;

      const ptsStr = hasActualScore ? `<span class="banner-score-highlight">${lineup.actual_points} pts</span>` : "Upcoming";
      const capPtsStr = (lineup.captain && lineup.captain.actual_points !== null && lineup.captain.actual_points !== undefined)
        ? ` · ${lineup.captain.actual_points} pts`
        : "";
      const capNote = lineup.captain_promoted ? ` <span class="badge-promoted-vc">(VC Promoted)</span>` : "";
      const capStr = lineup.captain ? `${lineup.captain.name} (C)${capPtsStr}${capNote}` : "-";
      const movesStr = (lineup.transfers && lineup.transfers.length)
        ? lineup.transfers.map(t => `${t.outgoing_name} ➔ ${t.incoming_name}`).join(", ")
        : "No transfers";
      const chipNorm = (lineup.chip_played || "").toLowerCase();
      const isFreeChip = ["wildcard", "freehit", "free_hit", "wc", "fh"].includes(chipNorm);
      const hitsStr = isFreeChip
        ? " (Hits: 0pt - Free Chip)"
        : (lineup.transfer_hits && lineup.transfer_hits > 0 ? ` (Hits: -${lineup.transfer_hits * 4}pt)` : "");
      const chipStr = lineup.chip_played ? ` · Chip: ${lineup.chip_played.toUpperCase()}` : "";

      let autosubStr = "";
      if (lineup.autosubs && lineup.autosubs.length > 0) {
        const subDetails = lineup.autosubs.map(s => `${s.out.name} OUT ➔ ${s.in.name} IN (+${s.in.points} pts)`).join(", ");
        autosubStr = ` | <span class="banner-autosub-badge">🔄 Auto-Subs: ${escapeHtml(subDetails)}</span>`;
      }

      document.getElementById("banner-subtitle").innerHTML = `Matchday Result: ${ptsStr} | Captain: <strong>${capStr}</strong> | Moves: ${movesStr}${hitsStr}${chipStr}${autosubStr}`;
      if (toggleBtn) {
        toggleBtn.classList.remove("hidden");
        toggleBtn.textContent = "🔮 Show Model Recommended XI";
        toggleBtn.onclick = () => loadLineup(lineup.gameweek, "model");
      }
    } else if (lineup.has_logged_decision && state.lineupMode === "model") {
      bannerEl.classList.remove("hidden");
      bannerEl.classList.add("model-view");
      document.getElementById("banner-icon").textContent = "🔮";
      document.getElementById("banner-title").textContent = `Gameweek ${lineup.gameweek} Model Recommendation`;
      document.getElementById("banner-subtitle").textContent = `Displaying model optimal starting XI based on expected points.`;
      if (toggleBtn) {
        toggleBtn.classList.remove("hidden");
        toggleBtn.textContent = "🔒 Show My Logged Lineup";
        toggleBtn.onclick = () => loadLineup(lineup.gameweek, "auto");
      }
    } else {
      bannerEl.classList.add("hidden");
    }
  }

  // Matchday Performance panel in sidebar
  const matchdayPanel = document.getElementById("panel-matchday-score");
  if (matchdayPanel) {
    if (isLogged && hasActualScore) {
      matchdayPanel.classList.remove("hidden");
      document.getElementById("stat-actual-score").textContent = `${lineup.actual_points} pts`;
      document.getElementById("stat-predicted-xp").textContent = `${lineup.projected_points.total_xp.toFixed(1)} xP`;
      const delta = lineup.actual_points - lineup.projected_points.total_xp;
      const deltaEl = document.getElementById("stat-actual-delta");
      deltaEl.textContent = `${delta >= 0 ? "+" : ""}${delta.toFixed(1)} pts`;
      deltaEl.className = delta >= 0 ? "stat-diff-positive" : "stat-diff-negative";

      const chipNorm = (lineup.chip_played || "").toLowerCase();
      const isFreeChip = ["wildcard", "freehit", "free_hit", "wc", "fh"].includes(chipNorm);
      const hitsCost = isFreeChip ? " (0pt - Free Chip)" : (lineup.transfer_hits > 0 ? ` (-${lineup.transfer_hits * 4}pt)` : " (0pt)");
      const movesDesc = (lineup.transfers && lineup.transfers.length)
        ? (lineup.transfers.length > 3
            ? `${lineup.transfers.length} moves (${lineup.chip_played ? lineup.chip_played.toUpperCase() : "Overhaul"})${hitsCost}`
            : lineup.transfers.map(t => `${t.outgoing_name} ➔ ${t.incoming_name}`).join(", ") + hitsCost)
        : `No transfers (0pt)`;
      document.getElementById("stat-matchday-moves").textContent = movesDesc;
      document.getElementById("stat-matchday-chip").textContent = lineup.chip_played ? lineup.chip_played.toUpperCase() : "None";
    } else {
      matchdayPanel.classList.add("hidden");
    }
  }

  if (lineup.captain) {
    const capTitle = lineup.captain.name + (lineup.captain_promoted ? " (VC Promoted)" : "");
    document.getElementById("cap-name").textContent = capTitle;
    document.getElementById("cap-sub").textContent = `${lineup.captain.team} (${lineup.captain.fixtures_summary})`;
    if (lineup.captain.actual_points !== null && lineup.captain.actual_points !== undefined) {
      document.getElementById("cap-xp").innerHTML = `<span class="score-highlight">${lineup.captain.actual_points} pts</span> <small>(${(lineup.captain.expected_points * 2).toFixed(1)} xP)</small>`;
    } else {
      document.getElementById("cap-xp").textContent = `${(lineup.captain.expected_points * 2).toFixed(1)} xP`;
    }
  }
  if (lineup.vice_captain) {
    document.getElementById("vc-name").textContent = lineup.vice_captain.name;
    document.getElementById("vc-sub").textContent = `${lineup.vice_captain.team} (${lineup.vice_captain.fixtures_summary})`;
    if (lineup.vice_captain.actual_points !== null && lineup.vice_captain.actual_points !== undefined) {
      document.getElementById("vc-xp").innerHTML = `<span class="score-highlight">${lineup.vice_captain.actual_points} pts</span> <small>(${lineup.vice_captain.expected_points.toFixed(1)} xP)</small>`;
    } else {
      document.getElementById("vc-xp").textContent = `${lineup.vice_captain.expected_points.toFixed(1)} xP`;
    }
  }

  // Update Sidebar stats
  document.getElementById("stat-starters-xp").textContent = lineup.projected_points.starters_xp.toFixed(1);
  const floorXp = lineup.projected_points.floor_xp !== undefined ? lineup.projected_points.floor_xp.toFixed(1) : "-";
  const ceilXp = lineup.projected_points.ceiling_xp !== undefined ? lineup.projected_points.ceiling_xp.toFixed(1) : "-";
  document.getElementById("stat-uncertainty-range").textContent = `[${floorXp}, ${ceilXp}]`;

  // Count shields / swords in XI
  let shields = 0;
  let swords = 0;

  // Clear rows
  ["pitch-gkp", "pitch-def", "pitch-mid", "pitch-fwd", "pitch-bench"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = "";
  });

  // Group starters by position
  const byPos = { GKP: [], DEF: [], MID: [], FWD: [] };
  lineup.starters.forEach(p => {
    const pos = p.pos_abbr || "MID";
    if (byPos[pos]) byPos[pos].push(p);
    if (p.strategic_category === "SHIELD") shields++;
    if (p.strategic_category === "SWORD") swords++;
  });

  document.getElementById("stat-shields-count").textContent = shields;
  document.getElementById("stat-swords-count").textContent = swords;

  // Render rows
  Object.keys(byPos).forEach(pos => {
    const rowEl = document.getElementById(`pitch-${pos.toLowerCase()}`);
    if (!rowEl) return;
    byPos[pos].forEach(p => {
      rowEl.appendChild(createPlayerCard(p));
    });
  });

  // Render bench
  const benchEl = document.getElementById("pitch-bench");
  if (benchEl && lineup.bench) {
    lineup.bench.forEach((p, idx) => {
      benchEl.appendChild(createPlayerCard(p, true, idx));
    });
  }
}

function getFormation(starters) {
  const def = starters.filter(p => p.pos_abbr === "DEF" || p.position === "DEF").length;
  const mid = starters.filter(p => p.pos_abbr === "MID" || p.position === "MID").length;
  const fwd = starters.filter(p => p.pos_abbr === "FWD" || p.position === "FWD").length;
  return `${def}-${mid}-${fwd}`;
}

function isLegalFormation(starters) {
  const gkp = starters.filter(p => p.pos_abbr === "GKP" || p.position === "GKP").length;
  const def = starters.filter(p => p.pos_abbr === "DEF" || p.position === "DEF").length;
  const mid = starters.filter(p => p.pos_abbr === "MID" || p.position === "MID").length;
  const fwd = starters.filter(p => p.pos_abbr === "FWD" || p.position === "FWD").length;
  return gkp === 1 && def >= 3 && def <= 5 && mid >= 2 && mid <= 5 && fwd >= 1 && fwd <= 3 && (gkp + def + mid + fwd === 11);
}

function canSwapPlayers(p1, p2, starters, bench) {
  if (!p1 || !p2 || p1.id === p2.id) return false;
  const isP1Starter = starters.some(p => p.id === p1.id);
  const isP2Starter = starters.some(p => p.id === p2.id);

  if (isP1Starter === isP2Starter) {
    if (p1.pos_abbr === "GKP" || p2.pos_abbr === "GKP") {
      return p1.pos_abbr === "GKP" && p2.pos_abbr === "GKP";
    }
    return true;
  }

  const starter = isP1Starter ? p1 : p2;
  const benchP = isP1Starter ? p2 : p1;

  if (starter.pos_abbr === "GKP" || benchP.pos_abbr === "GKP") {
    return starter.pos_abbr === "GKP" && benchP.pos_abbr === "GKP";
  }

  const testStarters = starters.map(p => (p.id === starter.id ? benchP : p));
  return isLegalFormation(testStarters);
}

function setPitchCaptain(playerId) {
  if (!state.currentLineup) return;
  const starters = state.currentLineup.starters || [];
  const bench = state.currentLineup.bench || [];
  const target = starters.find(p => p.id === playerId);
  if (!target) {
    const isBench = bench.find(p => p.id === playerId);
    if (isBench) {
      showToast("Cannot make a bench player Captain. Substitute them onto the pitch first!", true);
      return;
    }
    return;
  }

  starters.forEach(p => {
    if (p.role === "CAPTAIN") p.role = null;
  });

  if (target.role === "VICE_CAPTAIN") {
    target.role = null;
    state.currentLineup.vice_captain = null;
  }

  target.role = "CAPTAIN";
  state.currentLineup.captain = target;

  const decCap = document.getElementById("dec-captain");
  if (decCap) decCap.value = target.name;

  showToast(`Captain set to ${target.name}`);
  renderPitch(state.currentLineup);
}

function setPitchViceCaptain(playerId) {
  if (!state.currentLineup) return;
  const starters = state.currentLineup.starters || [];
  const bench = state.currentLineup.bench || [];
  const target = starters.find(p => p.id === playerId);
  if (!target) {
    const isBench = bench.find(p => p.id === playerId);
    if (isBench) {
      showToast("Cannot make a bench player Vice-Captain. Substitute them onto the pitch first!", true);
      return;
    }
    return;
  }

  if (target.role === "CAPTAIN") {
    showToast("A player cannot be both Captain and Vice-Captain!", true);
    return;
  }

  starters.forEach(p => {
    if (p.role === "VICE_CAPTAIN") p.role = null;
  });

  target.role = "VICE_CAPTAIN";
  state.currentLineup.vice_captain = target;

  const decVc = document.getElementById("dec-vc");
  if (decVc) decVc.value = target.name;

  showToast(`Vice-Captain set to ${target.name}`);
  renderPitch(state.currentLineup);
}

function startSubstitution(player) {
  state.subbingPlayer = player;
  const banner = document.getElementById("sub-mode-banner");
  const nameEl = document.getElementById("sub-source-name");
  if (banner) banner.classList.remove("hidden");
  if (nameEl) nameEl.textContent = `${player.name} (${player.pos_abbr || player.position})`;
  renderPitch(state.currentLineup);
}

function cancelSubstitution() {
  state.subbingPlayer = null;
  const banner = document.getElementById("sub-mode-banner");
  if (banner) banner.classList.add("hidden");
  renderPitch(state.currentLineup);
}

function executeSubstitution(sourcePlayer, targetPlayer) {
  if (!state.currentLineup) return;
  if (sourcePlayer.id === targetPlayer.id) {
    cancelSubstitution();
    return;
  }

  const starters = state.currentLineup.starters || [];
  const bench = state.currentLineup.bench || [];

  const sourceInStarters = starters.findIndex(p => p.id === sourcePlayer.id);
  const targetInStarters = starters.findIndex(p => p.id === targetPlayer.id);
  const sourceInBench = bench.findIndex(p => p.id === sourcePlayer.id);
  const targetInBench = bench.findIndex(p => p.id === targetPlayer.id);

  if (sourceInStarters !== -1 && targetInStarters !== -1) {
    cancelSubstitution();
    return;
  }

  if (sourceInBench !== -1 && targetInBench !== -1) {
    if (sourcePlayer.pos_abbr === "GKP" || targetPlayer.pos_abbr === "GKP") {
      showToast("Cannot swap goalkeeper with outfield player on bench.", true);
      cancelSubstitution();
      return;
    }
    const temp = bench[sourceInBench];
    bench[sourceInBench] = bench[targetInBench];
    bench[targetInBench] = temp;
    cancelSubstitution();
    showToast(`Bench order updated: ${sourcePlayer.name} swapped with ${targetPlayer.name}.`);
    return;
  }

  const starterIdx = sourceInStarters !== -1 ? sourceInStarters : targetInStarters;
  const benchIdx = sourceInBench !== -1 ? sourceInBench : targetInBench;
  const starterP = starters[starterIdx];
  const benchP = bench[benchIdx];

  if (starterP.pos_abbr === "GKP" || benchP.pos_abbr === "GKP") {
    if (starterP.pos_abbr !== "GKP" || benchP.pos_abbr !== "GKP") {
      showToast("Goalkeepers can only be swapped with the backup goalkeeper.", true);
      cancelSubstitution();
      return;
    }
  }

  const testStarters = [...starters];
  testStarters[starterIdx] = benchP;

  if (!isLegalFormation(testStarters)) {
    showToast("Invalid substitution: Formation must have 3-5 DEF, 2-5 MID, 1-3 FWD, and 1 GKP.", true);
    cancelSubstitution();
    return;
  }

  starters[starterIdx] = benchP;
  bench[benchIdx] = starterP;

  if (starterP.role === "CAPTAIN") {
    starterP.role = null;
    benchP.role = "CAPTAIN";
    state.currentLineup.captain = benchP;
    const decCap = document.getElementById("dec-captain");
    if (decCap) decCap.value = benchP.name;
    showToast(`Armband passed to ${benchP.name}`);
  } else if (starterP.role === "VICE_CAPTAIN") {
    starterP.role = null;
    benchP.role = "VICE_CAPTAIN";
    state.currentLineup.vice_captain = benchP;
    const decVc = document.getElementById("dec-vc");
    if (decVc) decVc.value = benchP.name;
  }

  const newFormation = getFormation(starters);
  state.currentLineup.formation = newFormation;

  const startersXp = starters.reduce((acc, p) => acc + (p.expected_points || 0), 0);
  const capBonus = state.currentLineup.captain ? (state.currentLineup.captain.expected_points || 0) : 0;
  state.currentLineup.projected_points.starters_xp = startersXp;
  state.currentLineup.projected_points.total_xp = startersXp + capBonus;

  cancelSubstitution();
  showToast(`Substituted ${starterP.name} ➔ ${benchP.name} (Formation: ${newFormation})`);
}

function createPlayerCard(p, isBench = false, benchIdx = 0) {
  const card = document.createElement("div");
  card.className = "player-card";

  if (state.subbingPlayer) {
    if (state.subbingPlayer.id === p.id) {
      card.classList.add("sub-source");
    } else if (state.currentLineup && canSwapPlayers(state.subbingPlayer, p, state.currentLineup.starters, state.currentLineup.bench)) {
      card.classList.add("sub-target");
    }
  }

  // Role Badge (Captain / Vice)
  let badgeHtml = "";
  if (p.role === "CAPTAIN") {
    const title = p.promoted_from_vice ? "Captain (Promoted from Vice-Captain)" : "Captain";
    const label = p.promoted_from_vice ? "C*" : "C";
    badgeHtml = `<div class="player-badge-role badge-cap" title="${title}">${label}</div>`;
  } else if (p.role === "VICE_CAPTAIN") {
    badgeHtml = '<div class="player-badge-role badge-vc" title="Vice-Captain">V</div>';
  }

  // Auto-Sub Badges
  if (p.subbed_out) {
    badgeHtml += '<div class="player-badge-sub subbed-out" title="Auto-subbed out (0 mins played)">OUT</div>';
    card.classList.add("player-subbed-out");
  } else if (p.subbed_in) {
    badgeHtml += '<div class="player-badge-sub subbed-in" title="Auto-subbed in from bench">IN</div>';
    card.classList.add("player-subbed-in");
  }

  // FDR Badge
  const fdrVal = p.next_fixture_fdr || 3;
  const fixSummary = p.fixtures_summary || `${p.team}`;

  // EO Badge if available
  let eoHtml = "";
  if (p.strategic_category) {
    const tagClass = `tag-${p.strategic_category.toLowerCase()}`;
    const eoPct = p.effective_ownership_pct !== undefined ? `${Math.round(p.effective_ownership_pct)}%` : "";
    eoHtml = `<span class="player-eo-tag ${tagClass}">${p.strategic_category} ${eoPct}</span>`;
  }

  const benchLabel = isBench ? `<div class="player-sub">${p.role === 'GK_SUB' ? 'GK Sub' : `Sub ${benchIdx}`}</div>` : "";

  let scoreHtml = "";
  if (p.actual_points !== null && p.actual_points !== undefined) {
    const multLabel = p.role === "CAPTAIN" ? '<span class="pts-unit">(x2)</span>' : "";
    scoreHtml = `
      <div class="player-actual-pts">
        <span class="pts-val">${p.actual_points}</span>
        <span class="pts-unit">pts</span>
        ${multLabel}
      </div>
      <div class="player-xp-sub">${p.expected_points.toFixed(1)} xP</div>
    `;
  } else {
    scoreHtml = `<div class="player-xp">${p.expected_points.toFixed(1)} xP</div>`;
  }

  card.innerHTML = `
    ${badgeHtml}
    <div class="player-name" title="${p.name}">${p.name}</div>
    <div class="player-sub">${p.pos_abbr || ''} · ${p.team}</div>
    ${benchLabel}
    ${scoreHtml}
    <div class="player-fdr-badge fdr-${fdrVal}">${fixSummary}</div>
    ${eoHtml}
  `;

  // Quick Action Buttons
  const actions = document.createElement("div");
  actions.className = "card-quick-actions";

  const isCap = p.role === "CAPTAIN";
  const isVc = p.role === "VICE_CAPTAIN";

  if (!isBench) {
    const capBtn = document.createElement("button");
    capBtn.type = "button";
    capBtn.className = `quick-btn btn-cap ${isCap ? 'active-role' : ''}`;
    capBtn.title = isCap ? "Current Captain" : "Make Captain";
    capBtn.textContent = "C";
    capBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      setPitchCaptain(p.id);
    });
    actions.appendChild(capBtn);

    const vcBtn = document.createElement("button");
    vcBtn.type = "button";
    vcBtn.className = `quick-btn btn-vc ${isVc ? 'active-role' : ''}`;
    vcBtn.title = isVc ? "Current Vice-Captain" : "Make Vice-Captain";
    vcBtn.textContent = "V";
    vcBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      setPitchViceCaptain(p.id);
    });
    actions.appendChild(vcBtn);
  }

  const subBtn = document.createElement("button");
  subBtn.type = "button";
  subBtn.className = "quick-btn btn-sub";
  subBtn.title = "Substitute player";
  subBtn.textContent = "⇄";
  subBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    if (state.subbingPlayer && state.subbingPlayer.id === p.id) {
      cancelSubstitution();
    } else {
      startSubstitution(p);
    }
  });
  actions.appendChild(subBtn);

  card.appendChild(actions);

  card.addEventListener("click", () => {
    if (state.subbingPlayer) {
      if (state.subbingPlayer.id === p.id) {
        cancelSubstitution();
      } else {
        executeSubstitution(state.subbingPlayer, p);
      }
    } else {
      openPlayerStatsModal(p.id, p);
    }
  });

  return card;
}

// Player Statistics & Details Modal
let inspectingPlayerId = null;

async function openPlayerStatsModal(playerId, initialData = null) {
  inspectingPlayerId = playerId;
  const modal = document.getElementById("modal-player-stats");
  if (!modal) return;

  const nameEl = document.getElementById("ps-name");
  const metaEl = document.getElementById("ps-pos-team");
  const priceEl = document.getElementById("ps-price");
  const bodyEl = document.getElementById("ps-body");

  nameEl.textContent = initialData ? initialData.name : `Player #${playerId}`;
  metaEl.textContent = initialData ? `${initialData.pos_abbr || ''} · ${initialData.team || ''}` : "";
  priceEl.textContent = initialData?.price_fmt || "";

  bodyEl.innerHTML = '<p class="text-muted" style="padding: 1rem 0;">Loading detailed statistics, projections, and fixture calendar...</p>';
  modal.classList.remove("hidden");

  try {
    const gw = state.selectedGameweek || state.activeGameweek || 1;
    const p = await api(`/api/player?id=${playerId}&gameweek=${gw}`);

    nameEl.textContent = p.name;
    metaEl.textContent = `${p.position} (${p.pos_abbr}) · ${p.team_name} (${p.team_short})`;
    priceEl.textContent = p.price_fmt;

    let alertHtml = "";
    if (p.status !== "a" || p.news) {
      const chanceStr = p.chance_playing_next !== null ? `(${p.chance_playing_next}% chance)` : "";
      alertHtml = `
        <div style="background: rgba(239, 68, 68, 0.15); border-left: 4px solid var(--accent-red); padding: 0.6rem 0.8rem; border-radius: 4px; margin-bottom: 1rem; font-size: 0.85rem;">
          <strong style="color: var(--accent-red);">Status / News ${chanceStr}:</strong> ${p.news || 'Flagged / Doubtful'}
        </div>
      `;
    }

    const xpStr = p.expected_points !== null ? p.expected_points.toFixed(1) : "--";
    const rangeStr = (p.xp_floor !== null && p.xp_ceiling !== null) ? `${p.xp_floor.toFixed(1)} – ${p.xp_ceiling.toFixed(1)}` : "--";
    const minStr = p.expected_minutes !== null ? `${p.expected_minutes}m` : "--";
    const probStr = p.start_probability !== null ? `${p.start_probability}%` : "--";
    const eoStr = `${p.effective_ownership_pct}%`;
    const catStr = p.strategic_category || "CORE";

    const fixHtml = (p.fixtures || []).map(f => {
      const diffClass = `fdr-${f.difficulty || 3}`;
      return `
        <div class="ps-fixture-pill">
          <span class="ps-fix-gw">GW${f.gameweek}</span>
          <span class="ps-fix-opp">${f.summary}</span>
          <span class="player-fdr-badge ${diffClass}" style="margin: 0; padding: 1px 6px; font-size: 0.65rem;">FDR ${f.difficulty}</span>
        </div>
      `;
    }).join("") || '<span class="text-muted">No upcoming fixtures scheduled.</span>';

    bodyEl.innerHTML = `
      ${alertHtml}
      <div class="ps-section">
        <div class="ps-section-title">Gameweek ${gw} Tactical Projection</div>
        <div class="ps-stats-grid">
          <div class="ps-stat-box" style="border-color: var(--accent-green);">
            <div class="ps-stat-label">Expected xP</div>
            <div class="ps-stat-value" style="color: var(--accent-green);">${xpStr}</div>
          </div>
          <div class="ps-stat-box">
            <div class="ps-stat-label">Floor – Ceiling</div>
            <div class="ps-stat-value" style="font-size: 0.92rem;">${rangeStr}</div>
          </div>
          <div class="ps-stat-box">
            <div class="ps-stat-label">Start / Minutes</div>
            <div class="ps-stat-value" style="font-size: 0.92rem;">${probStr} · ${minStr}</div>
          </div>
          <div class="ps-stat-box">
            <div class="ps-stat-label">Effective Own.</div>
            <div class="ps-stat-value" style="color: var(--accent-gold);">${eoStr}</div>
          </div>
          <div class="ps-stat-box">
            <div class="ps-stat-label">Strategic Role</div>
            <div class="ps-stat-value" style="font-size: 0.92rem;">${catStr}</div>
          </div>
        </div>
      </div>

      <div class="ps-section">
        <div class="ps-section-title">Season Performance & Underlyings</div>
        <div class="ps-stats-grid">
          <div class="ps-stat-box">
            <div class="ps-stat-label">Total Points</div>
            <div class="ps-stat-value">${p.total_points}</div>
          </div>
          <div class="ps-stat-box">
            <div class="ps-stat-label">Form</div>
            <div class="ps-stat-value">${p.form}</div>
          </div>
          <div class="ps-stat-box">
            <div class="ps-stat-label">Pts / Match</div>
            <div class="ps-stat-value">${p.points_per_game}</div>
          </div>
          <div class="ps-stat-box">
            <div class="ps-stat-label">Mins (Starts)</div>
            <div class="ps-stat-value" style="font-size: 0.92rem;">${p.minutes} (${p.starts})</div>
          </div>
          <div class="ps-stat-box">
            <div class="ps-stat-label">Expected Goals</div>
            <div class="ps-stat-value">${p.expected_goals} <small style="font-size:0.65rem; color:var(--text-muted);">(${p.expected_goals_per_90}/90)</small></div>
          </div>
          <div class="ps-stat-box">
            <div class="ps-stat-label">Expected Assists</div>
            <div class="ps-stat-value">${p.expected_assists} <small style="font-size:0.65rem; color:var(--text-muted);">(${p.expected_assists_per_90}/90)</small></div>
          </div>
          <div class="ps-stat-box">
            <div class="ps-stat-label">xGI</div>
            <div class="ps-stat-value">${p.expected_goal_involvements}</div>
          </div>
          <div class="ps-stat-box">
            <div class="ps-stat-label">Clean Sheets/90</div>
            <div class="ps-stat-value">${p.clean_sheets_per_90}</div>
          </div>
          <div class="ps-stat-box">
            <div class="ps-stat-label">ICT Index</div>
            <div class="ps-stat-value">${p.ict_index}</div>
          </div>
          <div class="ps-stat-box">
            <div class="ps-stat-label">Bonus (BPS)</div>
            <div class="ps-stat-value">${p.bps}</div>
          </div>
        </div>
      </div>

      <div class="ps-section" style="margin-bottom: 0.5rem;">
        <div class="ps-section-title">Upcoming Fixtures</div>
        <div class="ps-fixtures-row">${fixHtml}</div>
      </div>
    `;
  } catch (err) {
    bodyEl.innerHTML = `<p class="text-muted">Error loading player details: ${err.message}</p>`;
  }
}

// Save Lineup directly from Pitch
async function savePitchLineup() {
  if (!state.currentLineup || !state.currentLineup.starters) {
    showToast("No active lineup to save.", true);
    return;
  }
  const gw = parseInt(document.getElementById("lineup-gw-select").value) || state.selectedGameweek || state.activeGameweek;
  const chip = document.getElementById("pitch-chip-select").value || null;

  const starters = state.currentLineup.starters.map(p => p.id);
  const bench = (state.currentLineup.bench || []).map(p => p.id);
  const capId = state.currentLineup.captain ? state.currentLineup.captain.id : starters[0];
  const vcId = state.currentLineup.vice_captain ? state.currentLineup.vice_captain.id : (starters[1] || starters[0]);

  try {
    const payload = {
      team_id: state.activeTeamId,
      gameweek: gw,
      starters: starters,
      bench: bench,
      captain: capId,
      vice_captain: vcId,
      chip: chip,
      overwrite: true,
    };

    const res = await api("/api/decisions", {
      method: "POST",
      body: JSON.stringify(payload),
    });

    showToast(`Lineup & Captain saved for GW${gw}! (Pred: ${res.predicted_lineup_xp ? res.predicted_lineup_xp.toFixed(1) + ' xP' : ''})`);
    await refreshActiveTeamData();
    await loadDecisions();
  } catch (err) {
    showToast(`Error saving lineup: ${err.message}`, true);
  }
}

// Decision Logger
async function handleDecisionSubmit(e) {
  e.preventDefault();
  const gw = parseInt(document.getElementById("dec-gw").value);
  const chip = document.getElementById("dec-chip").value || null;
  const captain = document.getElementById("dec-captain").value.trim();
  const vc = document.getElementById("dec-vc").value.trim();
  const hitsRaw = document.getElementById("dec-hits").value;
  const actualRaw = document.getElementById("dec-actual-pts").value;
  const notes = document.getElementById("dec-notes").value.trim();

  const hits = hitsRaw ? parseInt(hitsRaw) : null;
  const actual_points = actualRaw ? parseInt(actualRaw) : null;

  try {
    const payload = {
      team_id: state.activeTeamId,
      gameweek: gw,
      captain: captain,
      vice_captain: vc,
      chip: chip,
      hits: hits,
      actual_points: actual_points,
      notes: notes,
      overwrite: true,
    };

    if (state.currentLineup && state.currentLineup.starters) {
      payload.starters = state.currentLineup.starters.map(p => p.id);
      payload.bench = (state.currentLineup.bench || []).map(p => p.id);
    }

    const res = await api("/api/decisions", {
      method: "POST",
      body: JSON.stringify(payload),
    });

    showToast(`Logged decision for GW${gw}!`);
    await refreshActiveTeamData();
    await loadDecisions();
  } catch (err) {
    showToast(`Error logging decision: ${err.message}`, true);
  }
}

async function loadDecisions() {
  const container = document.getElementById("decisions-list");
  if (!container) return;
  try {
    const data = await api(`/api/decisions?team=${state.activeTeamId}`);
    const list = data.decisions || [];
    if (list.length === 0) {
      container.innerHTML = '<p class="text-muted">No decisions logged yet for this team.</p>';
      return;
    }

    container.innerHTML = "";
    list.forEach(dec => {
      const el = document.createElement("div");
      el.className = "decision-entry";
      const chipBadge = dec.chip_played ? `<span class="badge badge-info">${dec.chip_played.toUpperCase()}</span>` : "";
      const scoreBadge = dec.actual_points !== null ? ` | Score: <strong>${dec.actual_points} pts</strong>` : "";
      const decChipNorm = (dec.chip_played || "").toLowerCase();
      const decIsFreeChip = ["wildcard", "freehit", "free_hit", "wc", "fh"].includes(decChipNorm);
      const hitsDesc = decIsFreeChip ? "(Hits: 0pt - Free Chip)" : `(Hits: -${dec.transfer_hits * 4}pt)`;
      const moves = dec.transfers && dec.transfers.length ? `Moves: ${dec.transfers.map(t => `${t.outgoing_name} ➔ ${t.incoming_name}`).join(", ")}` : "No transfers";

      el.innerHTML = `
        <div class="decision-entry-header">
          <span>GW${dec.gameweek} Decision ${chipBadge}</span>
          <span>Pred: ${dec.predicted_lineup_xp.toFixed(1)} xP${scoreBadge}</span>
        </div>
        <div class="decision-entry-sub">
          Captain: <strong>${dec.captain_name}</strong> | Vice: <strong>${dec.vice_captain_name}</strong>
        </div>
        <div class="decision-entry-sub">${moves} ${hitsDesc}</div>
        ${dec.notes ? `<div class="decision-entry-sub" style="font-style: italic; margin-top: 0.2rem;">"${dec.notes}"</div>` : ""}
      `;
      container.appendChild(el);
    });

    const targetGw = parseInt(document.getElementById("dec-gw").value) || state.activeGameweek;
    const curDec = list.find(d => d.gameweek === targetGw);
    renderExecutedTransfersBox(curDec && curDec.transfers ? curDec.transfers : []);

    if (curDec) {
      const capSelect = document.getElementById("dec-captain");
      const vcSelect = document.getElementById("dec-vc");
      if (capSelect && curDec.captain_name && (!capSelect.value || capSelect.value === "")) {
        capSelect.value = curDec.captain_name;
      }
      if (vcSelect && curDec.vice_captain_name && (!vcSelect.value || vcSelect.value === "")) {
        vcSelect.value = curDec.vice_captain_name;
      }
      const chipSelect = document.getElementById("dec-chip");
      if (chipSelect && curDec.chip_played && !chipSelect.value) {
        chipSelect.value = curDec.chip_played;
      }
      const hitsInput = document.getElementById("dec-hits");
      if (hitsInput && (!hitsInput.value || hitsInput.value === "")) {
        const isFree = curDec.chip_played && ["wildcard", "wc", "freehit", "free_hit", "fh"].some(c => curDec.chip_played.toLowerCase().includes(c));
        hitsInput.placeholder = isFree ? "0 (Free with Chip)" : `Auto-calculated (${curDec.transfer_hits || 0})`;
      }
    }
  } catch (err) {
    container.innerHTML = `<p class="text-muted">Failed to load decisions: ${err.message}</p>`;
  }
}

function populateDecisionLoggerSquad(players) {
  const capSelect = document.getElementById("dec-captain");
  const vcSelect = document.getElementById("dec-vc");
  const outSelect = document.getElementById("tx-exec-out");
  if (!players || !players.length) return;

  const curCap = capSelect ? capSelect.value : "";
  const curVc = vcSelect ? vcSelect.value : "";
  const curOut = outSelect ? outSelect.value : "";

  if (capSelect) {
    capSelect.innerHTML = '<option value="">-- Select Captain --</option>';
    players.forEach(p => {
      const opt = document.createElement("option");
      opt.value = p.name;
      opt.textContent = `${p.name} (${p.pos_abbr || p.position} · ${p.team})`;
      if (curCap === p.name || (!curCap && p.role === "CAPTAIN")) opt.selected = true;
      capSelect.appendChild(opt);
    });
  }

  if (vcSelect) {
    vcSelect.innerHTML = '<option value="">-- Select Vice-Captain --</option>';
    players.forEach(p => {
      const opt = document.createElement("option");
      opt.value = p.name;
      opt.textContent = `${p.name} (${p.pos_abbr || p.position} · ${p.team})`;
      if (curVc === p.name || (!curVc && p.role === "VICE_CAPTAIN")) opt.selected = true;
      vcSelect.appendChild(opt);
    });
  }

  if (outSelect) {
    outSelect.innerHTML = '<option value="">-- Select player to sell --</option>';
    players.forEach(p => {
      const opt = document.createElement("option");
      opt.value = p.id;
      const priceText = p.selling_price_fmt || p.price_fmt || `£${(p.price_tenths / 10).toFixed(1)}m`;
      opt.textContent = `${p.name} (${p.pos_abbr || p.position} · ${p.team} · ${priceText})`;
      if (String(curOut) === String(p.id)) opt.selected = true;
      outSelect.appendChild(opt);
    });
  }
}

async function loadAllLeaguePlayers() {
  if (state.allLeaguePlayers && state.allLeaguePlayers.length > 0) return;
  try {
    const data = await api("/api/players?all=true");
    state.allLeaguePlayers = data.players || [];
    populateAvailablePlayersDatalist();
  } catch (err) {
    console.error("Failed to load league players:", err);
  }
}

function populateAvailablePlayersDatalist() {
  const datalist = document.getElementById("available-players-datalist");
  if (!datalist || !state.allLeaguePlayers) return;
  const squadIds = new Set(state.currentSquad && state.currentSquad.players ? state.currentSquad.players.map(p => p.id) : []);

  datalist.innerHTML = "";
  state.allLeaguePlayers.forEach(p => {
    if (!squadIds.has(p.id)) {
      const opt = document.createElement("option");
      opt.value = `${p.name} (${p.team} · ${p.position} · ${p.price_fmt})`;
      opt.setAttribute("data-id", p.id);
      datalist.appendChild(opt);
    }
  });
}

function resolveIncomingPlayer(inputText) {
  if (!inputText || !state.allLeaguePlayers) return null;
  const txt = inputText.trim().toLowerCase();
  const directMatch = state.allLeaguePlayers.find(p => {
    const formatted = `${p.name} (${p.team} · ${p.position} · ${p.price_fmt})`.toLowerCase();
    return formatted === txt || p.name.toLowerCase() === txt;
  });
  if (directMatch) return directMatch;

  return (
    state.allLeaguePlayers.find(p => p.name.toLowerCase().startsWith(txt)) ||
    state.allLeaguePlayers.find(p => p.name.toLowerCase().includes(txt)) ||
    null
  );
}

function updateTradeSummary() {
  const summaryEl = document.getElementById("tx-exec-summary");
  if (!summaryEl) return;
  const outSelect = document.getElementById("tx-exec-out");
  const inInput = document.getElementById("tx-exec-in");
  const outId = parseInt(outSelect.value);
  const inPlayer = resolveIncomingPlayer(inInput.value);

  if (!outId && !inPlayer) {
    summaryEl.textContent = "";
    return;
  }

  const outPlayer = state.currentSquad && state.currentSquad.players ? state.currentSquad.players.find(p => p.id === outId) : null;

  if (outPlayer && inPlayer) {
    const outSell = outPlayer.selling_price_tenths !== undefined ? outPlayer.selling_price_tenths : outPlayer.price_tenths;
    const inCost = inPlayer.price_tenths;
    const diff = (outSell - inCost) / 10;
    const sign = diff >= 0 ? "+" : "";
    summaryEl.innerHTML = `Selling <strong>${outPlayer.name}</strong> (£${(outSell / 10).toFixed(1)}m) ➔ Buying <strong>${inPlayer.name}</strong> (${inPlayer.price_fmt}). Net Bank Impact: <strong>${sign}£${diff.toFixed(1)}m</strong>`;
  } else if (outPlayer) {
    const priceText = outPlayer.selling_price_fmt || outPlayer.price_fmt || `£${(outPlayer.price_tenths / 10).toFixed(1)}m`;
    summaryEl.innerHTML = `Selling <strong>${outPlayer.name}</strong> (${priceText})`;
  } else if (inPlayer) {
    summaryEl.innerHTML = `Buying <strong>${inPlayer.name}</strong> (${inPlayer.team} · ${inPlayer.position} · ${inPlayer.price_fmt})`;
  }
}

async function handleExecuteTrade() {
  const outSelect = document.getElementById("tx-exec-out");
  const inInput = document.getElementById("tx-exec-in");
  const outId = parseInt(outSelect.value);
  if (!outId) {
    showToast("Please select a player to sell (OUT)", true);
    return;
  }
  const inPlayer = resolveIncomingPlayer(inInput.value);
  if (!inPlayer) {
    showToast("Please select a valid player to buy (IN)", true);
    return;
  }
  const outPlayer = state.currentSquad && state.currentSquad.players ? state.currentSquad.players.find(p => p.id === outId) : null;
  const outName = outPlayer ? outPlayer.name : `Player ${outId}`;

  const gw = parseInt(document.getElementById("dec-gw").value) || state.activeGameweek;
  const chipVal = document.getElementById("dec-chip") ? document.getElementById("dec-chip").value : null;

  try {
    const res = await api("/api/transfers/execute", {
      method: "POST",
      body: JSON.stringify({
        team_id: state.activeTeamId,
        gameweek: gw,
        chip: chipVal || null,
        transfers: [{ outgoing_id: outId, incoming_id: inPlayer.id }],
      }),
    });

    showToast(`Transfer executed: ${outName} ➔ ${inPlayer.name}! Bank: ${res.bank_fmt}, FT: ${res.free_transfers}`);
    inInput.value = "";
    outSelect.value = "";
    document.getElementById("tx-exec-summary").textContent = "";

    renderExecutedTransfersBox(res.transfers);

    await refreshActiveTeamData();
    populateAvailablePlayersDatalist();
    await loadDecisions();
  } catch (err) {
    showToast(`Transfer failed: ${err.message}`, true);
  }
}

function renderExecutedTransfersBox(transfers) {
  const box = document.getElementById("tx-executed-box");
  const list = document.getElementById("tx-executed-list");
  if (!box || !list) return;
  if (!transfers || transfers.length === 0) {
    box.classList.add("hidden");
    return;
  }
  box.classList.remove("hidden");
  list.innerHTML = transfers
    .map(
      t => `
    <div class="tx-executed-item" style="display: flex; justify-content: space-between; padding: 4px 0; font-size: 0.85rem; border-bottom: 1px solid var(--border-color);">
      <span><strong>${t.outgoing_name}</strong> ➔ <strong style="color: var(--accent-gold);">${t.incoming_name}</strong></span>
      <span class="text-muted">Sold £${(t.selling_price_tenths / 10).toFixed(1)}m · Bought £${(t.purchase_price_tenths / 10).toFixed(1)}m</span>
    </div>
  `,
    )
    .join("");
}

// Transfers Optimizer View
async function runSuggestTransfers() {
  const container = document.getElementById("tx-results-container");
  container.innerHTML = '<p class="text-muted">Solving branch-and-bound combinatorial transfers across the Premier League...</p>';

  const numTx = document.getElementById("tx-num").value;
  const gws = document.getElementById("tx-gws").value;
  const risk = document.getElementById("tx-risk").value;
  const engine = document.getElementById("tx-engine") ? document.getElementById("tx-engine").value : "v1.3.5";

  try {
    const data = await api(`/api/transfers?team=${state.activeTeamId}&transfers=${numTx}&gameweeks=${gws}&risk=${risk}&engine=${engine}`);
    const suggestions = data.top_suggestions || [];
    if (suggestions.length === 0) {
      container.innerHTML = '<p class="text-muted">No valid transfer options found within budget and team limits.</p>';
      return;
    }

    container.innerHTML = "";
    suggestions.forEach((opt, idx) => {
      const card = document.createElement("div");
      card.className = "tx-card";
      const hitStr = opt.transfer_hits > 0 ? ` | Hit: -${opt.transfer_hits * 4} pts` : "";

      const movesHtml = opt.outgoing.map((outP, mIdx) => {
        const inP = opt.incoming[mIdx];
        return `
          <div class="tx-move-row">
            <span class="tx-out">OUT: ${outP.name} (${outP.team})</span>
            <span class="tx-in">IN: ${inP.name} (${inP.team})</span>
          </div>
        `;
      }).join("");

      const rb = opt.reason_breakdown || {};
      let badgesHtml = "";
      if (opt.lineup_xp_delta !== undefined) {
        badgesHtml += `<span class="badge" style="background: rgba(34, 197, 94, 0.15); color: #22c55e; border: 1px solid rgba(34, 197, 94, 0.3); font-size: 0.75rem; padding: 2px 6px; border-radius: 4px; margin-right: 4px;">Lineup: ${opt.lineup_xp_delta >= 0 ? '+' : ''}${opt.lineup_xp_delta.toFixed(2)} xP</span>`;
      }
      if (rb.pool_expansion_surfaced) {
        badgesHtml += `<span class="badge" style="background: rgba(59, 130, 246, 0.15); color: #3b82f6; border: 1px solid rgba(59, 130, 246, 0.3); font-size: 0.75rem; padding: 2px 6px; border-radius: 4px; margin-right: 4px;">Pool Expansion</span>`;
      }
      if (rb.gk_suppression && rb.gk_suppression !== "n/a") {
        badgesHtml += `<span class="badge" style="background: rgba(245, 158, 11, 0.15); color: #f59e0b; border: 1px solid rgba(245, 158, 11, 0.3); font-size: 0.75rem; padding: 2px 6px; border-radius: 4px; margin-right: 4px;">GK: ${rb.gk_suppression}</span>`;
      }
      if (rb.multi_horizon_gain && rb.multi_horizon_gain > 0.5) {
        badgesHtml += `<span class="badge" style="background: rgba(168, 85, 247, 0.15); color: #a855f7; border: 1px solid rgba(168, 85, 247, 0.3); font-size: 0.75rem; padding: 2px 6px; border-radius: 4px; margin-right: 4px;">Horizon: +${rb.multi_horizon_gain.toFixed(1)}</span>`;
      }

      const scoreDisplay = opt.lineup_xp_delta !== undefined ? opt.lineup_xp_delta : opt.xp_delta;
      card.innerHTML = `
        <div class="tx-card-header">
          <span class="tx-rank-badge">#${idx + 1} Best Move</span>
          <span class="tx-delta-xp">${scoreDisplay >= 0 ? '+' : ''}${scoreDisplay.toFixed(1)} xP${hitStr}</span>
        </div>
        ${badgesHtml ? `<div style="margin: 4px 0 8px 0;">${badgesHtml}</div>` : ''}
        <div class="tx-moves">${movesHtml}</div>
        <div class="stat-row">
          <span>Post-Move Bank:</span>
          <strong>£${(opt.bank_after_tenths / 10).toFixed(1)}m</strong>
        </div>
        <button type="button" class="btn btn-primary btn-sm btn-apply-tx" style="margin-top: 0.5rem; width: 100%;">⚡ Apply Move</button>
      `;

      // Select card on click
      card.addEventListener("click", () => {
        container.querySelectorAll(".tx-card").forEach(c => c.classList.remove("selected-tx-card"));
        card.classList.add("selected-tx-card");
      });

      // Apply button handler
      const btnApply = card.querySelector(".btn-apply-tx");
      btnApply.addEventListener("click", async (e) => {
        e.stopPropagation();
        const movesSummary = opt.outgoing.map((o, i) => `${o.name} ➔ ${opt.incoming[i].name}`).join(", ");
        const targetGw = state.selectedGameweek || state.activeGameweek || 1;
        const confirmed = confirm(
          `Apply transfer move #${idx + 1} (${movesSummary}) to your team for GW${targetGw}?`
        );
        if (!confirmed) return;

        try {
          const outByPos = {};
          opt.outgoing.forEach(p => {
            const pos = p.position || p.pos_abbr || "DEF";
            outByPos[pos] = outByPos[pos] || [];
            outByPos[pos].push(p);
          });
          const inByPos = {};
          opt.incoming.forEach(p => {
            const pos = p.position || p.pos_abbr || "DEF";
            inByPos[pos] = inByPos[pos] || [];
            inByPos[pos].push(p);
          });

          let transfersPayload = [];
          for (const pos in outByPos) {
            const outs = outByPos[pos];
            const ins = inByPos[pos] || [];
            for (let i = 0; i < outs.length; i++) {
              if (ins[i]) {
                transfersPayload.push({
                  outgoing_id: outs[i].id,
                  incoming_id: ins[i].id,
                });
              }
            }
          }
          if (transfersPayload.length < opt.outgoing.length) {
            transfersPayload = opt.outgoing.map((outP, i) => ({
              outgoing_id: outP.id,
              incoming_id: opt.incoming[i].id,
            }));
          }

          const res = await api("/api/transfers/execute", {
            method: "POST",
            body: JSON.stringify({
              team_id: state.activeTeamId,
              gameweek: targetGw,
              transfers: transfersPayload,
            }),
          });

          showToast(res.message || "Transfers applied successfully!");
          await refreshActiveTeamData();
          await loadDecisions();
          await loadLineup();
          await runSuggestTransfers();
        } catch (err) {
          showToast(`Transfer failed: ${err.message}`, true);
        }
      });

      container.appendChild(card);
    });
  } catch (err) {
    container.innerHTML = `<p class="text-muted">Optimization error: ${err.message}</p>`;
  }
}

// Wildcard / Free Hit Studio
async function runWildcard() {
  const container = document.getElementById("wc-results-container");
  container.innerHTML = '<p class="text-muted">Optimizing legal 15-player squad and starting XI under budget...</p>';

  const mode = document.getElementById("wc-mode").value;
  const budget = document.getElementById("wc-budget").value;
  const risk = document.getElementById("wc-risk").value;

  try {
    const budgetParam = budget ? `&budget=${budget}` : "";
    const data = await api(`/api/wildcard?team=${state.activeTeamId}&risk=${risk}${budgetParam}`);
    const xi = data.starters || data.optimal_starting_xi || [];
    const bench = data.bench || data.optimal_bench || [];
    const totalCostFmt = data.total_cost_fmt || `£${(data.total_cost_tenths / 10).toFixed(1)}m`;
    const bankRemFmt = data.bank_remaining_fmt || `£${(data.bank_remaining_tenths / 10).toFixed(1)}m`;
    const totalLineupXp = data.total_lineup_xp !== undefined ? data.total_lineup_xp : (data.projected_xi_xp || 0);

    const xiHtml = xi.map(p => `<li><strong>${p.name}</strong> (${p.team}, ${p.pos_abbr}) - ${p.price_fmt || `£${(p.price_tenths/10).toFixed(1)}m`} - ${p.expected_points.toFixed(1)} xP</li>`).join("");
    const benchHtml = bench.map(p => `<li>${p.name} (${p.team}, ${p.pos_abbr}) - ${p.price_fmt || `£${(p.price_tenths/10).toFixed(1)}m`} - ${p.expected_points.toFixed(1)} xP</li>`).join("");

    container.innerHTML = `
      <div class="panel card" style="margin-top: 1rem;">
        <div class="panel-header" style="flex-wrap: wrap; gap: 0.6rem;">
          <div>
            <h3 style="margin-bottom: 0.2rem;">${mode.toUpperCase()} Optimized Squad (${totalCostFmt} spent | Remaining Bank: ${bankRemFmt})</h3>
            <span class="badge badge-success">Projected XI: ${totalLineupXp.toFixed(1)} xP</span>
          </div>
          <button id="btn-apply-wc-squad" class="btn btn-primary btn-sm">
            ⚡ Apply ${mode.toUpperCase()} Squad
          </button>
        </div>
        <div class="panel-body two-col-layout">
          <div>
            <h4>Starting XI (${totalLineupXp.toFixed(1)} xP):</h4>
            <ul style="padding-left: 1.2rem; margin-top: 0.5rem;">${xiHtml}</ul>
          </div>
          <div>
            <h4>Bench Substitutes:</h4>
            <ul style="padding-left: 1.2rem; margin-top: 0.5rem;">${benchHtml}</ul>
          </div>
        </div>
      </div>
    `;

    const applyWcBtn = document.getElementById("btn-apply-wc-squad");
    if (applyWcBtn) {
      applyWcBtn.addEventListener("click", async () => {
        const targetGw = state.selectedGameweek || state.activeGameweek || 1;
        const confirmed = confirm(
          `Apply this ${mode.toUpperCase()} squad for GW${targetGw}? This will play the ${mode} chip, overhaul your squad, and lock in your starting XI & captain.`
        );
        if (!confirmed) return;

        try {
          const allSquad = data.squad || [...xi, ...bench];
          const squadIds = allSquad.map(p => p.id);
          const starterIds = xi.map(p => p.id);
          const benchIds = bench.map(p => p.id);
          const capId = data.captain ? data.captain.id : starterIds[0];
          const vcId = data.vice_captain ? data.vice_captain.id : (starterIds[1] || starterIds[0]);

          const res = await api("/api/wildcard/apply", {
            method: "POST",
            body: JSON.stringify({
              team_id: state.activeTeamId,
              gameweek: targetGw,
              mode: mode,
              squad_ids: squadIds,
              starter_ids: starterIds,
              bench_ids: benchIds,
              captain_id: capId,
              vice_captain_id: vcId,
              bank_tenths: data.bank_remaining_tenths || 0,
            }),
          });

          showToast(res.message || `${mode.toUpperCase()} squad applied successfully!`);
          await refreshActiveTeamData();
          await loadDecisions();
          await loadLineup();
          const chipTab = document.getElementById("tab-chips");
          if (chipTab && chipTab.classList.contains("active")) {
            await loadChipStrategy();
          }
        } catch (err) {
          showToast(`Failed to apply ${mode}: ${err.message}`, true);
        }
      });
    }
  } catch (err) {
    container.innerHTML = `<p class="text-muted">Wildcard optimizer error: ${err.message}</p>`;
  }
}

// Multi-Gameweek Planner View
async function runPlanner() {
  const container = document.getElementById("plan-results-container");
  container.innerHTML = '<p class="text-muted">Evaluating rolling multi-gameweek transfer trajectories with beam search...</p>';

  const horizon = document.getElementById("plan-horizon").value;
  const risk = document.getElementById("plan-risk").value;
  const noHits = document.getElementById("plan-no-hits").checked;

  try {
    const data = await api(`/api/plan?team=${state.activeTeamId}&horizon=${horizon}&risk=${risk}&no_hits=${noHits}`);
    const best = data.best_plan;
    if (!best) {
      container.innerHTML = '<p class="text-muted">No plan generated.</p>';
      return;
    }

    const steps = best.gameweek_steps || best.steps || [];
    if (!steps.length) {
      container.innerHTML = '<p class="text-muted">No steps in plan.</p>';
      return;
    }

    const stepsHtml = steps.map((step, sIdx) => {
      let txText = '<span class="text-muted">Roll Transfer (Bank FT)</span>';
      if (step.transfers && step.transfers.length) {
        txText = step.transfers.map(t => {
          const outName = t.out ? `${t.out.name} (${t.out.team || ''})` : (t.outgoing_name || "Out");
          const inName = t.in ? `${t.in.name} (${t.in.team || ''})` : (t.incoming_name || "In");
          return `<span class="tx-out">OUT: ${outName}</span> ➔ <span class="tx-in">IN: ${inName}</span>`;
        }).join("<br/>");
      }

      const hits = step.transfer_hits !== undefined ? step.transfer_hits : (step.hits || 0);
      const hitStr = hits > 0 ? `(-${hits * 4}pt hit)` : "0 hits";
      const xpVal = step.lineup_xp !== undefined ? step.lineup_xp : (step.projected_xp || step.net_xp || 0);
      const ft = step.free_transfers_after !== undefined ? step.free_transfers_after : (step.ft_available !== undefined ? step.ft_available : 1);
      const bankStr = step.bank_after_fmt || `£${((step.bank_after_tenths || step.bank_tenths || 0) / 10).toFixed(1)}m`;
      const capStr = step.captain ? `${step.captain.name} (C)` : "";
      const formStr = step.formation ? ` · Formation: ${step.formation}` : "";

      let applyStep0Html = "";
      if (sIdx === 0) {
        applyStep0Html = `
          <div style="margin-top: 0.6rem;">
            <button type="button" class="btn btn-primary btn-sm btn-apply-plan-step0">
              ⚡ Apply GW${step.gameweek} Move
            </button>
          </div>
        `;
      }

      return `
        <div class="decision-entry" style="margin-bottom: 0.8rem;">
          <div class="decision-entry-header">
            <span><strong>Gameweek ${step.gameweek}</strong>${formStr}</span>
            <span class="badge badge-success">Projected: ${xpVal.toFixed(1)} xP <small>${hitStr}</small></span>
          </div>
          <div class="decision-entry-sub" style="margin: 0.3rem 0;">${txText}</div>
          <div class="decision-entry-sub">
            Captain: <strong>${capStr}</strong> | FTs Available: <strong>${ft}</strong> | Post-Move Bank: <strong>${bankStr}</strong>
          </div>
          ${applyStep0Html}
        </div>
      `;
    }).join("");

    const totalXp = best.total_net_xp !== undefined ? best.total_net_xp : (best.cumulative_net_xp || 0);
    const totalHits = best.total_hits !== undefined ? best.total_hits : 0;

    container.innerHTML = `
      <div class="panel card" style="margin-top: 1rem;">
        <div class="panel-header">
          <h3>Optimal ${horizon}-Gameweek Roadmap (Cumulative: ${totalXp.toFixed(1)} Net xP)</h3>
          <span class="badge badge-info">Total Hits: -${totalHits * 4} pts</span>
        </div>
        <div class="panel-body">${stepsHtml}</div>
      </div>
    `;

    // Apply Step 0 handler
    const applyStep0Btn = container.querySelector(".btn-apply-plan-step0");
    if (applyStep0Btn) {
      applyStep0Btn.addEventListener("click", async () => {
        const step0 = steps[0];
        const txs = step0.transfers || [];
        const txSummary = txs.length
          ? txs.map(t => `${t.out ? t.out.name : (t.outgoing_name || 'Out')} ➔ ${t.in ? t.in.name : (t.incoming_name || 'In')}`).join(", ")
          : "Roll Transfer (Bank FT)";
        const capName = step0.captain ? step0.captain.name : "None";

        const confirmed = confirm(
          `Apply recommended plan move for GW${step0.gameweek}?\nTransfers: ${txSummary}\nCaptain: ${capName}`
        );
        if (!confirmed) return;

        try {
          if (txs.length > 0) {
            const transfersPayload = txs.map(t => ({
              outgoing_id: t.out ? t.out.id : (t.outgoing_id || t.outgoing),
              incoming_id: t.in ? t.in.id : (t.incoming_id || t.incoming),
            }));
            await api("/api/transfers/execute", {
              method: "POST",
              body: JSON.stringify({
                team_id: state.activeTeamId,
                gameweek: step0.gameweek,
                transfers: transfersPayload,
              }),
            });
          }

          if (step0.captain) {
            setPitchCaptain(step0.captain.id);
          }

          showToast(`GW${step0.gameweek} plan move applied successfully!`);
          await refreshActiveTeamData();
          await loadDecisions();
          await loadLineup();
          await runPlanner();
        } catch (err) {
          showToast(`Failed to apply plan move: ${err.message}`, true);
        }
      });
    }
  } catch (err) {
    container.innerHTML = `<p class="text-muted">Planner error: ${err.message}</p>`;
  }
}

// Chip Strategy & Calendar View
async function loadChipStrategy() {
  const container = document.getElementById("chip-results-container");
  container.innerHTML = '<p class="text-muted">Evaluating Blank/Double gameweeks and computing optimal chip roadmap...</p>';

  const isHist = state.appMode === "historical";
  const startGwInput = document.getElementById("chip-start-gw");
  let startGw = startGwInput ? startGwInput.value : "";

  // If in historical mode, default start GW to historical session gameweek
  if (isHist && (!startGw || startGw === "")) {
    startGw = histState.gameweek || 1;
    if (startGwInput) startGwInput.value = startGw;
  } else if (!isHist && (!startGw || startGw === "")) {
    if (startGwInput && !startGwInput.value) {
      startGw = state.activeGameweek || 1;
      startGwInput.value = startGw;
    }
  }

  const startParam = startGw ? `&start_gw=${startGw}` : "";

  try {
    let data;
    if (isHist) {
      if (!histState.sessionId) {
        container.innerHTML = `
          <div class="panel card" style="margin-top: 1rem; padding: 1.5rem; text-align: center;">
            <p class="text-muted">No historical simulation session selected. Please select or create a historical simulation session to view its chip strategy.</p>
          </div>
        `;
        return;
      }
      data = await api(`/api/historical/simulations/${histState.sessionId}/chips?start_gw=${startGw}`);
    } else {
      data = await api(`/api/chips?team=${state.activeTeamId}${startParam}`);
    }

    const infoEl = document.getElementById("chip-status-info");
    if (infoEl) {
      const usedArr = data.used_chips || [];
      const availArr = data.available_chips || [];
      const usedText = usedArr.length ? `Used: ${usedArr.map(c => c.toUpperCase()).join(", ")}` : "None used yet";
      const availText = availArr.length ? `Remaining: ${availArr.map(c => c.toUpperCase()).join(", ")}` : "None left";
      infoEl.innerHTML = `<strong>${availText}</strong> <span class="text-muted">(${usedText})</span>`;
    }

    const sched = data.recommended_schedule || [];
    const schedHtml = sched.length
      ? sched.map(s => `<li><strong>GW${s.gameweek}</strong> [${s.gw_type}]: <strong>${s.chip.toUpperCase()}</strong> — ${s.reasoning}</li>`).join("")
      : "<li>No chips recommended in current horizon.</li>";

    const titlePrefix = isHist ? `Historical Simulation (${escapeHtml(data.session_id || histState.sessionId)})` : `Team: ${escapeHtml(data.team_id || state.activeTeamId)}`;

    container.innerHTML = `
      <div class="panel card" style="margin-top: 1rem;">
        <div class="panel-header">
          <h3>${titlePrefix} — Gameweeks ${data.segment} (Chips reset after GW19)</h3>
          <span class="badge badge-info">Available: ${data.available_chips.join(", ") || "None"}</span>
        </div>
        <div class="panel-body">
          <h4>Recommended Deployment Schedule:</h4>
          <ul style="padding-left: 1.2rem; margin: 0.5rem 0 1rem 0;">${schedHtml}</ul>
        </div>
      </div>
    `;
  } catch (err) {
    container.innerHTML = `<p class="text-muted">Chip strategy error: ${err.message}</p>`;
  }
}

// Undo / Revert Current Gameweek Changes
async function handleUndoGameweek() {
  const targetGw = state.selectedGameweek || state.activeGameweek || 1;
  const confirmed = confirm(
    `Are you sure you want to reset all changes for GW${targetGw} and revert your squad to the status of the previous gameweek?`
  );
  if (!confirmed) return;

  try {
    const res = await api("/api/decisions/undo", {
      method: "POST",
      body: JSON.stringify({
        team_id: state.activeTeamId,
        gameweek: targetGw,
      }),
    });

    showToast(res.message || `Reverted squad to GW${res.reverted_to_gameweek} state!`);
    await refreshActiveTeamData();
    await loadDecisions();
    const chipTab = document.getElementById("tab-chips");
    if (chipTab && chipTab.classList.contains("active")) {
      await loadChipStrategy();
    }
  } catch (err) {
    showToast(`Undo failed: ${err.message}`, true);
  }
}

// Evaluation & Regret View
async function loadEvaluation() {
  const container = document.getElementById("eval-results-container");
  container.innerHTML = '<p class="text-muted">Evaluating historical predictions and manager decisions...</p>';

  const gwVal = document.getElementById("eval-gw").value;
  const gwParam = gwVal ? `&gameweek=${gwVal}` : "";

  try {
    const data = await api(`/api/evaluate?team=${state.activeTeamId}${gwParam}`);

    if (data.finalized_gameweeks !== undefined) {
      // Season summary
      container.innerHTML = `
        <div class="panel card" style="margin-top: 1rem;">
          <div class="panel-header">
            <h3>Season Accuracy & Decision Evaluation (${data.finalized_gameweeks} Finalized GWs)</h3>
          </div>
          <div class="panel-body">
            <div class="two-col-layout">
              <div>
                <p>Total Predicted: <strong>${data.total_predicted_xp.toFixed(1)} xP</strong></p>
                <p>Total Actual Points: <strong>${data.total_actual_points.toFixed(1)} pts</strong></p>
                <p>Lineup MAE: <strong>${data.lineup_mae.toFixed(2)} pts/GW</strong></p>
              </div>
              <div>
                <p>Lineup RMSE: <strong>${data.lineup_rmse.toFixed(2)} pts/GW</strong></p>
                <p>Mean Prediction Bias: <strong>${data.mean_prediction_bias.toFixed(2)}</strong> (${data.bias_interpretation})</p>
                <p>Transfer Hits: <strong>${data.total_transfer_hits}</strong> (-${data.total_transfer_hits * 4} pts)</p>
              </div>
            </div>
          </div>
        </div>
      `;
    } else {
      // Single GW Evaluation
      const cap = data.captaincy || {};
      const bench = data.bench || {};
      container.innerHTML = `
        <div class="panel card" style="margin-top: 1rem;">
          <div class="panel-header">
            <h3>Gameweek ${data.gameweek} Model & Manager Evaluation</h3>
          </div>
          <div class="panel-body">
            <p>Lineup Score: <strong>${data.actual_lineup_score} pts</strong> (Predicted: ${data.predicted_lineup_xp.toFixed(1)} xP)</p>
            <p>Captain: <strong>${cap.captain_name}</strong> (${cap.captain_actual_points} pts) vs Optimal: <strong>${cap.optimal_captain_name}</strong> (${cap.optimal_captain_actual_points} pts) ➔ Regret: <strong>${cap.captaincy_regret_points} pts</strong></p>
            <p>Bench Stranded: <strong>${bench.total_bench_points} pts</strong> ➔ Regret: <strong>${bench.bench_regret_points} pts</strong></p>
          </div>
        </div>
      `;
    }
  } catch (err) {
    container.innerHTML = `<p class="text-muted">Evaluation error: ${err.message}</p>`;
  }
}

// Team Creation Modal
function initModal() {
  const modal = document.getElementById("modal-create-team");
  const openBtn = document.getElementById("btn-open-create-team");
  const closeBtn = document.getElementById("btn-close-modal");
  const cancelBtn = document.getElementById("btn-cancel-modal");
  const form = document.getElementById("form-create-team");

  openBtn.addEventListener("click", () => modal.classList.remove("hidden"));
  [closeBtn, cancelBtn].forEach(b => b.addEventListener("click", () => modal.classList.add("hidden")));

  form.addEventListener("submit", async e => {
    e.preventDefault();
    const name = document.getElementById("new-team-name").value.trim();
    const manager = document.getElementById("new-team-manager").value.trim();
    const copyFrom = document.getElementById("new-team-copy").value || null;
    const activate = document.getElementById("new-team-activate").checked;

    try {
      const res = await api("/api/teams/create", {
        method: "POST",
        body: JSON.stringify({ name, manager, copy_from: copyFrom, activate }),
      });
      modal.classList.add("hidden");
      form.reset();
      showToast(`Created team '${res.name}'!`);
      await loadTeams();
    } catch (err) {
      showToast(`Error creating team: ${err.message}`, true);
    }
  });

  // Team Renaming Modal
  const renameModal = document.getElementById("modal-rename-team");
  const openRenameBtn = document.getElementById("btn-rename-team");
  const closeRenameBtn = document.getElementById("btn-close-rename-modal");
  const cancelRenameBtn = document.getElementById("btn-cancel-rename-modal");
  const renameForm = document.getElementById("form-rename-team");
  const editTeamNameInput = document.getElementById("edit-team-name");

  if (openRenameBtn && renameModal) {
    openRenameBtn.addEventListener("click", () => {
      const activeObj = state.teams.find(t => t.team_id === state.activeTeamId);
      if (editTeamNameInput) {
        editTeamNameInput.value = activeObj ? activeObj.name : "";
      }
      renameModal.classList.remove("hidden");
    });
    [closeRenameBtn, cancelRenameBtn].forEach(b => {
      if (b) b.addEventListener("click", () => renameModal.classList.add("hidden"));
    });

    if (renameForm) {
      renameForm.addEventListener("submit", async e => {
        e.preventDefault();
        const newName = editTeamNameInput.value.trim();
        if (!newName) {
          showToast("Team name cannot be empty.", true);
          return;
        }

        try {
          const res = await api("/api/teams/rename", {
            method: "POST",
            body: JSON.stringify({ team_id: state.activeTeamId, name: newName }),
          });
          renameModal.classList.add("hidden");
          showToast(`Renamed team to '${res.name}'!`);
          await loadTeams();
        } catch (err) {
          showToast(`Error renaming team: ${err.message}`, true);
        }
      });
    }
  }

  // Player Stats Modal
  const psModal = document.getElementById("modal-player-stats");
  const psClose = document.getElementById("btn-close-player-stats");
  const psFooterClose = document.getElementById("btn-close-ps-footer");
  if (psModal) {
    [psClose, psFooterClose].forEach(b => {
      if (b) b.addEventListener("click", () => psModal.classList.add("hidden"));
    });
  }

  const btnPsCap = document.getElementById("btn-ps-make-cap");
  if (btnPsCap) {
    btnPsCap.addEventListener("click", () => {
      if (inspectingPlayerId) {
        setPitchCaptain(inspectingPlayerId);
        showToast("Player selected as Captain!");
        if (psModal) psModal.classList.add("hidden");
      }
    });
  }

  const btnPsVc = document.getElementById("btn-ps-make-vc");
  if (btnPsVc) {
    btnPsVc.addEventListener("click", () => {
      if (inspectingPlayerId) {
        setPitchViceCaptain(inspectingPlayerId);
        showToast("Player selected as Vice-Captain!");
        if (psModal) psModal.classList.add("hidden");
      }
    });
  }
}

// Global Event Listeners
function initEventListeners() {
  // Team switcher dropdown
  document.getElementById("team-select").addEventListener("change", e => {
    switchTeam(e.target.value);
  });

  // Delete team button
  document.getElementById("btn-delete-team").addEventListener("click", deleteActiveTeam);

  // Sync official data
  document.getElementById("btn-sync-data").addEventListener("click", async () => {
    showToast("Syncing latest official FPL data...");
    try {
      const res = await api("/api/update-data", { method: "POST" });
      showToast(`FPL data updated (${res.players} players synced)!`);
      await refreshActiveTeamData();
    } catch (err) {
      showToast(`Data sync failed: ${err.message}`, true);
    }
  });

  // Sync live scores
  document.getElementById("btn-sync-scores").addEventListener("click", async () => {
    showToast("Fetching live matchday scores from FPL...");
    try {
      const res = await api("/api/update-scores", { method: "POST" });
      showToast(`Matchday scores updated (${res.players_updated} players)!`);
      await refreshActiveTeamData();
    } catch (err) {
      showToast(`Scores fetch failed: ${err.message}`, true);
    }
  });

  // Lineup Gameweek refresh and selector
  const gwSelectInput = document.getElementById("lineup-gw-select");
  if (gwSelectInput) {
    gwSelectInput.addEventListener("change", e => {
      const val = parseInt(e.target.value);
      if (val && val >= 1 && val <= 38) {
        loadLineup(val, "auto");
      }
    });
  }

  document.getElementById("btn-refresh-lineup").addEventListener("click", () => {
    const gw = parseInt(document.getElementById("lineup-gw-select").value) || state.activeGameweek;
    loadLineup(gw, "model");
  });

  // Decision Logger Form
  document.getElementById("form-log-decision").addEventListener("submit", handleDecisionSubmit);
  document.getElementById("btn-refresh-decisions").addEventListener("click", loadDecisions);

  // Pitch Save and Cancel Sub
  const btnSavePitch = document.getElementById("btn-save-pitch-lineup");
  if (btnSavePitch) btnSavePitch.addEventListener("click", savePitchLineup);

  const btnUndoPitch = document.getElementById("btn-undo-pitch-lineup");
  if (btnUndoPitch) btnUndoPitch.addEventListener("click", handleUndoGameweek);

  const btnCancelSub = document.getElementById("btn-cancel-sub");
  if (btnCancelSub) btnCancelSub.addEventListener("click", cancelSubstitution);

  const btnUndoDec = document.getElementById("btn-undo-dec-gw");
  if (btnUndoDec) btnUndoDec.addEventListener("click", handleUndoGameweek);

  // Executed Transfers Handlers
  const btnExecTrade = document.getElementById("btn-execute-trade");
  if (btnExecTrade) btnExecTrade.addEventListener("click", handleExecuteTrade);

  const txOut = document.getElementById("tx-exec-out");
  if (txOut) txOut.addEventListener("change", updateTradeSummary);

  const txIn = document.getElementById("tx-exec-in");
  if (txIn) txIn.addEventListener("input", updateTradeSummary);

  const decGwInput = document.getElementById("dec-gw");
  if (decGwInput) {
    decGwInput.addEventListener("change", async e => {
      const gw = parseInt(e.target.value);
      if (gw) {
        try {
          const decData = await api(`/api/decisions?team=${state.activeTeamId}`);
          const list = decData.decisions || [];
          const dec = list.find(d => d.gameweek === gw);
          renderExecutedTransfersBox(dec && dec.transfers ? dec.transfers : []);
          if (dec) {
            const capSelect = document.getElementById("dec-captain");
            const vcSelect = document.getElementById("dec-vc");
            if (capSelect && dec.captain_name) capSelect.value = dec.captain_name;
            if (vcSelect && dec.vice_captain_name) vcSelect.value = dec.vice_captain_name;
            const chipSelect = document.getElementById("dec-chip");
            if (chipSelect) chipSelect.value = dec.chip_played || "";
            const hitsInput = document.getElementById("dec-hits");
            if (hitsInput) {
              hitsInput.value = "";
              const isFree = dec.chip_played && ["wildcard", "wc", "freehit", "free_hit", "fh"].some(c => dec.chip_played.toLowerCase().includes(c));
              hitsInput.placeholder = isFree ? "0 (Free with Chip)" : `Auto-calculated (${dec.transfer_hits || 0})`;
            }
          }
        } catch (err) {}
      }
    });
  }

  const decChipSelect = document.getElementById("dec-chip");
  if (decChipSelect) {
    decChipSelect.addEventListener("change", () => {
      const hitsInput = document.getElementById("dec-hits");
      if (hitsInput) {
        const val = (decChipSelect.value || "").toLowerCase();
        const isFree = ["wildcard", "wc", "freehit", "free_hit", "fh"].some(c => val.includes(c));
        if (isFree) {
          hitsInput.value = "0";
          hitsInput.placeholder = "0 (Free with Chip)";
        } else if (hitsInput.value === "0") {
          hitsInput.value = "";
          hitsInput.placeholder = "Auto-calculated";
        }
      }
    });
  }

  // Transfers & Studio Buttons
  const btnRunTx = document.getElementById("btn-run-suggest-tx");
  if (btnRunTx) btnRunTx.addEventListener("click", runSuggestTransfers);
  const btnRunWc = document.getElementById("btn-run-wildcard");
  if (btnRunWc) btnRunWc.addEventListener("click", runWildcard);
  const btnRunPlan = document.getElementById("btn-run-plan");
  if (btnRunPlan) btnRunPlan.addEventListener("click", runPlanner);
  const btnRunChips = document.getElementById("btn-run-chip-strategy");
  if (btnRunChips) btnRunChips.addEventListener("click", loadChipStrategy);
  document.getElementById("btn-run-eval").addEventListener("click", loadEvaluation);

  // V0.6 Live Matchday & AI Advisor Buttons
  const btnRefreshLive = document.getElementById("btn-refresh-live");
  if (btnRefreshLive) btnRefreshLive.addEventListener("click", () => loadLiveMatchday(false));

  const btnFetchFpl = document.getElementById("btn-fetch-fpl-scores");
  if (btnFetchFpl) btnFetchFpl.addEventListener("click", () => loadLiveMatchday(true));

  const btnRunAdvisor = document.getElementById("btn-run-advisor");
  if (btnRunAdvisor) btnRunAdvisor.addEventListener("click", runAdvisor);

  const btnViewDossier = document.getElementById("btn-view-dossier");
  if (btnViewDossier) btnViewDossier.addEventListener("click", viewManagerDossier);

  const advProvider = document.getElementById("adv-provider");
  if (advProvider) advProvider.addEventListener("change", updateProviderKeyPlaceholder);

  const btnToggleKey = document.getElementById("btn-toggle-key-visibility");
  if (btnToggleKey) {
    btnToggleKey.addEventListener("click", () => {
      const keyInput = document.getElementById("adv-api-key");
      if (!keyInput) return;
      if (keyInput.type === "password") {
        keyInput.type = "text";
        btnToggleKey.textContent = "🙈";
      } else {
        keyInput.type = "password";
        btnToggleKey.textContent = "👁️";
      }
    });
  }

  const advApiKey = document.getElementById("adv-api-key");
  if (advApiKey) {
    advApiKey.addEventListener("input", () => {
      const provSelect = document.getElementById("adv-provider");
      const provider = provSelect ? provSelect.value : "";
      const val = advApiKey.value.trim();
      try {
        if (provider === "gemini") localStorage.setItem("fpl_advisor_api_key_gemini", val);
        else if (provider === "openai") localStorage.setItem("fpl_advisor_api_key_openai", val);
        else if (provider === "openrouter" || val.startsWith("sk-or-")) localStorage.setItem("fpl_advisor_api_key_openrouter", val);
      } catch (_) {}
    });
  }

  const advModel = document.getElementById("adv-model");
  if (advModel) {
    advModel.addEventListener("change", () => {
      const provSelect = document.getElementById("adv-provider");
      const provider = provSelect ? provSelect.value : "";
      if (provider && advModel.value) {
        try {
          localStorage.setItem(`fpl_advisor_model_${provider}`, advModel.value);
        } catch (_) {}
      }
    });
  }
}

// ==========================================
// TAB 7: LIVE MATCHDAY TRACKER CONTROLLER
// ==========================================

async function loadLiveMatchday(force = false) {
  const container = document.getElementById("live-results-container");
  if (!container) return;

  const gwInput = document.getElementById("live-gw");
  let gw = gwInput ? parseInt(gwInput.value) : null;
  if (!gw) gw = state.activeGameweek;
  if (gwInput && !gwInput.value) gwInput.value = gw;

  container.innerHTML = `
    <div style="padding: 2.5rem 1rem; text-align: center; color: var(--text-muted);">
      <div class="spinner" style="margin: 0 auto 1rem auto; width: 32px; height: 32px; border: 3px solid var(--border-color); border-top-color: var(--accent-green); border-radius: 50%; animation: spin 0.8s linear infinite;"></div>
      <p>Loading real-time matchday performance for Gameweek ${gw}...</p>
    </div>
  `;

  try {
    const data = await api(`/api/live?team=${state.activeTeamId}&gameweek=${gw}${force ? '&force=true' : ''}`);
    renderLiveMatchday(data);
    const updatedEl = document.getElementById("live-last-updated");
    if (updatedEl) {
      const d = new Date(data.generated_at);
      updatedEl.textContent = `Updated: ${d.toLocaleTimeString()}`;
    }
  } catch (err) {
    container.innerHTML = `
      <div class="alert alert-danger" style="margin-top: 1rem;">
        Failed to load live matchday data: ${escapeHtml(err.message)}
      </div>
    `;
  }
}

function renderLiveMatchday(data) {
  const container = document.getElementById("live-results-container");
  if (!container) return;

  const net = data.net_points || 0;
  const gross = data.gross_points || 0;
  const hits = data.hit_cost || 0;
  const cap = data.captain || {};
  const chip = data.chip_played;
  const autosubs = data.autosubs || [];
  const starters = data.starters || [];
  const bench = data.bench || [];
  const rankAcc = data.rank_accelerators || [];

  let html = `
    <div class="live-hero-grid">
      <div class="live-hero-card">
        <div class="live-hero-label">Live Score</div>
        <div class="live-hero-value">${net} <span style="font-size: 1.1rem; font-weight: 600; color: var(--text-secondary);">pts</span></div>
        <div class="live-hero-sub">${hits > 0 ? `Gross: ${gross} pts (-${hits} hit deduction)` : 'No transfer hits taken'}</div>
      </div>
      <div class="live-hero-card">
        <div class="live-hero-label">Armband (Captain)</div>
        <div style="font-size: 1.4rem; font-weight: 800; color: var(--accent-gold); line-height: 1.2;">
          👑 ${escapeHtml(cap.name || 'Unknown')} <span style="font-size: 0.95rem; color: var(--text-primary);">(${cap.multiplier || 2}x)</span>
        </div>
        <div class="live-hero-sub">
          <strong>${cap.points || 0} pts</strong> ${cap.promoted_from_vice ? '• <span style="color: #60a5fa;">Promoted from Vice</span>' : ''}
        </div>
      </div>
      <div class="live-hero-card">
        <div class="live-hero-label">Active Chip</div>
        <div style="font-size: 1.4rem; font-weight: 800; color: ${chip ? 'var(--accent-purple)' : 'var(--text-muted)'}; line-height: 1.2;">
          ${chip ? escapeHtml(chip.toUpperCase()) : 'None Active'}
        </div>
        <div class="live-hero-sub">${chip ? 'Chip modifier applied' : 'Standard matchday scoring'}</div>
      </div>
    </div>
  `;

  if (autosubs.length > 0) {
    html += `
      <div class="live-autosub-banner">
        <div class="live-autosub-title">🔄 Automatic Substitutions Applied (${autosubs.length})</div>
        <div style="display: flex; flex-direction: column; gap: 0.35rem; font-size: 0.85rem;">
          ${autosubs.map(s => `
            <div>
              • <strong>OUT</strong>: ${escapeHtml(s.out.name)} (${s.out.position}) ➔ 
              <strong>IN</strong>: <strong style="color: var(--accent-green);">${escapeHtml(s.in.name)}</strong> (${s.in.position}, +${s.in.points} pts): 
              <em>${escapeHtml(s.reason)}</em>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }

  html += `
    <h3 style="margin: 1.5rem 0 0.8rem 0; font-size: 1.05rem; display: flex; align-items: center; gap: 6px;">
      <span>🏟️ Starting XI Performance</span>
    </h3>
    <div class="live-table-container">
      <table class="live-table">
        <thead>
          <tr>
            <th>Pos</th>
            <th>Player</th>
            <th>Team</th>
            <th>Min</th>
            <th>G</th>
            <th>A</th>
            <th>CS</th>
            <th>GC</th>
            <th>Bonus</th>
            <th>BPS</th>
            <th>Status</th>
            <th style="text-align: right;">Points</th>
          </tr>
        </thead>
        <tbody>
          ${starters.map(p => {
            const isCap = p.role && p.role.includes("CAPTAIN");
            const isSubbed = p.subbed_in;
            const badge = isCap ? ' <span class="badge" style="background: var(--accent-gold); color: #000; font-weight: 800; font-size: 0.7rem; padding: 2px 4px; border-radius: 3px;">C</span>' : (p.role === "VICE_CAPTAIN" ? ' <span class="badge" style="background: #64748b; font-size: 0.7rem; padding: 2px 4px; border-radius: 3px;">VC</span>' : '');
            const subBadge = isSubbed ? ' <span class="badge" style="background: #3b82f6; font-size: 0.7rem; padding: 2px 4px; border-radius: 3px;">🔄 SUB IN</span>' : '';
            const statusHtml = p.match_finished ? '<span class="live-status-finished">Finished</span>' : '<span class="live-status-live">● Live/Upcoming</span>';
            return `
              <tr style="${isSubbed ? 'background: rgba(59, 130, 246, 0.05);' : ''}">
                <td><span class="pos-badge pos-${p.position.toLowerCase()}">${p.position}</span></td>
                <td><strong>${escapeHtml(p.name)}</strong>${badge}${subBadge}</td>
                <td><span class="team-tag">${p.team}</span></td>
                <td>${p.minutes}'</td>
                <td>${p.goals}</td>
                <td>${p.assists}</td>
                <td>${p.clean_sheet}</td>
                <td>${p.goals_conceded}</td>
                <td>${p.bonus}</td>
                <td>${p.bps}</td>
                <td>${statusHtml}</td>
                <td style="text-align: right; font-weight: 800; font-size: 1.05rem; color: ${p.points > 0 ? 'var(--accent-green)' : 'var(--text-primary)'};">${p.points}</td>
              </tr>
            `;
          }).join('')}
        </tbody>
      </table>
    </div>

    <h3 style="margin: 1.5rem 0 0.8rem 0; font-size: 1.05rem; display: flex; align-items: center; gap: 6px;">
      <span>🪑 Bench Substitutes</span>
    </h3>
    <div class="live-table-container">
      <table class="live-table">
        <thead>
          <tr>
            <th>Order</th>
            <th>Pos</th>
            <th>Player</th>
            <th>Team</th>
            <th>Min</th>
            <th>Raw Pts</th>
            <th>Counted in Total</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          ${bench.map(p => {
            const countedBadge = p.counted_in_total ? '<span style="color: var(--accent-green); font-weight: 700;">✅ Yes</span>' : '<span style="color: var(--text-muted);">No</span>';
            const statusHtml = p.match_finished ? '<span class="live-status-finished">Finished</span>' : '<span class="live-status-live">● Live/Upcoming</span>';
            return `
              <tr>
                <td>#${p.order}</td>
                <td><span class="pos-badge pos-${p.position.toLowerCase()}">${p.position}</span></td>
                <td>${escapeHtml(p.name)} ${p.subbed_in ? '<span class="badge" style="background: #3b82f6; font-size: 0.7rem; padding: 2px 4px; border-radius: 3px;">🔄 Subbed In</span>' : ''}</td>
                <td><span class="team-tag">${p.team}</span></td>
                <td>${p.minutes}'</td>
                <td><strong>${p.raw_points}</strong></td>
                <td>${countedBadge}</td>
                <td>${statusHtml}</td>
              </tr>
            `;
          }).join('')}
        </tbody>
      </table>
    </div>
  `;

  if (rankAcc.length > 0) {
    html += `
      <h3 style="margin: 1.5rem 0 0.8rem 0; font-size: 1.05rem; display: flex; align-items: center; gap: 6px;">
        <span>🚀 Rank Accelerators (Top Swing Leverage)</span>
      </h3>
      <div class="rank-accelerators-grid">
        ${rankAcc.map(a => `
          <div class="rank-accelerator-card">
            <div style="font-weight: 700; font-size: 0.95rem;">⭐ ${escapeHtml(a.name)} <span class="team-tag">${a.team}</span></div>
            <div style="font-size: 0.8rem; color: var(--text-secondary); margin: 0.2rem 0;">
              Scored <strong>${a.points} pts</strong> (EO: ${a.eo_pct}%)
            </div>
            <div style="font-size: 0.85rem; font-weight: 800; color: var(--accent-green);">
              +${a.rank_delta_pts} pts rank leverage
            </div>
          </div>
        `).join('')}
      </div>
    `;
  }

  container.innerHTML = html;
}

// ==========================================
// TAB 8: AI ADVISOR & ANALYTICAL DOSSIER
// ==========================================

const PROVIDER_MODELS = {
  openrouter: [
    { id: "meta-llama/llama-3.3-70b-instruct", name: "Llama 3.3 70B (Default)" },
    { id: "deepseek/deepseek-chat", name: "DeepSeek V3" },
    { id: "openai/gpt-4o-mini", name: "GPT-4o Mini" },
    { id: "deepseek/deepseek-r1", name: "DeepSeek R1 (Reasoning) *" },
  ],
  gemini: [
    { id: "gemini-1.5-flash-latest", name: "Gemini 1.5 Flash (Default)" },
    { id: "gemini-1.5-pro-latest", name: "Gemini 1.5 Pro" },
    { id: "gemini-2.0-flash", name: "Gemini 2.0 Flash" },
  ],
  openai: [
    { id: "gpt-4o-mini", name: "GPT-4o Mini (Default)" },
    { id: "gpt-4o", name: "GPT-4o" },
    { id: "o3-mini", name: "o3-mini" },
  ],
};

function updateProviderKeyPlaceholder() {
  const provSelect = document.getElementById("adv-provider");
  const keyInput = document.getElementById("adv-api-key");
  const modelSelect = document.getElementById("adv-model");
  const modelGroup = document.getElementById("adv-model-group");
  if (!provSelect || !keyInput) return;
  const val = provSelect.value;

  // Clean up legacy URL strings if any
  try {
    const legacyKey = localStorage.getItem("fpl_advisor_api_key") || "";
    if (legacyKey.startsWith("http")) {
      localStorage.removeItem("fpl_advisor_api_key");
    }
  } catch (_) {}

  // Populate model selector
  if (modelSelect && modelGroup) {
    if (val === "heuristic") {
      modelGroup.style.display = "none";
    } else {
      modelGroup.style.display = "inline-flex";
      modelSelect.innerHTML = '<option value="">Default Model</option>';
      const models = PROVIDER_MODELS[val] || [];
      const savedModel = localStorage.getItem(`fpl_advisor_model_${val}`) || "";
      const validModelIds = new Set(models.map(m => m.id));
      if (savedModel && !validModelIds.has(savedModel)) {
        localStorage.removeItem(`fpl_advisor_model_${val}`);
      }
      const activeSaved = validModelIds.has(savedModel) ? savedModel : "";
      models.forEach(m => {
        const opt = document.createElement("option");
        opt.value = m.id;
        opt.textContent = m.name;
        if (m.name.includes("*")) {
          opt.title = "Requires paid account credits on OpenRouter";
        }
        if (m.id === activeSaved) opt.selected = true;
        modelSelect.appendChild(opt);
      });
    }
  }

  if (val === "heuristic") {
    keyInput.placeholder = "(Not required)";
    keyInput.disabled = true;
    keyInput.value = "";
  } else if (val === "openrouter") {
    keyInput.placeholder = "OpenRouter Key (sk-or-v1-...)";
    keyInput.disabled = false;
    try {
      keyInput.value = localStorage.getItem("fpl_advisor_api_key_openrouter") || "";
    } catch (_) {}
  } else if (val === "gemini") {
    keyInput.placeholder = "Gemini API Key (AIza...)";
    keyInput.disabled = false;
    try {
      keyInput.value = localStorage.getItem("fpl_advisor_api_key_gemini") || "";
    } catch (_) {}
  } else if (val === "openai") {
    keyInput.placeholder = "OpenAI API Key (sk-...)";
    keyInput.disabled = false;
    try {
      keyInput.value = localStorage.getItem("fpl_advisor_api_key_openai") || "";
    } catch (_) {}
  } else {
    keyInput.placeholder = "Optional API Key (AIza / sk- / sk-or-)";
    keyInput.disabled = false;
    keyInput.value = "";
  }
}

function loadAdvisor() {
  const advGw = document.getElementById("adv-gw");
  if (advGw && !advGw.value) {
    advGw.value = state.activeGameweek || 1;
  }
  updateProviderKeyPlaceholder();
}

async function runAdvisor() {
  const container = document.getElementById("advisor-results-container");
  if (!container) return;

  const personaSelect = document.getElementById("adv-persona");
  const providerSelect = document.getElementById("adv-provider");
  const apiKeyInput = document.getElementById("adv-api-key");
  const modelSelect = document.getElementById("adv-model");
  const gwInput = document.getElementById("adv-gw") || document.getElementById("live-gw");
  let gw = gwInput ? parseInt(gwInput.value) : null;
  if (!gw) gw = state.activeGameweek;
  if (gwInput && !gwInput.value) gwInput.value = gw;

  const persona = personaSelect ? personaSelect.value : "devil_advocate";
  const provider = providerSelect ? providerSelect.value : "auto";
  let apiKey = apiKeyInput ? apiKeyInput.value.trim() : null;
  if (apiKey && (apiKey.startsWith("http://") || apiKey.startsWith("https://"))) {
    apiKey = null;
  }

  const selectedModel = modelSelect ? modelSelect.value : "";
  if (selectedModel) {
    try {
      localStorage.setItem(`fpl_advisor_model_${provider}`, selectedModel);
    } catch (_) {}
  }

  if (apiKey) {
    try {
      if (provider === "openrouter" || apiKey.startsWith("sk-or-")) localStorage.setItem("fpl_advisor_api_key_openrouter", apiKey);
      else if (provider === "gemini") localStorage.setItem("fpl_advisor_api_key_gemini", apiKey);
      else if (provider === "openai") localStorage.setItem("fpl_advisor_api_key_openai", apiKey);
    } catch (_) {}
  }

  container.innerHTML = `
    <div style="padding: 2.5rem 1rem; text-align: center; color: var(--text-muted);">
      <div class="spinner" style="margin: 0 auto 1rem auto; width: 32px; height: 32px; border: 3px solid var(--border-color); border-top-color: var(--accent-purple); border-radius: 50%; animation: spin 0.8s linear infinite;"></div>
      <p>Synthesizing briefing dossier and consulting ${persona.replace(/_/g, ' ').toUpperCase()} advisor using ${provider.toUpperCase()} engine${selectedModel ? ` (${selectedModel})` : ''}...</p>
    </div>
  `;

  try {
    const payload = {
      team_id: state.activeTeamId,
      gameweek: gw,
      persona: persona,
      provider: provider,
    };
    if (apiKey) payload.api_key = apiKey;
    if (selectedModel) payload.model = selectedModel;

    const data = await api("/api/advise", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    renderAdvisorResults(data);
    showToast("AI Strategic Advisory Generated!");
  } catch (err) {
    let extraTip = "";
    if (err.message && (err.message.includes("401") || err.message.toLowerCase().includes("authentication") || err.message.toLowerCase().includes("unauthorized"))) {
      extraTip = `
        <div style="margin-top: 0.6rem; font-size: 0.85rem; line-height: 1.4; color: var(--text-secondary);">
          💡 <em>Authentication error for <strong>${escapeHtml(provider.toUpperCase())}</strong>. Click 👁️ in the toolbar to verify the entered API key. If using OpenRouter, ensure your key begins with <code>sk-or-v1-</code>.</em>
        </div>
      `;
    }
    container.innerHTML = `
      <div class="alert alert-danger" style="margin-top: 1rem;">
        <strong>Advisor Error:</strong> ${escapeHtml(err.message)}
        ${extraTip}
      </div>
    `;
    showToast(err.message, true);
    if (err.message && err.message.toLowerCase().includes("api key") && apiKeyInput) {
      apiKeyInput.focus();
    }
  }
}

function renderAdvisorResults(data) {
  const container = document.getElementById("advisor-results-container");
  if (!container) return;

  const val = data.validation || {};
  const isLegal = val.is_legal !== false;
  const errors = val.errors || [];
  const critiques = data.critique_points || [];
  const tactical = data.tactical_notes || [];
  const transfers = data.proposed_transfers || [];
  const cap = data.proposed_captain;
  const vc = data.proposed_vice_captain;

  const verdictBadge = isLegal
    ? `<span class="advisor-verdict-approved">🟢 APPROVED (LEGAL & WITHIN BUDGET)</span>`
    : `<span class="advisor-verdict-rejected">🔴 REJECTED (${errors.length} RULE VIOLATIONS)</span>`;

  let html = `
    <div class="advisor-card">
      <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 1rem;">
        <div>
          <h3 style="margin: 0; font-size: 1.25rem;">
            Strategic Advisory — Gameweek ${data.gameweek}
          </h3>
          <div style="font-size: 0.82rem; color: var(--text-secondary); margin-top: 0.2rem;">
            Persona: <strong>${escapeHtml((data.persona || '').replace(/_/g, ' ').toUpperCase())}</strong> | 
            Engine: <code>${escapeHtml(data.provider_used || 'heuristic')}</code>
          </div>
        </div>
        <div>${verdictBadge}</div>
      </div>

      <div style="background: var(--bg-input); border-radius: 8px; padding: 1.2rem; margin-bottom: 1.2rem;">
        <div style="font-size: 0.8rem; font-weight: 700; color: var(--accent-purple); text-transform: uppercase; margin-bottom: 0.4rem;">
          Executive Tactical Critique
        </div>
        <div class="advisor-markdown-content" style="line-height: 1.55;">${formatMarkdown(data.analysis_markdown)}</div>
      </div>
  `;

  if (critiques.length > 0) {
    html += `
      <div style="margin-bottom: 1.2rem;">
        <h4 style="font-size: 0.95rem; margin-bottom: 0.5rem; color: #fbbf24;">⚡ Key Contrarian & Trap Risks</h4>
        <ul style="padding-left: 1.2rem; display: flex; flex-direction: column; gap: 0.35rem; font-size: 0.88rem;">
          ${critiques.map(c => `<li>${formatMarkdown(c)}</li>`).join('')}
        </ul>
      </div>
    `;
  }

  if (tactical.length > 0) {
    html += `
      <div style="margin-bottom: 1.2rem;">
        <h4 style="font-size: 0.95rem; margin-bottom: 0.5rem; color: #38bdf8;">📋 Tactical & Press Conference Matchup Signals</h4>
        <ul style="padding-left: 1.2rem; display: flex; flex-direction: column; gap: 0.35rem; font-size: 0.88rem;">
          ${tactical.map(t => `<li>${formatMarkdown(t)}</li>`).join('')}
        </ul>
      </div>
    `;
  }

  html += `
      <div style="margin-top: 1.2rem; padding-top: 1.2rem; border-top: 1px solid var(--border-color);">
        <h4 style="font-size: 0.95rem; margin-bottom: 0.6rem;">🎯 Proposed Strategic Actions</h4>
        <div style="display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 0.8rem;">
          <div style="background: var(--bg-input); border-radius: 6px; padding: 0.6rem 1rem;">
            <span style="font-size: 0.75rem; color: var(--text-muted); display: block;">RECOMMENDED CAPTAIN</span>
            <strong style="color: var(--accent-gold); font-size: 1.05rem;">👑 ${escapeHtml(cap || 'None')}</strong>
            ${vc ? `<span style="font-size: 0.8rem; color: var(--text-secondary); margin-left: 6px;">(VC: ${escapeHtml(vc)})</span>` : ''}
          </div>
        </div>

        <div style="font-size: 0.88rem;">
          <strong>Transfers:</strong>
          ${transfers.length > 0 ? `
            <ul style="padding-left: 1.2rem; margin-top: 0.4rem; display: flex; flex-direction: column; gap: 0.35rem;">
              ${transfers.map(t => `
                <li>
                  🔄 OUT: <strong>${escapeHtml(t.out)}</strong> ➔ IN: <strong style="color: var(--accent-green);">${escapeHtml(t.in)}</strong>
                  ${t.rationale ? ` — <span style="color: var(--text-secondary);">${escapeHtml(t.rationale)}</span>` : ''}
                </li>
              `).join('')}
            </ul>
          ` : '<span style="color: var(--text-muted); margin-left: 6px;">No transfers suggested (Roll free transfer).</span>'}
        </div>
      </div>

      <div style="margin-top: 1.2rem; padding: 0.9rem 1.1rem; border-radius: 8px; background: ${isLegal ? 'rgba(16, 185, 129, 0.08)' : 'rgba(239, 68, 68, 0.08)'}; border: 1px solid ${isLegal ? 'rgba(16, 185, 129, 0.25)' : 'rgba(239, 68, 68, 0.25)'};">
        <div style="font-weight: 700; font-size: 0.85rem; color: ${isLegal ? 'var(--accent-green)' : 'var(--accent-red)'}; margin-bottom: 0.25rem;">
          Deterministic Validation Guardrails
        </div>
        ${isLegal ? `
          <div style="font-size: 0.85rem; color: var(--text-secondary);">
            All proposed moves comply with FPL constraints. Projected Bank: <strong>£${((val.bank_after_tenths || 0)/10).toFixed(1)}m</strong> | Hits: <strong>${val.transfer_hits || 0}</strong>.
          </div>
        ` : `
          <div style="font-size: 0.85rem; color: #fca5a5;">
            ${errors.map(e => `<div>• ${escapeHtml(e)}</div>`).join('')}
          </div>
        `}
      </div>
    </div>
  `;

  container.innerHTML = html;
}

async function viewManagerDossier() {
  const container = document.getElementById("advisor-results-container");
  if (!container) return;

  const gwInput = document.getElementById("adv-gw") || document.getElementById("live-gw");
  let gw = gwInput ? parseInt(gwInput.value) : null;
  if (!gw) gw = state.activeGameweek;
  if (gwInput && !gwInput.value) gwInput.value = gw;

  container.innerHTML = `
    <div style="padding: 2.5rem 1rem; text-align: center; color: var(--text-muted);">
      <div class="spinner" style="margin: 0 auto 1rem auto; width: 32px; height: 32px; border: 3px solid var(--border-color); border-top-color: var(--accent-blue); border-radius: 50%; animation: spin 0.8s linear infinite;"></div>
      <p>Compiling analytical manager dossier for Gameweek ${gw}...</p>
    </div>
  `;

  try {
    const data = await api(`/api/briefing?team=${state.activeTeamId}&gameweek=${gw}`);
    renderManagerDossier(data);
  } catch (err) {
    container.innerHTML = `
      <div class="alert alert-danger" style="margin-top: 1rem;">
        Failed to load analytical dossier: ${escapeHtml(err.message)}
      </div>
    `;
  }
}

function renderManagerDossier(dossier) {
  const container = document.getElementById("advisor-results-container");
  if (!container) return;

  const fin = dossier.financials || {};
  const lineup = dossier.lineup || {};
  const alerts = dossier.squad_health_alerts || [];
  const riskData = dossier.strategic_risk || {};
  const threats = riskData.top_threats_against_squad || dossier.strategic_ownership_risks || [];
  const recs = dossier.transfer_suggestions || dossier.top_transfer_recommendations || [];
  const chipData = dossier.chip_strategy || {};

  let html = `
    <div class="advisor-card">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.2rem; flex-wrap: wrap; gap: 0.5rem;">
        <div>
          <h3 style="margin: 0; font-size: 1.25rem;">📑 Manager Analytical Dossier — Gameweek ${dossier.gameweek}</h3>
          <div style="font-size: 0.82rem; color: var(--text-secondary);">Comprehensive pre-match analytical intelligence package</div>
        </div>
        <button class="btn btn-outline btn-sm" onclick="runAdvisor()">Switch to AI Critique</button>
      </div>

      <!-- Financials HUD -->
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 0.75rem; margin-bottom: 1.5rem;">
        <div class="ps-stat-box">
          <div class="ps-stat-label">Bank</div>
          <div class="ps-stat-value">${escapeHtml(fin.bank_fmt || '£0.0m')}</div>
        </div>
        <div class="ps-stat-box">
          <div class="ps-stat-label">Free Transfers</div>
          <div class="ps-stat-value">${fin.free_transfers !== undefined ? fin.free_transfers : 1}</div>
        </div>
        <div class="ps-stat-box">
          <div class="ps-stat-label">Projected XI xP</div>
          <div class="ps-stat-value" style="color: var(--accent-green);">${lineup.total_predicted_xp || 0}</div>
        </div>
        <div class="ps-stat-box">
          <div class="ps-stat-label">Captain Armband</div>
          <div class="ps-stat-value" style="color: var(--accent-gold); font-size: 0.95rem;">${escapeHtml(lineup.captain ? lineup.captain.name : 'None')}</div>
        </div>
      </div>
  `;

  // Health alerts
  if (alerts.length > 0) {
    html += `
      <div style="margin-bottom: 1.5rem;">
        <h4 style="font-size: 0.95rem; margin-bottom: 0.5rem; color: #f87171;">⚠️ Squad Health Alerts & Press Conference Notes</h4>
        <div style="display: flex; flex-direction: column; gap: 0.4rem;">
          ${alerts.map(a => `
            <div style="background: rgba(239, 68, 68, 0.08); border-left: 3px solid var(--accent-red); padding: 0.5rem 0.8rem; border-radius: 4px; font-size: 0.85rem;">
              <strong>${escapeHtml(a.name)}</strong> (${a.chance_pct !== null && a.chance_pct !== undefined ? a.chance_pct + '% chance' : 'Status: ' + escapeHtml(a.status || 'Flagged')}): 
              <em>${escapeHtml(a.news || 'Flagged by medical staff')}</em>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }

  // Top Transfer recommendations
  if (recs.length > 0) {
    html += `
      <div style="margin-bottom: 1.5rem;">
        <h4 style="font-size: 0.95rem; margin-bottom: 0.5rem; color: var(--accent-green);">🔄 Top Algorithmic Transfer Moves</h4>
        <div style="display: flex; flex-direction: column; gap: 0.4rem;">
          ${recs.slice(0, 3).map(r => {
            const outName = r.outgoing ? r.outgoing.map(p => p.name).join(', ') : (r.out_name || 'None');
            const inName = r.incoming ? r.incoming.map(p => p.name).join(', ') : (r.in_name || 'None');
            const deltaRaw = r.net_xp_gain !== undefined ? r.net_xp_gain : (r.net_delta !== undefined ? r.net_delta : (r.xp_delta || 0));
            const delta = typeof deltaRaw === 'number' ? deltaRaw.toFixed(2) : deltaRaw;
            const hit = r.transfer_hits ? ` (Hits: -${r.transfer_hits * 4}pt)` : '';
            return `
              <div style="background: var(--bg-input); border-radius: 6px; padding: 0.5rem 0.8rem; font-size: 0.85rem; display: flex; justify-content: space-between; align-items: center;">
                <div>
                  🔄 <strong>${escapeHtml(outName)}</strong> ➔ <strong>${escapeHtml(inName)}</strong>${hit}
                </div>
                <div style="font-weight: 800; color: var(--accent-green);">
                  +${delta} xP
                </div>
              </div>
            `;
          }).join('')}
        </div>
      </div>
    `;
  }

  // Strategic EO / Template Threats
  if (threats.length > 0) {
    html += `
      <div style="margin-bottom: 1.5rem;">
        <h4 style="font-size: 0.95rem; margin-bottom: 0.5rem; color: var(--accent-blue);">🛡️ Template & Effective Ownership Exposure</h4>
        <div style="display: flex; flex-wrap: wrap; gap: 0.5rem;">
          ${threats.map(r => {
            const eoVal = r.effective_ownership_pct !== undefined ? r.effective_ownership_pct : (r.eo_pct !== undefined ? r.eo_pct : 0);
            const eo = typeof eoVal === 'number' ? eoVal.toFixed(1) : eoVal;
            const isOwned = r.owned_by_squad !== undefined ? r.owned_by_squad : false;
            return `
              <div style="background: var(--bg-input); border-radius: 6px; padding: 0.4rem 0.7rem; font-size: 0.8rem;">
                <strong>${escapeHtml(r.name)}</strong> (${escapeHtml(r.team || '')}): <strong>${eo}% EO</strong> (${isOwned ? '✅ Owned' : '❌ Not Owned'})
              </div>
            `;
          }).join('')}
        </div>
      </div>
    `;
  }

  // Chip Strategy Horizon
  if (chipData.active_segment || (chipData.chips_remaining && chipData.chips_remaining.length > 0)) {
    html += `
      <div>
        <h4 style="font-size: 0.95rem; margin-bottom: 0.5rem; color: var(--accent-purple);">🃏 Chip Strategy & Horizon</h4>
        <div style="background: var(--bg-input); border-radius: 6px; padding: 0.6rem 0.9rem; font-size: 0.85rem;">
          <div>Segment: <strong>${escapeHtml(chipData.active_segment || 'Current Half')}</strong></div>
          <div style="margin-top: 0.2rem;">Remaining: <em>${escapeHtml((chipData.chips_remaining || []).join(', ') || 'None')}</em></div>
        </div>
      </div>
    `;
  }

  html += `</div>`;
  container.innerHTML = html;
}

// Startup sync: auto-check gameweek and sync scores
async function syncGameweekAndScoresAtStartup() {
  try {
    const gwData = await api("/api/gameweek");
    if (gwData && gwData.current_gameweek) {
      state.currentGameweek = gwData.current_gameweek;
      state.activeGameweek = gwData.current_gameweek;
    }
    // Auto-hit scores update at start of GUI
    const scoreRes = await api("/api/update-scores", { method: "POST" });
    if (scoreRes && scoreRes.players_updated !== undefined) {
      showToast(`Gameweek ${state.activeGameweek || 4} verified · Scores synchronized (${scoreRes.players_updated} players).`);
    }
  } catch (err) {
    console.warn("Startup gameweek and score sync:", err);
  }
}

// =========================================================================
// STRATEGIC SQUAD STUDIO (V1.1) CLIENT CONTROLLER
// =========================================================================

const strategicState = {
  mode: "initial",
  horizon: 5,
  strategy: "balanced",
  budget: 100.0,
  lockedPlayerIds: new Set(),
  excludedPlayerIds: new Set(),
  preferredPlayerIds: new Set(),
  candidates: {},
  selectedCandidateKey: "balanced",
  previousCandidate: null,
  allPlayers: [],
  initialized: false,
};

async function loadStrategicStudio() {
  try {
    let endpoint = "/api/strategic-squad/config";
    const contextBadge = document.getElementById("strategic-context-badge");

    if (state.appMode === "historical") {
      const season = histState.season || "2023-24";
      const gw = histState.sessionData ? histState.sessionData.current_gw : (histState.gameweek || 1);
      const sid = histState.sessionId || "";
      endpoint = `/api/strategic-squad/config?season=${encodeURIComponent(season)}&gameweek=${gw}${sid ? `&session_id=${encodeURIComponent(sid)}` : ""}`;
      if (contextBadge) {
        contextBadge.textContent = `Historical (${season} GW${gw})`;
        contextBadge.className = "badge badge-warning";
      }
    } else {
      if (contextBadge) {
        contextBadge.textContent = "Live Team (2026/27)";
        contextBadge.className = "badge badge-info";
      }
    }

    const config = await api(endpoint);
    if (config && config.players) {
      strategicState.allPlayers = config.players;
      populateStrategicPlayersDatalist(config.players);
    }
    const statusBadge = document.getElementById("strategic-status-badge");
    const horizonBadge = document.getElementById("strategic-horizon-badge");
    if (statusBadge) statusBadge.textContent = `Mode: ${strategicState.mode.replace('_', ' ').toUpperCase()}`;
    if (horizonBadge) horizonBadge.textContent = `Horizon: ${strategicState.horizon} GWs`;
  } catch (err) {
    console.warn("Failed to load strategic squad config:", err);
  }
}

function populateStrategicPlayersDatalist(players) {
  const datalist = document.getElementById("strategic-players-datalist");
  if (!datalist) return;
  datalist.innerHTML = "";
  players.forEach(p => {
    const opt = document.createElement("option");
    opt.value = `${p.name} (${p.pos_abbr || p.position}, ${p.team}, ${p.price_fmt})`;
    opt.dataset.id = p.id;
    datalist.appendChild(opt);
  });
}

function findStrategicPlayerFromInput() {
  const input = document.getElementById("strategic-player-search");
  if (!input || !input.value.trim()) return null;
  const val = input.value.trim().toLowerCase();
  const matched = strategicState.allPlayers.find(p => {
    const full = `${p.name} (${p.pos_abbr || p.position}, ${p.team}, ${p.price_fmt})`.toLowerCase();
    return full === val || p.name.toLowerCase() === val;
  });
  if (matched) return matched;
  return strategicState.allPlayers.find(p => p.name.toLowerCase().includes(val));
}

function renderActiveConstraintPills() {
  const container = document.getElementById("active-constraints-container");
  if (!container) return;
  container.innerHTML = "";

  const hasConstraints = (
    strategicState.lockedPlayerIds.size > 0 ||
    strategicState.excludedPlayerIds.size > 0 ||
    strategicState.preferredPlayerIds.size > 0
  );

  const reoptBtn = document.getElementById("btn-reoptimize-strategic");
  if (reoptBtn) reoptBtn.disabled = !hasConstraints || !strategicState.previousCandidate;

  if (!hasConstraints) {
    container.innerHTML = `<span class="text-muted" id="no-constraints-text" style="font-size: 0.85rem;">No active player constraints. Optimizer has full search freedom.</span>`;
    return;
  }

  const playerById = new Map(strategicState.allPlayers.map(p => [p.id, p]));

  strategicState.lockedPlayerIds.forEach(id => {
    const p = playerById.get(id);
    const name = p ? `${p.name} (${p.pos_abbr || p.position})` : `ID:${id}`;
    const pill = document.createElement("span");
    pill.className = "constraint-pill constraint-pill-lock";
    pill.innerHTML = `🔒 ${escapeHtml(name)} <button type="button" class="btn-remove-pill" data-type="lock" data-id="${id}" title="Remove lock">×</button>`;
    container.appendChild(pill);
  });

  strategicState.excludedPlayerIds.forEach(id => {
    const p = playerById.get(id);
    const name = p ? `${p.name} (${p.pos_abbr || p.position})` : `ID:${id}`;
    const pill = document.createElement("span");
    pill.className = "constraint-pill constraint-pill-exclude";
    pill.innerHTML = `🚫 ${escapeHtml(name)} <button type="button" class="btn-remove-pill" data-type="exclude" data-id="${id}" title="Remove exclusion">×</button>`;
    container.appendChild(pill);
  });

  strategicState.preferredPlayerIds.forEach(id => {
    const p = playerById.get(id);
    const name = p ? `${p.name} (${p.pos_abbr || p.position})` : `ID:${id}`;
    const pill = document.createElement("span");
    pill.className = "constraint-pill constraint-pill-prefer";
    pill.innerHTML = `⭐ ${escapeHtml(name)} <button type="button" class="btn-remove-pill" data-type="prefer" data-id="${id}" title="Remove preference">×</button>`;
    container.appendChild(pill);
  });

  container.querySelectorAll(".btn-remove-pill").forEach(btn => {
    btn.addEventListener("click", () => {
      const type = btn.dataset.type;
      const pid = parseInt(btn.dataset.id, 10);
      if (type === "lock") strategicState.lockedPlayerIds.delete(pid);
      if (type === "exclude") strategicState.excludedPlayerIds.delete(pid);
      if (type === "prefer") strategicState.preferredPlayerIds.delete(pid);
      renderActiveConstraintPills();
    });
  });
}

function renderStrategicMatrix(candidates) {
  const tbody = document.getElementById("strategic-matrix-tbody");
  if (!tbody) return;
  tbody.innerHTML = "";

  const candidateKeys = ["maximum_ev", "balanced", "floor", "ceiling", "flexibility"];

  const metrics = [
    { label: "Total Strategic Objective", fn: c => c.total_objective_value ? c.total_objective_value.toFixed(1) : "-" },
    { label: "Horizon Projected xP", fn: c => c.horizon_xp ? `${c.horizon_xp.toFixed(1)} xP` : "-" },
    { label: "GW1 Lineup Projected xP", fn: c => c.start_gw_lineup_xp ? `${c.start_gw_lineup_xp.toFixed(1)} xP` : "-" },
    { label: "Optimized Formation", fn: c => c.formation || "-" },
    { label: "Total Cost", fn: c => c.total_cost_fmt || "-" },
    { label: "Bank Remaining", fn: c => c.bank_remaining_fmt || "-" },
    { label: "Future Flexibility Score", fn: c => c.future_flexibility_score ? `${c.future_flexibility_score.toFixed(0)} / 100` : "-" },
    { label: "Bench Value Score", fn: c => c.bench_value_score ? `${c.bench_value_score.toFixed(1)}` : "-" },
    { label: "Structural Risk Penalty", fn: c => c.risk_score ? `-${c.risk_score.toFixed(1)} pts` : "0.0 pts" },
  ];

  metrics.forEach(m => {
    const tr = document.createElement("tr");
    let rowHtml = `<td class="metric-name">${escapeHtml(m.label)}</td>`;
    candidateKeys.forEach(k => {
      const c = candidates[k];
      const val = c ? m.fn(c) : "-";
      const isSel = k === strategicState.selectedCandidateKey;
      rowHtml += `<td style="${isSel ? 'background: rgba(124, 58, 237, 0.2); font-weight: 700;' : ''}">${escapeHtml(val)}</td>`;
    });
    tr.innerHTML = rowHtml;
    tbody.appendChild(tr);
  });
}

function renderStrategicPitch(candidate) {
  const container = document.getElementById("strategic-pitch-container");
  if (!container || !candidate) return;
  container.innerHTML = "";

  const titleEl = document.getElementById("selected-candidate-title");
  const formEl = document.getElementById("selected-candidate-formation");
  if (titleEl) titleEl.textContent = `${candidate.strategy.toUpperCase().replace('_', ' ')} Strategic Candidate`;
  if (formEl) formEl.textContent = `Formation: ${candidate.formation || "3-4-3"} · Total Cost: ${candidate.total_cost_fmt || ""} · Bank: ${candidate.bank_remaining_fmt || ""}`;

  const starters = candidate.starters || [];
  const bench = candidate.bench || [];

  const byPos = { GKP: [], DEF: [], MID: [], FWD: [] };
  starters.forEach(p => {
    const pos = p.pos_abbr || p.position;
    if (byPos[pos]) byPos[pos].push(p);
    else byPos.MID.push(p);
  });

  ["GKP", "DEF", "MID", "FWD"].forEach(pos => {
    const row = document.createElement("div");
    row.className = "strategic-pitch-row";
    (byPos[pos] || []).forEach(p => {
      row.appendChild(createStrategicPlayerCard(p, candidate));
    });
    container.appendChild(row);
  });

  if (bench.length > 0) {
    const benchHeader = document.createElement("div");
    benchHeader.style.cssText = "font-size: 0.75rem; font-weight: 700; text-transform: uppercase; color: rgba(255,255,255,0.7); text-align: center; margin-top: 0.5rem;";
    benchHeader.textContent = "Bench Substitutes";
    container.appendChild(benchHeader);

    const benchRow = document.createElement("div");
    benchRow.className = "strategic-pitch-row";
    bench.forEach(p => {
      benchRow.appendChild(createStrategicPlayerCard(p, candidate, true));
    });
    container.appendChild(benchRow);
  }
}

function createStrategicPlayerCard(p, candidate, isBench = false) {
  const card = document.createElement("div");
  card.className = `strategic-player-card ${p.is_locked ? "is-locked" : ""}`;
  
  let roleBadge = "";
  if (p.role === "CAPTAIN") roleBadge = `<span class="p-card-role" style="background: #f59e0b; color: #000;">C</span>`;
  else if (p.role === "VICE_CAPTAIN") roleBadge = `<span class="p-card-role" style="background: #94a3b8; color: #000;">VC</span>`;
  else if (p.role === "GK_SUB") roleBadge = `<span class="p-card-role" style="background: #3b82f6; color: #fff;">SUB</span>`;

  let lockIcon = p.is_locked ? "🔒 " : (p.is_preferred ? "⭐ " : "");

  card.innerHTML = `
    ${roleBadge}
    <div class="p-card-name" title="${escapeHtml(p.name)}">${lockIcon}${escapeHtml(p.name)}</div>
    <div class="p-card-meta">${escapeHtml(p.team || '')} · ${escapeHtml(p.price_fmt || '')}</div>
    <div class="p-card-xp">${p.expected_points !== undefined ? Number(p.expected_points).toFixed(1) : '0.0'} xP</div>
  `;
  return card;
}

function renderStrategicDossier(candidate) {
  const container = document.getElementById("strategic-dossier-content");
  if (!container || !candidate) return;

  const hBreakdown = candidate.horizon_breakdown || {};
  const breakdownRows = Object.entries(hBreakdown).map(([gw, xp]) => `
    <div style="display: flex; justify-content: space-between; padding: 0.25rem 0; border-bottom: 1px solid rgba(255,255,255,0.05);">
      <span class="text-muted">GW${gw}:</span>
      <strong>${Number(xp).toFixed(1)} xP</strong>
    </div>
  `).join("");

  container.innerHTML = `
    <div style="margin-bottom: 1rem;">
      <div style="display: flex; justify-content: space-between; margin-bottom: 0.35rem;">
        <span class="text-muted">Horizon Projected Total:</span>
        <strong style="color: var(--accent-green); font-size: 1.1rem;">${candidate.horizon_xp ? candidate.horizon_xp.toFixed(1) : 0} xP</strong>
      </div>
      <div style="display: flex; justify-content: space-between; margin-bottom: 0.35rem;">
        <span class="text-muted">Start GW Lineup Projected:</span>
        <strong>${candidate.start_gw_lineup_xp ? candidate.start_gw_lineup_xp.toFixed(1) : 0} xP</strong>
      </div>
      <div style="display: flex; justify-content: space-between; margin-bottom: 0.35rem;">
        <span class="text-muted">Captaincy Score:</span>
        <strong>${candidate.captaincy_score ? candidate.captaincy_score.toFixed(1) : 0}</strong>
      </div>
      <div style="display: flex; justify-content: space-between; margin-bottom: 0.35rem;">
        <span class="text-muted">Bench Quality Score:</span>
        <strong>${candidate.bench_value_score ? candidate.bench_value_score.toFixed(1) : 0}</strong>
      </div>
      <div style="display: flex; justify-content: space-between;">
        <span class="text-muted">Future Transfer Flexibility:</span>
        <strong style="color: var(--accent-blue);">${candidate.future_flexibility_score ? candidate.future_flexibility_score.toFixed(0) : 50} / 100</strong>
      </div>
    </div>

    <div style="margin-top: 1rem;">
      <h4 style="font-size: 0.82rem; text-transform: uppercase; color: var(--text-secondary); margin-bottom: 0.4rem;">Horizon GW-by-GW Breakdown:</h4>
      ${breakdownRows}
    </div>
  `;

  const provEl = document.getElementById("strategic-provenance-info");
  if (provEl) {
    const prov = candidate.provenance || {};
    const exactBadge = candidate.is_exact_global_optimum ? "✅ Exact Global Solver" : "⚡ Heuristic 1-Opt/2-Opt Local Search";
    provEl.innerHTML = `
      <div>Algorithm: <strong>${escapeHtml(candidate.algorithm || "solve_strategic_squad")}</strong></div>
      <div>Optimality Guarantee: <strong>${exactBadge}</strong></div>
      <div>Provenance Timestamp: <em>${escapeHtml(prov.timestamp || new Date().toISOString())}</em></div>
    `;
  }
}

function renderConstraintImpactBanner(impact) {
  const banner = document.getElementById("constraint-impact-banner");
  if (!banner) return;
  if (!impact) {
    banner.classList.add("hidden");
    return;
  }

  banner.classList.remove("hidden");
  document.getElementById("impact-summary-text").textContent = impact.summary || "Constraint impact analysis complete.";
  
  const oppCostEl = document.getElementById("impact-opp-cost");
  if (oppCostEl) {
    const opp = impact.opportunity_cost || 0;
    oppCostEl.textContent = `${opp.toFixed(1)} pts`;
    oppCostEl.style.color = opp > 0 ? "var(--accent-red)" : "var(--accent-green)";
  }

  const xpDeltaEl = document.getElementById("impact-xp-delta");
  if (xpDeltaEl) {
    const xpD = impact.horizon_xp_delta || 0;
    xpDeltaEl.textContent = `${xpD >= 0 ? '+' : ''}${xpD.toFixed(1)} pts`;
  }

  const bankDeltaEl = document.getElementById("impact-bank-delta");
  if (bankDeltaEl) {
    bankDeltaEl.textContent = impact.bank_delta_fmt || "£0.0m";
  }

  const flexDeltaEl = document.getElementById("impact-flex-delta");
  if (flexDeltaEl) {
    const fD = impact.flexibility_delta || 0;
    flexDeltaEl.textContent = `${fD >= 0 ? '+' : ''}${fD.toFixed(1)}`;
  }

  const diffEl = document.getElementById("impact-players-diff");
  if (diffEl) {
    const added = impact.players_added || [];
    const removed = impact.players_removed || [];
    if (added.length > 0 || removed.length > 0) {
      diffEl.innerHTML = `
        <div style="margin-top: 0.4rem;">
          ${added.length ? `<span style="color: var(--accent-green);">IN:</span> ${added.map(p => `<strong>${escapeHtml(p.name)}</strong> (${p.pos_abbr || p.position})`).join(', ')} ` : ''}
          ${removed.length ? `<span style="color: var(--accent-red); margin-left: 0.5rem;">OUT:</span> ${removed.map(p => `<strong>${escapeHtml(p.name)}</strong> (${p.pos_abbr || p.position})`).join(', ')}` : ''}
        </div>
      `;
    } else {
      diffEl.innerHTML = "";
    }
  }
}

function initStrategicStudio() {
  if (strategicState.initialized) return;
  strategicState.initialized = true;

  const modeSel = document.getElementById("strategic-mode-select");
  const horizonSel = document.getElementById("strategic-horizon-select");
  const stratSel = document.getElementById("strategic-strategy-select");
  const budgetInp = document.getElementById("strategic-budget-input");

  if (modeSel) {
    modeSel.addEventListener("change", e => {
      strategicState.mode = e.target.value;
      const b = document.getElementById("strategic-status-badge");
      if (b) b.textContent = `Mode: ${e.target.value.replace('_', ' ').toUpperCase()}`;
    });
  }

  if (horizonSel) {
    horizonSel.addEventListener("change", e => {
      strategicState.horizon = parseInt(e.target.value, 10);
      const b = document.getElementById("strategic-horizon-badge");
      if (b) b.textContent = `Horizon: ${e.target.value} GWs`;
    });
  }

  if (stratSel) {
    stratSel.addEventListener("change", e => {
      strategicState.strategy = e.target.value;
    });
  }

  if (budgetInp) {
    budgetInp.addEventListener("change", e => {
      strategicState.budget = parseFloat(e.target.value) || 100.0;
    });
  }

  const addLockBtn = document.getElementById("btn-add-lock");
  const addExclBtn = document.getElementById("btn-add-exclude");
  const addPrefBtn = document.getElementById("btn-add-prefer");
  const clearBtn = document.getElementById("btn-clear-constraints");
  const searchInp = document.getElementById("strategic-player-search");

  if (addLockBtn) {
    addLockBtn.addEventListener("click", () => {
      const p = findStrategicPlayerFromInput();
      if (!p) {
        showToast("Please select a player to lock.", true);
        return;
      }
      strategicState.excludedPlayerIds.delete(p.id);
      strategicState.lockedPlayerIds.add(p.id);
      if (searchInp) searchInp.value = "";
      renderActiveConstraintPills();
      showToast(`Locked ${p.name} as Must-Have.`);
    });
  }

  if (addExclBtn) {
    addExclBtn.addEventListener("click", () => {
      const p = findStrategicPlayerFromInput();
      if (!p) {
        showToast("Please select a player to exclude.", true);
        return;
      }
      strategicState.lockedPlayerIds.delete(p.id);
      strategicState.excludedPlayerIds.add(p.id);
      if (searchInp) searchInp.value = "";
      renderActiveConstraintPills();
      showToast(`Excluded ${p.name} from squad.`);
    });
  }

  if (addPrefBtn) {
    addPrefBtn.addEventListener("click", () => {
      const p = findStrategicPlayerFromInput();
      if (!p) {
        showToast("Please select a player to prefer.", true);
        return;
      }
      strategicState.preferredPlayerIds.add(p.id);
      if (searchInp) searchInp.value = "";
      renderActiveConstraintPills();
      showToast(`Added soft preference for ${p.name}.`);
    });
  }

  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      strategicState.lockedPlayerIds.clear();
      strategicState.excludedPlayerIds.clear();
      strategicState.preferredPlayerIds.clear();
      renderActiveConstraintPills();
      showToast("Cleared all player constraints.");
    });
  }

  const genBtn = document.getElementById("btn-generate-strategic");
  if (genBtn) {
    genBtn.addEventListener("click", async () => {
      try {
        genBtn.disabled = true;
        genBtn.textContent = "⏳ Solving Strategic Space...";

        const payload = {
          mode: strategicState.mode,
          horizon: strategicState.horizon,
          strategy: strategicState.strategy,
          budget: strategicState.budget,
          locked_player_ids: Array.from(strategicState.lockedPlayerIds),
          excluded_player_ids: Array.from(strategicState.excludedPlayerIds),
          preferred_player_ids: Array.from(strategicState.preferredPlayerIds),
          team_id: state.activeTeamId,
        };

        if (state.appMode === "historical") {
          payload.season = histState.season || "2023-24";
          payload.gameweek = histState.sessionData ? histState.sessionData.current_gw : (histState.gameweek || 1);
          if (histState.sessionId) {
            payload.session_id = histState.sessionId;
          }
        }

        const res = await api("/api/strategic-squad/optimize", {
          method: "POST",
          body: JSON.stringify(payload),
        });

        if (res && res.squad) {
          strategicState.candidates = res.strategic_candidates || { [res.strategy]: res };
          strategicState.selectedCandidateKey = res.strategy || "balanced";
          strategicState.previousCandidate = res;

          renderCandidateSwitcherTabs(strategicState.candidates);
          renderStrategicMatrix(strategicState.candidates);
          renderStrategicPitch(res);
          renderStrategicDossier(res);

          const resPanel = document.getElementById("strategic-results-panel");
          if (resPanel) resPanel.classList.remove("hidden");

          const reoptBtn = document.getElementById("btn-reoptimize-strategic");
          if (reoptBtn) reoptBtn.disabled = false;

          if (res.failed_profiles && Object.keys(res.failed_profiles).length > 0) {
            const failedList = Object.entries(res.failed_profiles).map(([p, reason]) => `${p}: ${reason}`).join("; ");
            showToast(`Generated ${Object.keys(strategicState.candidates).length} candidates. Notice: unfeasible profiles skipped: ${failedList}`, true);
          } else {
            showToast(`Generated ${Object.keys(strategicState.candidates).length} strategic candidates!`);
          }
        }
      } catch (err) {
        let msg = err.message || "Optimization failed.";
        if (err.error_type === "INFEASIBLE_CONSTRAINTS" || msg.toLowerCase().includes("budget") || msg.toLowerCase().includes("constraint")) {
          msg = `Infeasible Constraints: ${msg}. Please relax player locks or adjust budget.`;
        }
        showToast(`Strategic optimization error: ${msg}`, true);
      } finally {
        genBtn.disabled = false;
        genBtn.textContent = "⚡ Generate Strategic Candidates";
      }
    });
  }

  const reoptBtn = document.getElementById("btn-reoptimize-strategic");
  if (reoptBtn) {
    reoptBtn.addEventListener("click", async () => {
      try {
        reoptBtn.disabled = true;
        reoptBtn.textContent = "⏳ Re-optimizing...";

        const payload = {
          previous_candidate: strategicState.previousCandidate,
          mode: strategicState.mode,
          horizon: strategicState.horizon,
          strategy: strategicState.selectedCandidateKey || strategicState.strategy,
          budget: strategicState.budget,
          locked_player_ids: Array.from(strategicState.lockedPlayerIds),
          excluded_player_ids: Array.from(strategicState.excludedPlayerIds),
          preferred_player_ids: Array.from(strategicState.preferredPlayerIds),
          team_id: state.activeTeamId,
        };

        if (state.appMode === "historical") {
          payload.season = histState.season || "2023-24";
          payload.gameweek = histState.sessionData ? histState.sessionData.current_gw : (histState.gameweek || 1);
          if (histState.sessionId) {
            payload.session_id = histState.sessionId;
          }
        }

        const res = await api("/api/strategic-squad/reoptimize", {
          method: "POST",
          body: JSON.stringify(payload),
        });

        if (res && res.squad) {
          strategicState.candidates[res.strategy] = res;
          strategicState.selectedCandidateKey = res.strategy;
          strategicState.previousCandidate = res;

          renderCandidateSwitcherTabs(strategicState.candidates);
          renderStrategicMatrix(strategicState.candidates);
          renderStrategicPitch(res);
          renderStrategicDossier(res);

          if (res.constraint_impact) {
            renderConstraintImpactBanner(res.constraint_impact);
          }

          showToast("Re-optimization complete. Opportunity cost evaluated!");
        }
      } catch (err) {
        showToast(`Re-optimization error: ${err.message}`, true);
      } finally {
        reoptBtn.disabled = false;
        reoptBtn.textContent = "🔄 Re-Optimize Under Constraints";
      }
    });
  }

  const applyBtn = document.getElementById("btn-apply-strategic-squad");
  if (applyBtn) {
    applyBtn.addEventListener("click", async () => {
      const cand = strategicState.candidates[strategicState.selectedCandidateKey] || strategicState.previousCandidate;
      if (!cand) return;

      const confirmed = confirm(`Are you sure you want to apply this ${cand.strategy.toUpperCase()} squad (${cand.mode.toUpperCase()}) to your active team?`);
      if (!confirmed) return;

      try {
        applyBtn.disabled = true;
        applyBtn.textContent = "Applying...";

        const applyPayload = {
          candidate: cand,
          team_id: state.activeTeamId,
          mode: cand.mode,
          gameweek: state.activeGameweek || 1,
        };

        if (state.appMode === "historical") {
          applyPayload.season = histState.season || "2023-24";
          applyPayload.gameweek = histState.sessionData ? histState.sessionData.current_gw : (histState.gameweek || 1);
          if (histState.sessionId) {
            applyPayload.session_id = histState.sessionId;
          }
        }

        const res = await api("/api/strategic-squad/apply", {
          method: "POST",
          body: JSON.stringify(applyPayload),
        });

        if (res && res.success) {
          showToast(`Successfully applied strategic squad!`);
          if (state.appMode === "historical") {
            if (histState.sessionId) {
              await loadHistoricalSession(histState.sessionId);
            }
          } else {
            await loadCurrentSquad();
            await loadLineup();
          }
        }
      } catch (err) {
        showToast(`Failed to apply squad: ${err.message}`, true);
      } finally {
        applyBtn.disabled = false;
        applyBtn.textContent = "💾 Apply Squad to Team";
      }
    });
  }

  const seedBtn = document.getElementById("btn-seed-planner-strategic");
  if (seedBtn) {
    seedBtn.addEventListener("click", () => {
      const cand = strategicState.candidates[strategicState.selectedCandidateKey] || strategicState.previousCandidate;
      if (!cand) return;

      const plannerTabBtn = document.querySelector('.tabs-nav .tab-btn[data-tab="planner"]');
      if (plannerTabBtn) plannerTabBtn.click();
      showToast(`Seeded planner with ${cand.strategy} squad! Click "Generate Multi-GW Plan" to evaluate trajectories.`);
    });
  }
}

function renderCandidateSwitcherTabs(candidates) {
  const container = document.getElementById("candidate-selector-tabs");
  if (!container) return;
  container.innerHTML = "";

  Object.keys(candidates).forEach(key => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `candidate-tab-btn ${key === strategicState.selectedCandidateKey ? "active" : ""}`;
    btn.textContent = key.replace('_', ' ').toUpperCase();
    btn.addEventListener("click", () => {
      strategicState.selectedCandidateKey = key;
      renderCandidateSwitcherTabs(candidates);
      renderStrategicMatrix(candidates);
      renderStrategicPitch(candidates[key]);
      renderStrategicDossier(candidates[key]);
    });
    container.appendChild(btn);
  });
}

// ============================================================================
// Historical Time Machine & Interactive Simulation (V1.4)
// ============================================================================

const histState = {
  season: "2023-24",
  gameweek: 1,
  sessionId: null,
  sessionData: null,
  overviewData: null,
  swapOutPlayer: null,
  overviewPastGw: null,
  overviewFutureGw: null,
  availableSeasons: [],
  initialized: false,
};

function initHistoricalTimeMachine() {
  if (histState.initialized) return;
  histState.initialized = true;

  // Subtab switching in Matchday Center
  const subtabBtns = document.querySelectorAll(".hist-subtab-btn");
  subtabBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      const target = btn.getAttribute("data-subtab");
      subtabBtns.forEach(b => {
        b.classList.remove("active", "btn-secondary");
        b.classList.add("btn-outline");
      });
      btn.classList.add("active", "btn-secondary");
      btn.classList.remove("btn-outline");

      ["standings", "results", "upcoming"].forEach(name => {
        const pane = document.getElementById(`hist-subtab-${name}`);
        if (pane) pane.style.display = name === target ? "block" : "none";
      });
    });
  });

  // Season change
  const seasonSelect = document.getElementById("hist-season-select");
  if (seasonSelect) {
    seasonSelect.addEventListener("change", async (e) => {
      histState.season = e.target.value;
      await loadHistoricalOverview();
      await loadHistoricalSimulationsList();
      const activeTab = document.querySelector('.tabs-nav .tab-btn.active');
      if (activeTab && activeTab.dataset.tab === "strategic") {
        await loadStrategicStudio();
      }
    });
  }

  // Gameweek change
  const gwInput = document.getElementById("hist-gw-select");
  if (gwInput) {
    gwInput.addEventListener("change", async (e) => {
      const val = parseInt(e.target.value, 10);
      if (val >= 1 && val <= 38) {
        histState.gameweek = val;
        await loadHistoricalOverview();
        const activeTab = document.querySelector('.tabs-nav .tab-btn.active');
        if (activeTab && activeTab.dataset.tab === "strategic") {
          await loadStrategicStudio();
        }
      }
    });
  }

  // Simulation Session change
  const simSelect = document.getElementById("hist-session-select");
  if (simSelect) {
    simSelect.addEventListener("change", async (e) => {
      const id = e.target.value;
      if (id) {
        await loadHistoricalSession(id);
        const activeTab = document.querySelector('.tabs-nav .tab-btn.active');
        if (activeTab && activeTab.dataset.tab === "strategic") {
          await loadStrategicStudio();
        }
      }
    });
  }

  // New Simulation modal
  const btnNewSim = document.getElementById("btn-hist-new-sim");
  const modalCreate = document.getElementById("hist-create-modal");
  const btnCloseCreate = document.getElementById("btn-hist-close-create-modal");
  const btnCancelCreate = document.getElementById("btn-cancel-create-sim");
  const btnConfirmCreate = document.getElementById("btn-confirm-create-sim");

  const closeModal = (modal) => {
    if (!modal) return;
    modal.classList.add("hidden");
    modal.style.display = "none";
  };

  if (btnNewSim) {
    btnNewSim.addEventListener("click", () => {
      openCreateSimulationModal();
    });
  }
  if (btnCloseCreate && modalCreate) {
    btnCloseCreate.addEventListener("click", () => closeModal(modalCreate));
  }
  if (btnCancelCreate && modalCreate) {
    btnCancelCreate.addEventListener("click", () => closeModal(modalCreate));
  }

  if (btnConfirmCreate) {
    btnConfirmCreate.addEventListener("click", async () => {
      const season = document.getElementById("create-sim-season").value;
      const startGw = parseInt(document.getElementById("create-sim-start-gw").value, 10) || 1;
      const simId = document.getElementById("create-sim-id").value.trim() || `sim_${Date.now()}`;
      const manager = document.getElementById("create-sim-manager").value.trim() || "Human Manager";
      const strat = document.getElementById("create-sim-strategy").value;

      try {
        btnConfirmCreate.disabled = true;
        btnConfirmCreate.textContent = "Creating...";
        const res = await api("/api/historical/simulations/create", {
          method: "POST",
          body: JSON.stringify({
            session_id: simId,
            season: season,
            start_gw: startGw,
            starting_strategy: strat,
            manager_name: manager,
          }),
        });

        // Close modal immediately upon successful creation
        closeModal(modalCreate);
        showToast(`Simulation '${simId}' created!`);

        histState.season = season;
        const seasonSelect = document.getElementById("hist-season-select");
        if (seasonSelect) seasonSelect.value = season;

        await loadHistoricalSimulationsList();
        await loadHistoricalSession(simId);
        await loadOverview();
      } catch (err) {
        showToast(`Failed to create simulation: ${err.message}`, true);
      } finally {
        btnConfirmCreate.disabled = false;
        btnConfirmCreate.textContent = "Create Simulation";
      }
    });
  }

  // Run Gameweek
  const btnRunGw = document.getElementById("btn-hist-run-gw");
  if (btnRunGw) {
    btnRunGw.addEventListener("click", async () => {
      if (!histState.sessionId) {
        showToast("Please select or create a historical simulation session first.", true);
        return;
      }
      try {
        btnRunGw.disabled = true;
        btnRunGw.textContent = "Resolving...";
        const res = await api(`/api/historical/simulations/${histState.sessionId}/run-gw`, {
          method: "POST",
          body: JSON.stringify({}),
        });

        // Open resolution modal
        showHistoricalResolutionModal(res.resolution);
        await loadHistoricalSession(histState.sessionId);
      } catch (err) {
        showToast(`Failed to run matchday: ${err.message}`, true);
      } finally {
        btnRunGw.disabled = false;
        btnRunGw.textContent = "⚡ Run Matchday";
      }
    });
  }

  // Report Modal
  const btnReport = document.getElementById("btn-hist-view-report");
  if (btnReport) {
    btnReport.addEventListener("click", async () => {
      if (!histState.sessionId) {
        showToast("Please select a simulation session to view report.", true);
        return;
      }
      try {
        const report = await api(`/api/historical/simulations/${histState.sessionId}/report`);
        showHistoricalReportModal(report);
      } catch (err) {
        showToast(`Failed to load report: ${err.message}`, true);
      }
    });
  }

  // Chip Selector
  const chipSelect = document.getElementById("hist-chip-select");
  if (chipSelect) {
    chipSelect.addEventListener("change", async (e) => {
      if (!histState.sessionId) return;
      const chip = e.target.value;
      try {
        await api(`/api/historical/simulations/${histState.sessionId}/chip`, {
          method: "POST",
          body: JSON.stringify({ chip: chip || null }),
        });
        showToast(chip ? `Activated chip: ${chip}` : "Deactivated chip.");
        await loadHistoricalSession(histState.sessionId);
      } catch (err) {
        showToast(err.message, true);
      }
    });
  }

  // Clear Transacted
  const btnClearTx = document.getElementById("btn-hist-clear-tx");
  if (btnClearTx) {
    btnClearTx.addEventListener("click", async () => {
      if (!histState.sessionId) return;
      try {
        await api(`/api/historical/simulations/${histState.sessionId}/transfers`, {
          method: "POST",
          body: JSON.stringify({ action: "clear" }),
        });
        showToast("Cleared staged transfers.");
        await loadHistoricalSession(histState.sessionId);
      } catch (err) {
        showToast(err.message, true);
      }
    });
  }

  // Recommendations Button
  const btnRecs = document.getElementById("btn-hist-recs");
  if (btnRecs) {
    btnRecs.addEventListener("click", async () => {
      if (!histState.sessionId) {
        showToast("Please select a simulation first.", true);
        return;
      }
      try {
        btnRecs.disabled = true;
        const recs = await api(`/api/historical/simulations/${histState.sessionId}/recommendations`);
        showHistoricalRecommendationsModal(recs);
      } catch (err) {
        showToast(`Error getting recommendations: ${err.message}`, true);
      } finally {
        btnRecs.disabled = false;
      }
    });
  }

  // Auto-Lineup Button
  const btnAutoLineup = document.getElementById("btn-hist-auto-lineup");
  if (btnAutoLineup) {
    btnAutoLineup.addEventListener("click", async () => {
      if (!histState.sessionId) return;
      try {
        const recs = await api(`/api/historical/simulations/${histState.sessionId}/recommendations`);
        if (recs && recs.recommended_starters) {
          await api(`/api/historical/simulations/${histState.sessionId}/lineup`, {
            method: "POST",
            body: JSON.stringify({
              starting_ids: recs.recommended_starters,
              bench_ids: recs.recommended_bench,
              captain_id: recs.recommended_captain,
              vice_captain_id: recs.recommended_vice_captain,
            }),
          });
          showToast("Starting 11 and captaincy auto-aligned to optimal xP.");
          await loadHistoricalSession(histState.sessionId);
        }
      } catch (err) {
        showToast(`Lineup update failed: ${err.message}`, true);
      }
    });
  }

  // Results Filter GW
  const resultsFilter = document.getElementById("hist-results-gw-filter");
  if (resultsFilter) {
    resultsFilter.addEventListener("change", (e) => {
      if (!histState.overviewData) return;
      renderHistoricalPastResults(histState.overviewData.past_results, e.target.value);
    });
  }

  // Modals Close
  const btnCloseModal = document.getElementById("btn-hist-close-modal");
  const modalBox = document.getElementById("hist-modal");
  if (btnCloseModal && modalBox) {
    btnCloseModal.addEventListener("click", () => closeModal(modalBox));
  }

  const btnCloseSwap = document.getElementById("btn-hist-close-swap-modal");
  const modalSwap = document.getElementById("hist-swap-modal");
  if (btnCloseSwap && modalSwap) {
    btnCloseSwap.addEventListener("click", () => closeModal(modalSwap));
  }

  // Initial loads
  loadHistoricalSeasons();
  loadHistoricalOverview();
  loadHistoricalSimulationsList();
}

async function loadHistoricalSeasons() {
  try {
    const res = await api("/api/historical/seasons");
    const seasons = res.seasons || [];
    if (seasons.length > 0) {
      histState.availableSeasons = seasons;
      if (!seasons.includes(histState.season)) {
        histState.season = seasons[0];
      }

      // Populate header season dropdown
      const seasonSelect = document.getElementById("hist-season-select");
      if (seasonSelect) {
        seasonSelect.innerHTML = seasons.map(s => `
          <option value="${s}" ${s === histState.season ? "selected" : ""}>${s}</option>
        `).join("");
      }

      // Populate modal season dropdown
      const createSeason = document.getElementById("create-sim-season");
      if (createSeason) {
        createSeason.innerHTML = seasons.map(s => `
          <option value="${s}" ${s === histState.season ? "selected" : ""}>${s}</option>
        `).join("");
      }
    }
  } catch (err) {
    console.error("Failed to load historical seasons:", err);
  }
}

function openCreateSimulationModal() {
  const modalCreate = document.getElementById("hist-create-modal");
  const createSeason = document.getElementById("create-sim-season");
  if (createSeason) {
    if (histState.availableSeasons && histState.availableSeasons.length > 0) {
      createSeason.innerHTML = histState.availableSeasons.map(s => `
        <option value="${s}" ${s === histState.season ? "selected" : ""}>${s}</option>
      `).join("");
    }
    createSeason.value = histState.season;
  }
  const createId = document.getElementById("create-sim-id");
  if (createId) {
    createId.value = `sim_${histState.season.replace('-', '_')}_${Date.now().toString().slice(-4)}`;
  }
  if (modalCreate) {
    modalCreate.classList.remove("hidden");
    modalCreate.style.display = "flex";
  }
}

async function loadHistoricalTimeMachine() {
  initHistoricalTimeMachine();
  await loadHistoricalSeasons();
  await loadHistoricalOverview();
  await loadHistoricalSimulationsList();
}

// ----------------------------------------------------------------------------
// Overview & Standings / Fixtures
// ----------------------------------------------------------------------------

async function loadHistoricalOverview() {
  const bannerSeason = document.getElementById("hist-info-season");
  const bannerGw = document.getElementById("hist-info-gw");
  if (bannerSeason) bannerSeason.textContent = histState.season;
  if (bannerGw) bannerGw.textContent = histState.gameweek;

  try {
    const data = await api(`/api/historical/overview?season=${histState.season}&gameweek=${histState.gameweek}`);
    histState.overviewData = data;
    renderHistoricalStandings(data.standings);
    renderHistoricalPastResults(data.past_results, "all");
    renderHistoricalUpcomingFixtures(data.upcoming_fixtures);
  } catch (err) {
    console.error("Failed to load historical overview:", err);
  }
}

function renderHistoricalStandings(standings) {
  const tbody = document.getElementById("hist-standings-body");
  if (!tbody) return;
  if (!standings || standings.length === 0) {
    tbody.innerHTML = `<tr><td colspan="11" class="text-center text-muted" style="padding: 1.5rem;">No standings available for Gameweek ${histState.gameweek}.</td></tr>`;
    return;
  }

  tbody.innerHTML = standings.map((s, idx) => {
    let posClass = "";
    if (s.position <= 4) posClass = "pos-ucl";
    else if (s.position === 5) posClass = "pos-uel";
    else if (s.position >= 18) posClass = "pos-rel";

    const formHtml = (s.form || []).map(f => {
      const cls = f === "W" ? "form-w" : (f === "D" ? "form-d" : "form-l");
      return `<span class="form-badge ${cls}">${f}</span>`;
    }).join("");

    const gdFormatted = s.goal_difference > 0 ? `+${s.goal_difference}` : s.goal_difference;

    return `
      <tr class="${posClass}">
        <td style="text-align: center; font-weight: bold; color: #94a3b8;">${s.position}</td>
        <td style="font-weight: 600;">
          <span>${escapeHtml(s.name)}</span>
          <span style="font-size: 0.72rem; color: #64748b; margin-left: 4px;">(${escapeHtml(s.short_name)})</span>
        </td>
        <td style="text-align: center;">${s.played}</td>
        <td style="text-align: center;">${s.won}</td>
        <td style="text-align: center;">${s.drawn}</td>
        <td style="text-align: center;">${s.lost}</td>
        <td style="text-align: center;">${s.goals_for}</td>
        <td style="text-align: center;">${s.goals_against}</td>
        <td style="text-align: center; color: ${s.goal_difference > 0 ? '#34d399' : (s.goal_difference < 0 ? '#f87171' : '#94a3b8')};">${gdFormatted}</td>
        <td style="text-align: center; font-weight: bold; font-size: 0.95rem; color: #fbbf24;">${s.points}</td>
        <td style="text-align: center;"><div class="form-badge-strip">${formHtml || "-"}</div></td>
      </tr>
    `;
  }).join("");
}

function renderHistoricalPastResults(results, filterGw = "all") {
  const list = document.getElementById("hist-past-results-list");
  const filterSelect = document.getElementById("hist-results-gw-filter");
  if (!list) return;

  if (!results || results.length === 0) {
    list.innerHTML = `<div class="text-center text-muted" style="padding: 2rem;">No previous gameweeks completed yet before Gameweek ${histState.gameweek}.</div>`;
    if (filterSelect) filterSelect.innerHTML = `<option value="all">All Past GWs</option>`;
    return;
  }

  // Populate filter dropdown with unique events
  if (filterSelect && filterSelect.options.length <= 1) {
    const gws = Array.from(new Set(results.map(r => r.event))).sort((a, b) => b - a);
    filterSelect.innerHTML = `<option value="all">All Past GWs (${results.length} matches)</option>` +
      gws.map(gw => `<option value="${gw}">Gameweek ${gw}</option>`).join("");
  }

  const filtered = filterGw === "all" ? results : results.filter(r => r.event.toString() === filterGw.toString());

  list.innerHTML = filtered.map(r => {
    const hWin = r.team_h_score > r.team_a_score;
    const aWin = r.team_a_score > r.team_h_score;
    const kickoffFormatted = r.kickoff_time ? new Date(r.kickoff_time).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' }) : `GW ${r.event}`;

    return `
      <div class="fixture-row-card">
        <div style="font-size: 0.72rem; color: #64748b; width: 65px;">GW ${r.event}</div>
        <div class="fixture-teams">
          <div class="fixture-team-h" style="color: ${hWin ? '#fff' : '#94a3b8'};">
            ${escapeHtml(r.team_h_name)}
          </div>
          <div class="fixture-score">
            ${r.team_h_score} - ${r.team_a_score}
          </div>
          <div class="fixture-team-a" style="color: ${aWin ? '#fff' : '#94a3b8'};">
            ${escapeHtml(r.team_a_name)}
          </div>
        </div>
        <div style="font-size: 0.72rem; color: #64748b; width: 85px; text-align: right;">${kickoffFormatted}</div>
      </div>
    `;
  }).join("");
}

function renderHistoricalUpcomingFixtures(upcoming) {
  const list = document.getElementById("hist-upcoming-fixtures-list");
  if (!list) return;

  if (!upcoming || upcoming.length === 0) {
    list.innerHTML = `<div class="text-center text-muted" style="padding: 2rem;">No upcoming fixtures for Gameweek ${histState.gameweek}.</div>`;
    return;
  }

  list.innerHTML = upcoming.map(u => {
    const kickoffFormatted = u.kickoff_time ? new Date(u.kickoff_time).toLocaleString(undefined, { weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : `GW ${u.event}`;

    return `
      <div class="fixture-row-card">
        <div style="font-size: 0.72rem; color: #38bdf8; font-weight: bold; width: 60px;">GW ${u.event}</div>
        <div class="fixture-teams">
          <div class="fixture-team-h">
            ${escapeHtml(u.team_h_name)}
            <span class="fdr-pill fdr-${u.team_h_difficulty}" title="Home team FDR difficulty: ${u.team_h_difficulty}">${u.team_h_difficulty}</span>
          </div>
          <div class="fixture-vs">vs</div>
          <div class="fixture-team-a">
            <span class="fdr-pill fdr-${u.team_a_difficulty}" title="Away team FDR difficulty: ${u.team_a_difficulty}">${u.team_a_difficulty}</span>
            ${escapeHtml(u.team_a_name)}
          </div>
        </div>
        <div style="font-size: 0.72rem; color: #94a3b8; width: 110px; text-align: right;">${kickoffFormatted}</div>
      </div>
    `;
  }).join("");
}

// ----------------------------------------------------------------------------
// Simulations Management & Pitch
// ----------------------------------------------------------------------------

async function loadHistoricalSimulationsList() {
  const select = document.getElementById("hist-session-select");
  if (!select) return;

  try {
    const data = await api("/api/historical/simulations");
    const sims = data.simulations || [];
    const seasonSims = sims.filter(s => s.season === histState.season);

    if (seasonSims.length === 0) {
      select.innerHTML = `<option value="">No Sim for ${histState.season} (Click + New)</option>`;
      histState.sessionId = null;
      histState.sessionData = null;
      renderEmptyHistoricalSquad();
      return;
    }

    select.innerHTML = seasonSims.map(s => `
      <option value="${escapeHtml(s.session_id)}" ${s.session_id === histState.sessionId ? "selected" : ""}>
        ${escapeHtml(s.session_id)} (GW ${s.current_gw}, ${s.total_net_points} pts)
      </option>
    `).join("");

    const targetId = (histState.sessionId && seasonSims.some(s => s.session_id === histState.sessionId))
      ? histState.sessionId
      : seasonSims[0].session_id;

    select.value = targetId;
    await loadHistoricalSession(targetId);
  } catch (err) {
    console.error("Failed to list historical simulations:", err);
  }
}

async function loadHistoricalSession(sessionId) {
  histState.sessionId = sessionId;
  try {
    const data = await api(`/api/historical/simulations/${sessionId}`);
    histState.sessionData = data;
    histState.season = data.season;
    histState.gameweek = data.current_gw;

    // Update UI controls
    const seasonSelect = document.getElementById("hist-season-select");
    if (seasonSelect) seasonSelect.value = data.season;
    const gwInput = document.getElementById("hist-gw-select");
    if (gwInput) gwInput.value = data.current_gw;
    const squadGw = document.getElementById("hist-squad-gw");
    if (squadGw) squadGw.textContent = data.current_gw;

    // Header Historical HUD Badges
    const hudSeason = document.getElementById("hist-hud-season");
    if (hudSeason) hudSeason.textContent = data.season;
    const hudGw = document.getElementById("hist-hud-gw");
    if (hudGw) hudGw.textContent = `GW ${data.current_gw}`;
    const hudPts = document.getElementById("hist-hud-pts");
    if (hudPts) hudPts.textContent = `${data.total_net_points || 0} pts`;
    const hudBank = document.getElementById("hist-hud-bank");
    if (hudBank) hudBank.textContent = `£${((data.bank_tenths || 0) / 10).toFixed(1)}m`;
    const hudFt = document.getElementById("hist-hud-ft");
    if (hudFt) hudFt.textContent = data.free_transfers;
    const hudChip = document.getElementById("hist-hud-chip");
    if (hudChip) hudChip.textContent = data.active_chip || "None";

    // Pitch & In-tab Badges
    const badgePts = document.getElementById("hist-badge-pts");
    if (badgePts) badgePts.textContent = `Total Net: ${data.total_net_points || 0} pts`;
    const badgeBank = document.getElementById("hist-badge-bank");
    if (badgeBank) badgeBank.textContent = `Bank: £${((data.bank_tenths || 0) / 10).toFixed(1)}m`;
    const badgeFt = document.getElementById("hist-badge-ft");
    if (badgeFt) badgeFt.textContent = `Free Tx: ${data.free_transfers}`;
    const badgeChip = document.getElementById("hist-badge-chip");
    if (badgeChip) badgeChip.textContent = `Chip: ${data.active_chip || "None"}`;

    const chipSelect = document.getElementById("hist-chip-select");
    if (chipSelect) chipSelect.value = data.active_chip || "";

    // Render Pitch
    renderHistoricalPitch(data.squad || []);
    renderHistoricalStagedTransfers(data.transfers_staged || []);

    // Synchronize chip-start-gw input if present
    const chipGwInput = document.getElementById("chip-start-gw");
    if (chipGwInput) chipGwInput.value = data.current_gw;

    // Refresh matchday center
    await loadHistoricalOverview();

    // If chip tab is currently active, refresh chip strategy view
    const chipsTab = document.getElementById("tab-chips");
    if (chipsTab && chipsTab.classList.contains("active")) {
      loadChipStrategy();
    }
  } catch (err) {
    console.error("Failed to load historical session:", err);
    showToast(`Error loading simulation ${sessionId}: ${err.message}`, true);
  }
}

function renderEmptyHistoricalSquad() {
  ["gkp", "def", "mid", "fwd"].forEach(pos => {
    const el = document.getElementById(`hist-pitch-${pos}`);
    if (el) el.innerHTML = "";
  });
  const bench = document.getElementById("hist-pitch-bench");
  if (bench) bench.innerHTML = `<div class="text-muted text-sm" style="padding: 1rem;">No simulation active. Click "+ New Sim" to begin.</div>`;
}

function renderHistoricalPitch(squad) {
  const gkpRow = document.getElementById("hist-pitch-gkp");
  const defRow = document.getElementById("hist-pitch-def");
  const midRow = document.getElementById("hist-pitch-mid");
  const fwdRow = document.getElementById("hist-pitch-fwd");
  const benchRow = document.getElementById("hist-pitch-bench");

  if (!gkpRow || !benchRow) return;

  gkpRow.innerHTML = "";
  defRow.innerHTML = "";
  midRow.innerHTML = "";
  fwdRow.innerHTML = "";
  benchRow.innerHTML = "";

  const starters = squad.filter(p => p.is_starter);
  const bench = squad.filter(p => p.is_bench).sort((a, b) => (a.bench_order || 99) - (b.bench_order || 99));

  const renderCard = (p, isBench = false) => {
    const div = document.createElement("div");
    div.className = "player-card";
    if (p.is_captain) div.style.borderColor = "var(--accent-gold)";
    else if (p.is_vice_captain) div.style.borderColor = "#94a3b8";

    div.innerHTML = `
      <div style="font-size: 0.65rem; color: #94a3b8; font-weight: bold;">${p.pos_abbr} · ${escapeHtml(p.team_short)}</div>
      <div style="font-weight: 700; color: #fff; font-size: 0.82rem; margin: 2px 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 90px;" title="${escapeHtml(p.name)}">
        ${escapeHtml(p.name)}
      </div>
      <div style="display: flex; justify-content: space-between; font-size: 0.68rem; color: #cbd5e1; width: 100%;">
        <span>${p.selling_price_fmt}</span>
        <span style="color: var(--accent-green); font-weight: bold;">${p.total_points}p</span>
      </div>
      <div class="card-quick-actions" style="margin-top: 4px;">
        <button class="quick-btn ${p.is_captain ? 'active-role' : ''}" data-act="cap" title="Set Captain">C</button>
        <button class="quick-btn ${p.is_vice_captain ? 'active-role' : ''}" data-act="vc" title="Set Vice Captain">V</button>
        <button class="quick-btn" data-act="swap" style="color: #38bdf8;" title="Transfer Out / Swap">⇄</button>
      </div>
    `;

    // Button actions
    div.querySelector('[data-act="cap"]').addEventListener("click", async (e) => {
      e.stopPropagation();
      await updateHistoricalLineupRoles(p.player_id, null);
    });
    div.querySelector('[data-act="vc"]').addEventListener("click", async (e) => {
      e.stopPropagation();
      await updateHistoricalLineupRoles(null, p.player_id);
    });
    div.querySelector('[data-act="swap"]').addEventListener("click", (e) => {
      e.stopPropagation();
      openHistoricalSwapModal(p);
    });

    return div;
  };

  starters.forEach(p => {
    const card = renderCard(p, false);
    if (p.pos_abbr === "GKP") gkpRow.appendChild(card);
    else if (p.pos_abbr === "DEF") defRow.appendChild(card);
    else if (p.pos_abbr === "MID") midRow.appendChild(card);
    else if (p.pos_abbr === "FWD") fwdRow.appendChild(card);
  });

  bench.forEach((p, idx) => {
    const card = renderCard(p, true);
    card.style.opacity = "0.85";
    benchRow.appendChild(card);
  });
}

function renderHistoricalStagedTransfers(staged) {
  const countEl = document.getElementById("hist-staged-count");
  const listEl = document.getElementById("hist-staged-tx-list");
  if (!listEl) return;

  if (countEl) countEl.textContent = staged.length;

  if (staged.length === 0) {
    listEl.innerHTML = `<div class="text-muted text-sm">No transfers staged. Click ⇄ on any player above to swap.</div>`;
    return;
  }

  listEl.innerHTML = staged.map(st => {
    const costFormatted = st.cost_tenths > 0 ? `-£${(st.cost_tenths/10).toFixed(1)}m` : `+£${(Math.abs(st.cost_tenths)/10).toFixed(1)}m`;
    return `
      <div style="display: flex; justify-content: space-between; align-items: center; padding: 4px 8px; background: rgba(255,255,255,0.04); border-radius: 4px; margin-bottom: 4px;">
        <div>
          <span style="color: #f87171; text-decoration: line-through;">${escapeHtml(st.out_name)}</span>
          <span style="color: #94a3b8; margin: 0 4px;">➔</span>
          <span style="color: #34d399; font-weight: 600;">${escapeHtml(st.in_name)}</span>
        </div>
        <span style="font-size: 0.75rem; color: #fbbf24;">${costFormatted}</span>
      </div>
    `;
  }).join("");
}

async function updateHistoricalLineupRoles(newCapId, newVcId) {
  if (!histState.sessionId || !histState.sessionData) return;
  const squad = histState.sessionData.squad || [];
  const starters = squad.filter(p => p.is_starter).map(p => p.player_id);
  const bench = squad.filter(p => p.is_bench).sort((a, b) => a.bench_order - b.bench_order).map(p => p.player_id);

  let cap = newCapId || squad.find(p => p.is_captain)?.player_id || starters[0];
  let vc = newVcId || squad.find(p => p.is_vice_captain)?.player_id || starters[1];

  if (cap === vc) {
    vc = starters.find(id => id !== cap) || cap;
  }

  try {
    await api(`/api/historical/simulations/${histState.sessionId}/lineup`, {
      method: "POST",
      body: JSON.stringify({
        starting_ids: starters,
        bench_ids: bench,
        captain_id: cap,
        vice_captain_id: vc,
      }),
    });
    showToast("Lineup captaincy updated.");
    await loadHistoricalSession(histState.sessionId);
  } catch (err) {
    showToast(err.message, true);
  }
}

// ----------------------------------------------------------------------------
// Swap / Transfer Modal
// ----------------------------------------------------------------------------

async function openHistoricalSwapModal(outPlayer) {
  histState.swapOutPlayer = outPlayer;
  const modal = document.getElementById("hist-swap-modal");
  const title = document.getElementById("hist-swap-modal-title");
  const searchInput = document.getElementById("hist-swap-search");
  const posFilter = document.getElementById("hist-swap-pos-filter");
  const list = document.getElementById("hist-swap-candidates-list");

  if (!modal || !list) return;

  if (title) title.textContent = `Swap ${outPlayer.name} (${outPlayer.pos_abbr} - ${outPlayer.selling_price_fmt})`;
  if (posFilter) posFilter.value = outPlayer.pos_abbr;
  if (searchInput) searchInput.value = "";

  modal.classList.remove("hidden");
  modal.style.display = "flex";
  list.innerHTML = `<div class="text-center text-muted" style="padding: 2rem;">Loading candidates from Gameweek ${histState.gameweek} snapshot...</div>`;

  try {
    const data = await api(`/api/players?search=&all=true`);
    const allPlayers = data.players || [];

    const renderCandidates = () => {
      const q = (searchInput?.value || "").toLowerCase().trim();
      const pos = posFilter?.value || "ALL";

      const filtered = allPlayers.filter(p => {
        if (pos !== "ALL" && p.position !== pos && p.pos_abbr !== pos) return false;
        if (q && !p.name.toLowerCase().includes(q) && !(p.team || "").toLowerCase().includes(q)) return false;
        // Don't show players already in current squad
        if (histState.sessionData && histState.sessionData.squad && histState.sessionData.squad.some(s => s.player_id === p.id)) return false;
        return true;
      }).slice(0, 50);

      list.innerHTML = `
        <table class="data-table" style="width: 100%; font-size: 0.85rem;">
          <thead>
            <tr>
              <th>Player</th>
              <th>Club</th>
              <th>Pos</th>
              <th>Price</th>
              <th>Pts</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            ${filtered.map(cand => `
              <tr>
                <td style="font-weight: 600;">${escapeHtml(cand.name)}</td>
                <td style="color: #94a3b8;">${escapeHtml(cand.team)}</td>
                <td><span class="badge">${escapeHtml(cand.position || cand.pos_abbr)}</span></td>
                <td>£${(cand.price_tenths / 10).toFixed(1)}m</td>
                <td style="color: var(--accent-green); font-weight: bold;">${cand.total_points || 0}</td>
                <td>
                  <button class="btn btn-primary btn-xs btn-stage-swap" data-in-id="${cand.id}">Transfer In</button>
                </td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      `;

      list.querySelectorAll(".btn-stage-swap").forEach(b => {
        b.addEventListener("click", async () => {
          const inId = parseInt(b.getAttribute("data-in-id"), 10);
          await stageHistoricalTransfer(outPlayer.player_id, inId);
          modal.style.display = "none";
        });
      });
    };

    renderCandidates();
    if (searchInput) searchInput.oninput = renderCandidates;
    if (posFilter) posFilter.onchange = renderCandidates;
  } catch (err) {
    list.innerHTML = `<div class="text-danger" style="padding: 1rem;">Failed to load player list: ${err.message}</div>`;
  }
}

async function stageHistoricalTransfer(outId, inId) {
  if (!histState.sessionId) return;
  try {
    const res = await api(`/api/historical/simulations/${histState.sessionId}/transfers`, {
      method: "POST",
      body: JSON.stringify({ out_id: outId, in_id: inId }),
    });
    showToast(`Staged transfer: ${res.staged?.out_name} ➔ ${res.staged?.in_name}`);
    await loadHistoricalSession(histState.sessionId);
  } catch (err) {
    showToast(`Transfer failed: ${err.message}`, true);
  }
}

// ----------------------------------------------------------------------------
// Resolution & Report Modals
// ----------------------------------------------------------------------------

function showHistoricalResolutionModal(res) {
  const modal = document.getElementById("hist-modal");
  const title = document.getElementById("hist-modal-title");
  const body = document.getElementById("hist-modal-body");
  if (!modal || !body) return;

  if (title) title.textContent = `Gameweek ${res.gameweek} Matchday Result`;

  const capName = res.starters_points.find(s => s.player_id === res.effective_captain_id)?.name || `ID ${res.effective_captain_id}`;
  const autosubsHtml = (res.autosubs && res.autosubs.length > 0)
    ? res.autosubs.map(a => `<div style="font-size: 0.85rem; color: #38bdf8;">🔄 Auto-sub: ${a.out_name} (0 mins) ➔ ${a.in_name}</div>`).join("")
    : `<div class="text-muted text-sm">No automatic substitutions required.</div>`;

  const divergence = res.human_engine_divergence || {};
  const deltaColor = divergence.point_delta_vs_engine > 0 ? "#34d399" : (divergence.point_delta_vs_engine < 0 ? "#f87171" : "#94a3b8");

  body.innerHTML = `
    <div style="display: flex; gap: 1rem; margin-bottom: 1.25rem;">
      <div class="card" style="flex: 1; text-align: center; padding: 1rem; background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.3);">
        <div style="font-size: 0.8rem; color: #10b981; font-weight: bold;">NET POINTS</div>
        <div style="font-size: 2.2rem; font-weight: 800; color: #fff;">${res.net_points}</div>
        <div style="font-size: 0.75rem; color: #94a3b8;">Gross: ${res.gross_points} | Hits: -${res.transfer_hits}</div>
      </div>
      <div class="card" style="flex: 1; text-align: center; padding: 1rem;">
        <div style="font-size: 0.8rem; color: #fbbf24; font-weight: bold;">CAPTAIN CONTRIB</div>
        <div style="font-size: 1.8rem; font-weight: 800; color: #fbbf24;">${res.captain_points}p</div>
        <div style="font-size: 0.75rem; color: #cbd5e1;">${escapeHtml(capName)} ${res.captain_promoted ? '(Vice Promoted)' : ''}</div>
      </div>
      <div class="card" style="flex: 1; text-align: center; padding: 1rem;">
        <div style="font-size: 0.8rem; color: #38bdf8; font-weight: bold;">ENGINE BENCHMARK</div>
        <div style="font-size: 1.8rem; font-weight: 800; color: ${deltaColor};">
          ${divergence.point_delta_vs_engine > 0 ? '+' : ''}${divergence.point_delta_vs_engine || 0} pts
        </div>
        <div style="font-size: 0.75rem; color: #94a3b8;">Engine v1.2.5: ${res.engine_net_points} pts</div>
      </div>
    </div>

    <div style="margin-bottom: 1rem;">
      <h4 style="margin: 0 0 0.5rem 0; font-size: 0.9rem;">Substitutions & Bench Impact</h4>
      ${autosubsHtml}
    </div>

    <div>
      <h4 style="margin: 0 0 0.5rem 0; font-size: 0.9rem;">Starting XI Points Breakdown</h4>
      <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 0.5rem;">
        ${res.starters_points.map(s => `
          <div style="background: rgba(15, 23, 42, 0.7); border: 1px solid rgba(255,255,255,0.06); padding: 0.4rem 0.6rem; border-radius: 6px;">
            <div style="font-weight: 600; font-size: 0.8rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
              ${escapeHtml(s.name)} ${s.is_effective_captain ? '<span style="color: #fbbf24; font-weight: bold;">(C)</span>' : ''}
            </div>
            <div style="display: flex; justify-content: space-between; font-size: 0.72rem; color: #94a3b8; margin-top: 2px;">
              <span>${s.minutes}'</span>
              <strong style="color: var(--accent-green); font-size: 0.85rem;">${s.points} pts</strong>
            </div>
          </div>
        `).join("")}
      </div>
    </div>
  `;

  modal.classList.remove("hidden");
  modal.style.display = "flex";
}

function showHistoricalReportModal(rep) {
  const modal = document.getElementById("hist-modal");
  const title = document.getElementById("hist-modal-title");
  const body = document.getElementById("hist-modal-body");
  if (!modal || !body) return;

  if (title) title.textContent = `Historical Replay Benchmark Report: ${rep.session_id}`;

  const deltaFormatted = (rep.human_vs_engine_delta || 0) > 0 ? `+${rep.human_vs_engine_delta}` : rep.human_vs_engine_delta;

  body.innerHTML = `
    <div style="display: grid; grid-template-columns: repeat(4, 1fr)); gap: 0.8rem; margin-bottom: 1.5rem;">
      <div class="card" style="padding: 0.8rem; text-align: center;">
        <div class="text-muted text-xs">TOTAL NET POINTS</div>
        <div style="font-size: 1.6rem; font-weight: bold; color: var(--accent-green);">${rep.total_net_points}</div>
      </div>
      <div class="card" style="padding: 0.8rem; text-align: center;">
        <div class="text-muted text-xs">ENGINE BASELINE</div>
        <div style="font-size: 1.6rem; font-weight: bold; color: #94a3b8;">${rep.engine_baseline_total_net_points || '-'}</div>
      </div>
      <div class="card" style="padding: 0.8rem; text-align: center;">
        <div class="text-muted text-xs">HUMAN DELTA</div>
        <div style="font-size: 1.6rem; font-weight: bold; color: #38bdf8;">${deltaFormatted || '0'} pts</div>
      </div>
      <div class="card" style="padding: 0.8rem; text-align: center;">
        <div class="text-muted text-xs">TRANSFERS MADE</div>
        <div style="font-size: 1.6rem; font-weight: bold; color: #cbd5e1;">${rep.total_transfers_made} (-${rep.total_transfer_hits}p)</div>
      </div>
    </div>

    <div style="background: rgba(0,0,0,0.2); padding: 1rem; border-radius: 8px; border: 1px solid rgba(255,255,255,0.08);">
      <h4 style="margin: 0 0 0.6rem 0;">Decision Support Audit</h4>
      <div style="font-size: 0.85rem; line-height: 1.6; color: #cbd5e1;">
        <div>• <strong>Gameweeks Completed:</strong> ${rep.gameweeks_completed} / 38</div>
        <div>• <strong>Human Overrides:</strong> ${rep.override_count} total decisions differed from frozen engine recommendation.</div>
        <div>• <strong>Override Value:</strong> ${rep.override_positive_count} helped score (+), ${rep.override_negative_count} hurt score (-).</div>
        <div>• <strong>Captaincy Contribution:</strong> ${rep.captain_points} total captain points (${rep.captain_promotions} vice-captain promotions).</div>
        <div>• <strong>Autosub Events:</strong> ${rep.autosubs_count} bench players promoted.</div>
      </div>
    </div>
  `;

  modal.classList.remove("hidden");
  modal.style.display = "flex";
}

async function renderHistoricalEvaluationSummary() {
  const ptsEl = document.getElementById("hist-eval-pts");
  const baseEl = document.getElementById("hist-eval-baseline-pts");
  const deltaEl = document.getElementById("hist-eval-delta");
  const hitsEl = document.getElementById("hist-eval-hits");
  const ledgerEl = document.getElementById("hist-eval-ledger-container");

  if (!histState.sessionId) {
    if (ptsEl) ptsEl.textContent = "- pts";
    if (baseEl) baseEl.textContent = "- pts";
    if (deltaEl) deltaEl.textContent = "-";
    if (hitsEl) hitsEl.textContent = "0 pts";
    if (ledgerEl) ledgerEl.innerHTML = `<p class="text-muted text-sm">No simulation active. Start or select a simulation session to view benchmark progression.</p>`;
    return;
  }

  try {
    const report = await api(`/api/historical/simulations/${histState.sessionId}/report`);
    if (ptsEl) ptsEl.textContent = `${report.total_net_points} pts`;
    if (baseEl) baseEl.textContent = `${report.engine_baseline_total_net_points || '-'} pts`;

    if (deltaEl) {
      const d = report.human_vs_engine_delta || 0;
      deltaEl.textContent = `${d > 0 ? '+' : ''}${d} pts`;
      deltaEl.style.color = d > 0 ? "var(--accent-green)" : (d < 0 ? "#f87171" : "#cbd5e1");
    }

    if (hitsEl) hitsEl.textContent = `-${report.total_transfer_hits * 4} pts (${report.total_transfer_hits} hits)`;

    const history = histState.sessionData?.history || [];
    if (history.length === 0) {
      if (ledgerEl) ledgerEl.innerHTML = `<p class="text-muted text-sm">No gameweeks resolved yet. Advance gameweeks with "▶ Run Matchday" to build the progression log.</p>`;
      return;
    }

    if (ledgerEl) {
      ledgerEl.innerHTML = `
        <h4 style="margin: 0 0 0.75rem 0; font-size: 0.95rem;">Matchday Progression History</h4>
        <div style="overflow-x: auto;">
          <table class="data-table" style="width: 100%; font-size: 0.85rem;">
            <thead>
              <tr>
                <th style="text-align: center;">GW</th>
                <th style="text-align: center;">Net Pts</th>
                <th style="text-align: center;">Gross Pts</th>
                <th style="text-align: center;">Hits</th>
                <th>Captain</th>
                <th>Chip</th>
                <th style="text-align: center;">Engine Baseline</th>
                <th style="text-align: center;">Human vs Engine</th>
              </tr>
            </thead>
            <tbody>
              ${history.map(h => {
                const diff = (h.net_points || 0) - (h.engine_net_points || 0);
                const diffColor = diff > 0 ? '#34d399' : (diff < 0 ? '#f87171' : '#94a3b8');
                return `
                  <tr>
                    <td style="text-align: center; font-weight: bold;">GW ${h.gameweek}</td>
                    <td style="text-align: center; font-weight: 700; color: var(--accent-green);">${h.net_points}</td>
                    <td style="text-align: center;">${h.gross_points}</td>
                    <td style="text-align: center; color: ${h.transfer_hits > 0 ? '#f87171' : '#94a3b8'};">-${(h.transfer_hits || 0) * 4}</td>
                    <td>${escapeHtml(h.effective_captain_name || 'C')} (${h.captain_points || 0}p)</td>
                    <td><span class="badge badge-sm">${escapeHtml(h.active_chip || 'None')}</span></td>
                    <td style="text-align: center; color: #38bdf8;">${h.engine_net_points !== undefined ? h.engine_net_points : '-'}</td>
                    <td style="text-align: center; font-weight: bold; color: ${diffColor};">${diff > 0 ? '+' : ''}${diff}</td>
                  </tr>
                `;
              }).join("")}
            </tbody>
          </table>
        </div>
      `;
    }
  } catch (err) {
    if (ledgerEl) ledgerEl.innerHTML = `<p class="text-danger text-sm">Failed to load simulation report: ${escapeHtml(err.message)}</p>`;
  }
}

function showHistoricalRecommendationsModal(recs) {
  const modal = document.getElementById("hist-modal");
  const title = document.getElementById("hist-modal-title");
  const body = document.getElementById("hist-modal-body");
  if (!modal || !body) return;

  const engVer = recs.engine_version || "v1.3.5";
  if (title) title.textContent = `Decision Engine Recommendations (${engVer} - GW ${recs.gameweek})`;

  const chipRec = recs.recommended_chip;
  const chipBadge = chipRec
    ? `<span class="badge" style="background: var(--accent-purple); color: #fff; font-weight: bold; font-size: 0.85rem; padding: 4px 10px;">⚡ ${chipRec.toUpperCase().replace('_', ' ')}</span>`
    : `<span class="badge" style="background: rgba(255,255,255,0.1); color: #94a3b8; font-size: 0.85rem; padding: 4px 10px;">Save Chips (None Recommended)</span>`;

  const txsHtml = (recs.recommended_transfers && recs.recommended_transfers.length > 0)
    ? recs.recommended_transfers.map(t => `
        <div style="padding: 0.6rem; background: rgba(255,255,255,0.04); border-radius: 6px; margin-bottom: 0.4rem; display: flex; justify-content: space-between; align-items: center;">
          <div>
            <span style="color: #f87171; text-decoration: line-through;">${escapeHtml(t.out_name)}</span>
            <span style="color: #94a3b8; margin: 0 6px;">➔</span>
            <span style="color: #34d399; font-weight: 600;">${escapeHtml(t.in_name)}</span>
          </div>
          <span style="color: var(--accent-green); font-weight: bold;">+${t.xp_gain} xP</span>
        </div>
      `).join("")
    : `<div class="text-muted text-sm">Engine suggests rolling the free transfer (no moves).</div>`;

  body.innerHTML = `
    <div style="margin-bottom: 1.25rem; background: rgba(255,255,255,0.02); padding: 0.8rem; border-radius: 8px; border: 1px solid rgba(255,255,255,0.06);">
      <div style="font-size: 0.8rem; color: #94a3b8; text-transform: uppercase; margin-bottom: 0.35rem; font-weight: 600;">Seasonal Chip Strategy Evaluation</div>
      <div style="display: flex; align-items: center; justify-content: space-between;">
        <div>Recommended Chip for Deadline:</div>
        <div>${chipBadge}</div>
      </div>
    </div>

    <div style="margin-bottom: 1.25rem;">
      <h4 style="margin: 0 0 0.5rem 0; font-size: 0.95rem;">Recommended Transfers (${engVer} Baseline)</h4>
      ${txsHtml}
    </div>

    <div style="margin-bottom: 1.25rem;">
      <h4 style="margin: 0 0 0.5rem 0; font-size: 0.95rem;">Predicted Optimal Lineup</h4>
      <div style="font-size: 0.85rem; color: #94a3b8;">
        Lineup Expected Value: <strong style="color: #38bdf8;">${recs.predicted_lineup_xp} xP</strong>
      </div>
    </div>

    <div style="display: flex; gap: 0.5rem; justify-content: flex-end; border-top: 1px solid rgba(255,255,255,0.08); padding-top: 1rem;">
      <button class="btn btn-primary" id="btn-hist-apply-all-recs" style="background: linear-gradient(135deg, #059669, #10b981); font-weight: 700;">
        ⚡ Apply All Engine Recommendations
      </button>
    </div>
  `;

  const btnApplyAll = document.getElementById("btn-hist-apply-all-recs");
  if (btnApplyAll) {
    btnApplyAll.addEventListener("click", async () => {
      btnApplyAll.disabled = true;
      btnApplyAll.textContent = "Applying...";
      try {
        // 1. Stage transfers if any
        if (recs.recommended_transfers && recs.recommended_transfers.length > 0) {
          await api(`/api/historical/simulations/${histState.sessionId}/transfers`, {
            method: "POST",
            body: JSON.stringify({ action: "clear" }),
          });
          for (const t of recs.recommended_transfers) {
            await api(`/api/historical/simulations/${histState.sessionId}/transfers`, {
              method: "POST",
              body: JSON.stringify({ out_id: t.out_id, in_id: t.in_id }),
            });
          }
        }
        // 2. Set lineup and captaincy
        if (recs.recommended_starters && recs.recommended_starters.length === 11) {
          await api(`/api/historical/simulations/${histState.sessionId}/lineup`, {
            method: "POST",
            body: JSON.stringify({
              starting_ids: recs.recommended_starters,
              bench_ids: recs.recommended_bench,
              captain_id: recs.recommended_captain,
              vice_captain_id: recs.recommended_vice_captain,
            }),
          });
        }
        // 3. Set chip if recommended
        if (recs.recommended_chip) {
          await api(`/api/historical/simulations/${histState.sessionId}/chip`, {
            method: "POST",
            body: JSON.stringify({ chip: recs.recommended_chip }),
          });
        }
        showToast("Successfully applied all engine recommendations!");
        modal.style.display = "none";
        await loadHistoricalSession(histState.sessionId);
      } catch (err) {
        showToast(`Failed to apply recommendations: ${err.message}`, true);
      } finally {
        btnApplyAll.disabled = false;
        btnApplyAll.textContent = "⚡ Apply All Engine Recommendations";
      }
    });
  }

  modal.classList.remove("hidden");
  modal.style.display = "flex";
}

// App Initialization
document.addEventListener("DOMContentLoaded", async () => {
  initTabs();
  initModality();
  initModal();
  initEventListeners();
  initStrategicStudio();
  initHistoricalTimeMachine();
  await syncGameweekAndScoresAtStartup();
  await loadTeams();
  await loadAllLeaguePlayers();
  await loadOverview();
});


