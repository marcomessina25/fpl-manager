// FPL Manager Pro — Interactive Dashboard Client Controller

const state = {
  activeTeamId: null,
  teams: [],
  currentSquad: null,
  currentLineup: null,
  activeGameweek: 1,
  selectedGameweek: null,
  lineupMode: "auto",
  subbingPlayer: null,
  allLeaguePlayers: [],
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
      if (target === "decisions") {
        loadDecisions();
        loadAllLeaguePlayers();
        if (state.currentSquad && state.currentSquad.players) {
          populateDecisionLoggerSquad(state.currentSquad.players);
        }
      }
      if (target === "chips") loadChipStrategy();
      if (target === "evaluation") loadEvaluation();
      if (target === "live") loadLiveMatchday();
      if (target === "advisor") loadAdvisor();
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
      const hitsStr = (lineup.transfer_hits && lineup.transfer_hits > 0)
        ? ` (Hits: -${lineup.transfer_hits * 4}pt)`
        : "";
      const chipStr = lineup.chip_played ? ` · Chip: ${lineup.chip_played.toUpperCase()}` : "";

      document.getElementById("banner-subtitle").innerHTML = `Matchday Result: ${ptsStr} | Captain: <strong>${capStr}</strong> | Moves: ${movesStr}${hitsStr}${chipStr}`;
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
        hitsInput.placeholder = `Auto-calculated (${curDec.transfer_hits || 0})`;
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

  try {
    const res = await api("/api/transfers/execute", {
      method: "POST",
      body: JSON.stringify({
        team_id: state.activeTeamId,
        gameweek: gw,
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

  const startGw = document.getElementById("chip-start-gw").value;
  const startParam = startGw ? `&start_gw=${startGw}` : "";

  try {
    const data = await api(`/api/chips?team=${state.activeTeamId}${startParam}`);
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
              hitsInput.placeholder = `Auto-calculated (${dec.transfer_hits || 0})`;
            }
          }
        } catch (err) {}
      }
    });
  }

  // Transfers & Studio Buttons
  document.getElementById("btn-run-suggest-tx").addEventListener("click", runSuggestTransfers);
  document.getElementById("btn-run-wildcard").addEventListener("click", runWildcard);
  document.getElementById("btn-run-plan").addEventListener("click", runPlanner);
  document.getElementById("btn-run-chip-strategy").addEventListener("click", loadChipStrategy);
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

function loadAdvisor() {
  // Retain existing results if already computed
}

