// FPL Manager Pro — Interactive Dashboard Client Controller

const state = {
  activeTeamId: null,
  teams: [],
  currentSquad: null,
  currentLineup: null,
  activeGameweek: 1,
  selectedGameweek: null,
  lineupMode: "auto",
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
      if (target === "decisions") loadDecisions();
      if (target === "chips") loadChipStrategy();
      if (target === "evaluation") loadEvaluation();
    });
  });

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
    if (activeObj && activeObj.gameweek) {
      state.activeGameweek = activeObj.gameweek;
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
    state.activeGameweek = data.gameweek || (activeObj && activeObj.gameweek) || (data.state && data.state.gameweek) || 3;

    const fin = data.financials || {};
    const st = data.state || {};

    document.getElementById("hud-gw").textContent = `GW${state.activeGameweek}`;
    document.getElementById("hud-bank").textContent = fin.bank_fmt || `£${((fin.bank_tenths || 0) / 10).toFixed(1)}m`;
    document.getElementById("hud-value").textContent = fin.total_team_value_fmt || "£0.0m";
    document.getElementById("hud-ft").textContent = st.free_transfers !== undefined ? st.free_transfers : 1;
    document.getElementById("hud-chips").textContent = st.chips_remaining ? st.chips_remaining.length : 0;

    // Prefill Gameweek in decision logger, lineup, chips, and evaluation
    const decGw = document.getElementById("dec-gw");
    if (decGw) decGw.value = state.activeGameweek;
    const lineupGw = document.getElementById("lineup-gw-select");
    if (lineupGw) lineupGw.value = state.activeGameweek;
    const chipStartGw = document.getElementById("chip-start-gw");
    if (chipStartGw) chipStartGw.value = state.activeGameweek;
    const evalGw = document.getElementById("eval-gw");
    if (evalGw && !evalGw.value) evalGw.value = state.activeGameweek;
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
      if (dec) {
        if (dec.actual_points !== null && dec.actual_points !== undefined) {
          badge = `<span class="gw-pill-score">${dec.actual_points} pts</span>`;
        } else {
          badge = `<span class="gw-pill-tag">Logged</span>`;
        }
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
      const capStr = lineup.captain ? `${lineup.captain.name} (C)${capPtsStr}` : "-";
      const movesStr = (lineup.transfers && lineup.transfers.length)
        ? lineup.transfers.map(t => `${t.outgoing_name} ➔ ${t.incoming_name}`).join(", ")
        : "No transfers";
      const chipStr = lineup.chip_played ? ` · Chip: ${lineup.chip_played.toUpperCase()}` : "";

      document.getElementById("banner-subtitle").innerHTML = `Matchday Result: ${ptsStr} | Captain: <strong>${capStr}</strong> | Moves: ${movesStr}${chipStr}`;
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

      const movesDesc = (lineup.transfers && lineup.transfers.length)
        ? lineup.transfers.map(t => `${t.outgoing_name} ➔ ${t.incoming_name}`).join(", ") + ` (-${lineup.transfer_hits * 4}pt)`
        : `No transfers (0pt)`;
      document.getElementById("stat-matchday-moves").textContent = movesDesc;
      document.getElementById("stat-matchday-chip").textContent = lineup.chip_played ? lineup.chip_played.toUpperCase() : "None";
    } else {
      matchdayPanel.classList.add("hidden");
    }
  }

  // Update Captain and VC sidebar
  if (lineup.captain) {
    document.getElementById("cap-name").textContent = lineup.captain.name;
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

function createPlayerCard(p, isBench = false, benchIdx = 0) {
  const card = document.createElement("div");
  card.className = "player-card";

  // Role Badge (Captain / Vice)
  let badgeHtml = "";
  if (p.role === "CAPTAIN") badgeHtml = '<div class="player-badge-role badge-cap">C</div>';
  if (p.role === "VICE_CAPTAIN") badgeHtml = '<div class="player-badge-role badge-vc">V</div>';

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

  // Quick action: click to populate decision logger
  card.addEventListener("click", () => {
    const decCap = document.getElementById("dec-captain");
    if (decCap && !decCap.value) {
      decCap.value = p.name;
      showToast(`Selected ${p.name} as Captain in Decision Logger`);
    }
  });

  return card;
}

// Decision Logger
async function handleDecisionSubmit(e) {
  e.preventDefault();
  const gw = parseInt(document.getElementById("dec-gw").value);
  const chip = document.getElementById("dec-chip").value || null;
  const captain = document.getElementById("dec-captain").value.trim();
  const vc = document.getElementById("dec-vc").value.trim();
  const transfersRaw = document.getElementById("dec-transfers").value.trim();
  const hitsRaw = document.getElementById("dec-hits").value;
  const actualRaw = document.getElementById("dec-actual-pts").value;
  const notes = document.getElementById("dec-notes").value.trim();
  const overwrite = document.getElementById("dec-overwrite").checked;

  const transfers = transfersRaw ? transfersRaw.split(",").map(t => t.trim()).filter(Boolean) : null;
  const hits = hitsRaw ? parseInt(hitsRaw) : null;
  const actual_points = actualRaw ? parseInt(actualRaw) : null;

  try {
    const payload = {
      team_id: state.activeTeamId,
      gameweek: gw,
      captain: captain,
      vice_captain: vc,
      chip: chip,
      transfers: transfers,
      hits: hits,
      actual_points: actual_points,
      notes: notes,
      overwrite: overwrite,
    };

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
      const moves = dec.transfers && dec.transfers.length ? `Moves: ${dec.transfers.map(t => `${t.outgoing_name} ➔ ${t.incoming_name}`).join(", ")}` : "No transfers";

      el.innerHTML = `
        <div class="decision-entry-header">
          <span>GW${dec.gameweek} Decision ${chipBadge}</span>
          <span>Pred: ${dec.predicted_lineup_xp.toFixed(1)} xP${scoreBadge}</span>
        </div>
        <div class="decision-entry-sub">
          Captain: <strong>${dec.captain_name}</strong> | Vice: <strong>${dec.vice_captain_name}</strong>
        </div>
        <div class="decision-entry-sub">${moves} (Hits: -${dec.transfer_hits * 4}pt)</div>
        ${dec.notes ? `<div class="decision-entry-sub" style="font-style: italic; margin-top: 0.2rem;">"${dec.notes}"</div>` : ""}
      `;
      container.appendChild(el);
    });
  } catch (err) {
    container.innerHTML = `<p class="text-muted">Failed to load decisions: ${err.message}</p>`;
  }
}