async function runAdvisor() {
  const container = document.getElementById("advisor-results-container");
  if (!container) return;

  const personaSelect = document.getElementById("adv-persona");
  const providerSelect = document.getElementById("adv-provider");
  const apiKeyInput = document.getElementById("adv-api-key");
  const gwInput = document.getElementById("live-gw");
  let gw = gwInput ? parseInt(gwInput.value) : null;
  if (!gw) gw = state.activeGameweek;

  const persona = personaSelect ? personaSelect.value : "devil_advocate";
  const provider = providerSelect ? providerSelect.value : "auto";
  const apiKey = apiKeyInput ? apiKeyInput.value.trim() : null;

  container.innerHTML = `
    <div style="padding: 2.5rem 1rem; text-align: center; color: var(--text-muted);">
      <div class="spinner" style="margin: 0 auto 1rem auto; width: 32px; height: 32px; border: 3px solid var(--border-color); border-top-color: var(--accent-purple); border-radius: 50%; animation: spin 0.8s linear infinite;"></div>
      <p>Synthesizing briefing dossier and consulting ${persona.replace('_', ' ').toUpperCase()} advisor with deterministic guardrails...</p>
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

    const data = await api("/api/advise", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    renderAdvisorResults(data);
    showToast("AI Strategic Advisory Generated!");
  } catch (err) {
    container.innerHTML = `
      <div class="alert alert-danger" style="margin-top: 1rem;">
        Failed to generate AI Advisory: ${escapeHtml(err.message)}
      </div>
    `;
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
            Persona: <strong>${escapeHtml(data.persona.replace('_', ' ').toUpperCase())}</strong> | 
            Engine: <code>${escapeHtml(data.provider_used)}</code>
          </div>
        </div>
        <div>${verdictBadge}</div>
      </div>

      <div style="background: var(--bg-input); border-radius: 8px; padding: 1.2rem; margin-bottom: 1.2rem;">
        <div style="font-size: 0.8rem; font-weight: 700; color: var(--accent-purple); text-transform: uppercase; margin-bottom: 0.4rem;">
          Executive Tactical Critique
        </div>
        <div class="advisor-markdown-content">${escapeHtml(data.analysis_markdown)}</div>
      </div>
  `;

  if (critiques.length > 0) {
    html += `
      <div style="margin-bottom: 1.2rem;">
        <h4 style="font-size: 0.95rem; margin-bottom: 0.5rem; color: #fbbf24;">⚡ Key Contrarian & Trap Risks</h4>
        <ul style="padding-left: 1.2rem; display: flex; flex-direction: column; gap: 0.35rem; font-size: 0.88rem;">
          ${critiques.map(c => `<li>${c}</li>`).join('')}
        </ul>
      </div>
    `;
  }

  if (tactical.length > 0) {
    html += `
      <div style="margin-bottom: 1.2rem;">
        <h4 style="font-size: 0.95rem; margin-bottom: 0.5rem; color: #38bdf8;">📋 Tactical & Press Conference Matchup Signals</h4>
        <ul style="padding-left: 1.2rem; display: flex; flex-direction: column; gap: 0.35rem; font-size: 0.88rem;">
          ${tactical.map(t => `<li>${t}</li>`).join('')}
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

  const gwInput = document.getElementById("live-gw");
  let gw = gwInput ? parseInt(gwInput.value) : null;
  if (!gw) gw = state.activeGameweek;

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
  const risks = dossier.strategic_ownership_risks || [];
  const recs = dossier.top_transfer_recommendations || [];

  let html = `
    <div class="advisor-card">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.2rem;">
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
          <div class="ps-stat-value">${fin.free_transfers || 1}</div>
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
              <strong>${escapeHtml(a.name)}</strong> (${a.chance_pct !== null ? a.chance_pct + '% chance' : 'Status: ' + a.status}): 
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
          ${recs.slice(0, 3).map(r => `
            <div style="background: var(--bg-input); border-radius: 6px; padding: 0.5rem 0.8rem; font-size: 0.85rem; display: flex; justify-content: space-between; align-items: center;">
              <div>
                🔄 <strong>${escapeHtml(r.out_name)}</strong> ➔ <strong>${escapeHtml(r.in_name)}</strong>
              </div>
              <div style="font-weight: 800; color: var(--accent-green);">
                +${r.net_delta} xP
              </div>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }

  // EO risk
  if (risks.length > 0) {
    html += `
      <div>
        <h4 style="font-size: 0.95rem; margin-bottom: 0.5rem; color: var(--accent-blue);">🛡️ Template & Effective Ownership Exposure</h4>
        <div style="display: flex; flex-wrap: wrap; gap: 0.5rem;">
          ${risks.map(r => `
            <div style="background: var(--bg-input); border-radius: 6px; padding: 0.4rem 0.7rem; font-size: 0.8rem;">
              <strong>${escapeHtml(r.name)}</strong> (${r.team}): <strong>${r.eo_pct}% EO</strong> (${r.owned_by_squad ? '✅ Owned' : '❌ Not Owned'})
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }

  html += `</div>`;
  container.innerHTML = html;
}

// App Initialization
document.addEventListener("DOMContentLoaded", async () => {
  initTabs();
  initModal();
  initEventListeners();
  await loadTeams();
  await loadAllLeaguePlayers();
});