// Transfers Optimizer View
async function runSuggestTransfers() {
  const container = document.getElementById("tx-results-container");
  container.innerHTML = '<p class="text-muted">Solving branch-and-bound combinatorial transfers across the Premier League...</p>';

  const numTx = document.getElementById("tx-num").value;
  const gws = document.getElementById("tx-gws").value;
  const risk = document.getElementById("tx-risk").value;

  try {
    const data = await api(`/api/transfers?team=${state.activeTeamId}&transfers=${numTx}&gameweeks=${gws}&risk=${risk}`);
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

      card.innerHTML = `
        <div class="tx-card-header">
          <span class="tx-rank-badge">#${idx + 1} Best Move</span>
          <span class="tx-delta-xp">${opt.xp_delta >= 0 ? '+' : ''}${opt.xp_delta.toFixed(1)} xP${hitStr}</span>
        </div>
        <div class="tx-moves">${movesHtml}</div>
        <div class="stat-row">
          <span>Post-Move Bank:</span>
          <strong>£${(opt.bank_after_tenths / 10).toFixed(1)}m</strong>
        </div>
      `;
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
        <div class="panel-header">
          <h3>${mode.toUpperCase()} Optimized Squad (${totalCostFmt} spent | Remaining Bank: ${bankRemFmt})</h3>
          <span class="badge badge-success">Projected XI: ${totalLineupXp.toFixed(1)} xP</span>
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

    const stepsHtml = best.steps.map(step => {
      const txText = step.transfers && step.transfers.length
        ? step.transfers.map(t => `<span class="tx-out">OUT ${t.outgoing_name}</span> ➔ <span class="tx-in">IN ${t.incoming_name}</span>`).join("; ")
        : '<span class="text-muted">Roll Transfer (Bank FT)</span>';

      return `
        <div class="decision-entry">
          <div class="decision-entry-header">
            <span>Gameweek ${step.gameweek}</span>
            <span>Projected: ${step.projected_xp.toFixed(1)} xP (${step.hits > 0 ? `-${step.hits*4}pt hit` : '0 hit'})</span>
          </div>
          <div class="decision-entry-sub">${txText}</div>
          <div class="decision-entry-sub">FTs Available: <strong>${step.ft_available}</strong> | Bank: <strong>£${(step.bank_tenths/10).toFixed(1)}m</strong></div>
        </div>
      `;
    }).join("");

    container.innerHTML = `
      <div class="panel card" style="margin-top: 1rem;">
        <div class="panel-header">
          <h3>Optimal ${horizon}-Gameweek Roadmap (Cumulative: ${best.cumulative_net_xp.toFixed(1)} Net xP)</h3>
        </div>
        <div class="panel-body">${stepsHtml}</div>
      </div>
    `;
  } catch (err) {
    container.innerHTML = `<p class="text-muted">Planner error: ${err.message}</p>`;
  }
}

// Chip Strategy & Calendar View
async function loadChipStrategy() {
  const container = document.getElementById("chip-results-container");
  container.innerHTML = '<p class="text-muted">Evaluating Blank/Double gameweeks and computing optimal chip roadmap...</p>';

  const startGw = document.getElementById("chip-start-gw").value;
  const usedChips = document.getElementById("chip-used").value;
  const startParam = startGw ? `&start_gw=${startGw}` : "";
  const usedParam = usedChips ? `&used_chips=${usedChips}` : "";

  try {
    const data = await api(`/api/chips?team=${state.activeTeamId}${startParam}${usedParam}`);
    const sched = data.recommended_schedule || [];
    const schedHtml = sched.length
      ? sched.map(s => `<li><strong>GW${s.gameweek}</strong> [${s.gw_type}]: <strong>${s.chip.toUpperCase()}</strong> — ${s.reasoning}</li>`).join("")
      : "<li>No chips recommended in current horizon.</li>";

    container.innerHTML = `
      <div class="panel card" style="margin-top: 1rem;">
        <div class="panel-header">
          <h3>Season Segment: Gameweeks ${data.segment} (Chips reset after GW19)</h3>
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

  // Transfers & Studio Buttons
  document.getElementById("btn-run-suggest-tx").addEventListener("click", runSuggestTransfers);
  document.getElementById("btn-run-wildcard").addEventListener("click", runWildcard);
  document.getElementById("btn-run-plan").addEventListener("click", runPlanner);
  document.getElementById("btn-run-chip-strategy").addEventListener("click", loadChipStrategy);
  document.getElementById("btn-run-eval").addEventListener("click", loadEvaluation);
}

// App Initialization
document.addEventListener("DOMContentLoaded", async () => {
  initTabs();
  initModal();
  initEventListeners();
  await loadTeams();
});
