"""LLM Advisory Layer with Deterministic Guardrails for FPL Manager V0.6.

Integrates multi-provider LLM analysis (Gemini, OpenAI, Ollama, Heuristic)
with specialized personas (Devil's Advocate, Tactical Analyst, Strategic Planner).
Deterministic validation ensures that all LLM advice is strictly verified against
FPL budget, squad quota, and formation constraints before presentation.
"""

from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any
import urllib.error
import urllib.request

from .briefing import generate_manager_briefing
from .models import Player, Position
from .rules import validate_starting_lineup
from .squad_state import CurrentSquadState, load_current_squad
from .storage import SnapshotStore
from .transfers import Transfer, validate_transfers

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIRECTORY = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIRECTORY / "fpl.sqlite3"
DEFAULT_SQUAD_PATH = PROJECT_ROOT / "config" / "current_squad.json"
REPORTS_DIRECTORY = PROJECT_ROOT / "reports"
ADVISORY_REPORT_PATH = REPORTS_DIRECTORY / "llm_advisory.json"
ADVISORY_MD_PATH = REPORTS_DIRECTORY / "llm_advisory.md"

PERSONA_PROMPTS = {
    "devil_advocate": (
        "You are the Devil's Advocate for an elite Fantasy Premier League manager. "
        "Your role is to aggressively challenge complacency and groupthink. "
        "Question template picks, expose fixture difficulty traps, highlight minutes rotation risks, "
        "and warn against chasing last week's points. Be constructively skeptical and brutally honest."
    ),
    "tactical_analyst": (
        "You are a master Tactical Analyst & Press Conference Specialist for FPL. "
        "Analyze manager press conference quotes, injury doubt sentiment, tactical role shifts "
        "(e.g., inverted fullbacks, set-piece taker changes, penalty duties), and specific opposition vulnerabilities."
    ),
    "strategic_planner": (
        "You are a Macro Strategy Advisor for FPL. "
        "Focus on 3-5 gameweek planning horizons, bank flexibility, transfer rollover discipline, "
        "optimal hit timing (-4 vs long-term gain), and long-term chip timing (Wildcard, Bench Boost, Free Hit, Triple Captain)."
    ),
}


def _call_gemini_api(prompt: str, api_key: str, model: str = "gemini-1.5-flash") -> str:
    """Call Google Gemini REST API."""
    clean_key = api_key.strip()
    clean_model = (model or "gemini-1.5-flash").strip()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:generateContent?key={clean_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 2048},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            candidates = res.get("candidates", [])
            if candidates and "content" in candidates[0]:
                parts = candidates[0]["content"].get("parts", [])
                if parts:
                    return parts[0].get("text", "")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8")
            err_json = json.loads(body)
            msg = err_json.get("error", {}).get("message", body)
        except Exception:
            msg = body or str(e)
        raise RuntimeError(f"Google Gemini API error (HTTP {e.code}): {msg}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Google Gemini network error: {e.reason}") from e

    raise RuntimeError("Empty response received from Google Gemini API.")


def _call_openai_api(prompt: str, api_key: str, model: str = "gpt-4o-mini") -> str:
    """Call OpenAI REST API."""
    clean_key = api_key.strip()
    clean_model = (model or "gpt-4o-mini").strip()
    url = "https://api.openai.com/v1/chat/completions"
    payload = {
        "model": clean_model,
        "messages": [
            {"role": "system", "content": "You are an expert Fantasy Premier League tactical advisor."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.4,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {clean_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            choices = res.get("choices", [])
            if choices and "message" in choices[0]:
                return choices[0]["message"].get("content", "")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8")
            err_json = json.loads(body)
            msg = err_json.get("error", {}).get("message", body)
        except Exception:
            msg = body or str(e)
        raise RuntimeError(f"OpenAI API error (HTTP {e.code}): {msg}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"OpenAI network error: {e.reason}") from e

    raise RuntimeError("Empty response received from OpenAI API.")


def _call_ollama_api(prompt: str, host: str = "http://localhost:11434", model: str = "llama3.2") -> str:
    """Call local Ollama REST API."""
    clean_host = (host or "http://localhost:11434").rstrip("/")
    clean_model = (model or "llama3.2").strip()
    url = f"{clean_host}/api/chat"
    payload = {
        "model": clean_model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            return res.get("message", {}).get("content", "")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8")
            err_json = json.loads(body)
            msg = err_json.get("error", body)
        except Exception:
            msg = body or str(e)
        raise RuntimeError(f"Ollama API error (HTTP {e.code}): {msg}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Cannot connect to Ollama at {clean_host} ({e.reason}). Ensure Ollama daemon is running (`ollama serve`).") from e


def _heuristic_advisory(dossier: dict[str, Any], persona: str) -> dict[str, Any]:
    """Offline deterministic advisory engine synthesizing insights from dossier data."""
    gw = dossier.get("gameweek", 1)
    lineup = dossier.get("lineup", {})
    starters = lineup.get("starters", [])
    captain = lineup.get("captain", {})
    vice_captain = lineup.get("vice_captain", {})
    health_alerts = dossier.get("squad_health_alerts", [])
    ownership_risks = dossier.get("strategic_ownership_risks", [])
    transfer_recs = dossier.get("top_transfer_recommendations", [])
    financials = dossier.get("financials", {})

    proposed_transfers = []
    critique_points = []
    tactical_notes = []

    # Check health alerts safely
    flagged_starters = [
        p for p in starters
        if any((a.get("id") == p.get("id") or a.get("player_id") == p.get("id")) for a in health_alerts)
    ]
    if flagged_starters:
        names = ", ".join(p.get("name", "Unknown") for p in flagged_starters)
        critique_points.append(f"⚠️ **Health Exposure**: Starters with flags ({names}) require immediate contingency planning.")
        tactical_notes.append(f"Monitor press conference updates closely for {names}.")

    # Evaluate captaincy risk
    cap_name = captain.get("name", "Unknown")
    vice_name = vice_captain.get("name", "Unknown")
    strat_risk = dossier.get("strategic_risk", {})
    all_threats = dossier.get("strategic_ownership_risks") or strat_risk.get("top_threats_against_squad") or []
    high_eo = next((r for r in all_threats if r.get("name") == cap_name), None)
    eo_val = (high_eo.get("effective_ownership_pct") or high_eo.get("eo_pct", 0.0)) if high_eo else 0.0
    if high_eo and eo_val > 100:
        critique_points.append(f"🛡️ **Captaincy Template Trap**: Captain {cap_name} has {eo_val:.1f}% EO. Playing them protects rank but offers zero upside.")
    else:
        critique_points.append(f"⚔️ **Captaincy Differential**: {cap_name} is an active rank leverage play against the template.")

    # Strategic / transfer logic
    ft = financials.get("free_transfers", 1)
    tx_list = dossier.get("top_transfer_recommendations") or dossier.get("transfer_suggestions") or []
    if tx_list and (flagged_starters or ft >= 2):
        best_move = tx_list[0]
        if "outgoing" in best_move and "incoming" in best_move:
            out_name = best_move["outgoing"][0].get("name", "") if best_move["outgoing"] else ""
            in_name = best_move["incoming"][0].get("name", "") if best_move["incoming"] else ""
            delta = best_move.get("xp_delta") or best_move.get("net_xp_gain") or 0.0
        else:
            out_name = best_move.get("out_name", best_move.get("out", ""))
            in_name = best_move.get("in_name", best_move.get("in", ""))
            delta = best_move.get("net_delta", 0.0)

        if out_name and in_name:
            proposed_transfers.append({
                "out": out_name,
                "in": in_name,
                "rationale": f"Algorithmic top move ({delta:+.2f} xP). Resolves squad friction and capitalizes on form/fixture swing.",
            })
            tactical_notes.append(f"Swap {out_name} -> {in_name} delivers immediate fixture upgrade.")
    elif ft == 1 and not flagged_starters:
        tactical_notes.append("Roll the free transfer to accumulate 2 FTs for subsequent gameweek flexibility.")

    if persona == "devil_advocate":
        overview = (
            f"**Devil's Advocate Skepticism for Gameweek {gw}**\n\n"
            f"The current squad setup leans heavily on statistical projections that may fail to capture tactical variance. "
            f"Holding {cap_name} as captain exposes you to high volatility if their team faces a low-block defensive setup. "
            + (" Furthermore, carrying flagged players into the weekend without guaranteed starting bench cover is a critical liability." if flagged_starters else " The bench offers decent cover, but watch out for minute reductions.")
        )
    elif persona == "tactical_analyst":
        overview = (
            f"**Tactical & Press Conference Dossier Review for Gameweek {gw}**\n\n"
            f"Tactical matchups this week favor dynamic transitional wingers and set-piece aerial threats. "
            f"{cap_name} remains the focal offensive outlet, but vice-captain {vice_name} is an essential safety valve. "
            + (f"Medical staff reports on {flagged_starters[0]['name']} highlight a late fitness test." if flagged_starters else "Squad fitness appears robust across key positions.")
        )
    else:  # strategic_planner
        overview = (
            f"**Strategic Macro Blueprint for Gameweek {gw}**\n\n"
            f"You hold {financials.get('bank_fmt', '£0.0m')} in the bank and {ft} free transfer(s). "
            f"Preserving squad structure while targeting fixture swings across the next 3 fixtures will optimize points trajectory without burning unnecessary hit deductions."
        )

    return {
        "analysis_markdown": overview,
        "critique_points": critique_points,
        "tactical_notes": tactical_notes,
        "proposed_captain": cap_name,
        "proposed_vice_captain": vice_name,
        "proposed_transfers": proposed_transfers,
    }


def validate_proposed_advisory_actions(
    state: CurrentSquadState,
    all_players: list[Player],
    proposed_transfers: list[dict[str, Any]],
    proposed_captain: str | int | None,
    proposed_vice_captain: str | int | None,
) -> dict[str, Any]:
    """Deterministic validation guardrails verifying legality of proposed moves."""
    player_by_name = {p.name.lower(): p for p in all_players}
    player_by_id = {p.id: p for p in all_players}

    def _resolve_player(identifier: str | int | None) -> Player | None:
        if identifier is None:
            return None
        if isinstance(identifier, int) or (isinstance(identifier, str) and identifier.isdigit()):
            return player_by_id.get(int(identifier))
        return player_by_name.get(str(identifier).strip().lower())

    # 1. Validate Captain / Vice
    cap_player = _resolve_player(proposed_captain)
    vice_player = _resolve_player(proposed_vice_captain)

    squad_ids = set(state.player_ids)
    captain_errors = []
    if cap_player is not None:
        if cap_player.id not in squad_ids:
            captain_errors.append(f"Proposed captain {cap_player.name} is not in current squad.")
    if vice_player is not None:
        if vice_player.id not in squad_ids:
            captain_errors.append(f"Proposed vice-captain {vice_player.name} is not in current squad.")
    if cap_player and vice_player and cap_player.id == vice_player.id:
        captain_errors.append("Captain and vice-captain cannot be the same player.")

    # 2. Validate Transfers
    transfer_errors = []
    validated_transfers_list = []
    legal_transfers: list[Transfer] = []

    for t in proposed_transfers:
        out_p = _resolve_player(t.get("out"))
        in_p = _resolve_player(t.get("in"))

        if out_p is None:
            transfer_errors.append(f"Could not identify outgoing player '{t.get('out')}'.")
            continue
        if in_p is None:
            transfer_errors.append(f"Could not identify incoming player '{t.get('in')}'.")
            continue

        legal_transfers.append(Transfer(outgoing_id=out_p.id, incoming_id=in_p.id))
        validated_transfers_list.append({
            "out_id": out_p.id,
            "out_name": out_p.name,
            "in_id": in_p.id,
            "in_name": in_p.name,
            "rationale": t.get("rationale", ""),
        })

    transfer_val_res = None
    if legal_transfers:
        transfer_val_res = validate_transfers(state, all_players, legal_transfers)
        if not transfer_val_res.is_valid:
            transfer_errors.extend(transfer_val_res.errors)

    all_errors = captain_errors + transfer_errors
    is_legal = len(all_errors) == 0

    return {
        "is_legal": is_legal,
        "errors": all_errors,
        "captain_valid": len(captain_errors) == 0,
        "transfers_valid": len(transfer_errors) == 0,
        "validated_transfers": validated_transfers_list,
        "bank_after_tenths": transfer_val_res.bank_after_tenths if transfer_val_res else state.bank_tenths,
        "transfer_hits": transfer_val_res.transfer_hits if transfer_val_res else 0,
    }


def _build_llm_prompt(system_persona: str, dossier: dict[str, Any], gw: int) -> str:
    """Construct structured instruction prompt for generative AI providers."""
    return (
        f"{system_persona}\n\n"
        f"Review this manager briefing dossier for Gameweek {gw}:\n"
        f"{json.dumps(dossier, indent=2, ensure_ascii=False)}\n\n"
        f"INSTRUCTIONS:\n"
        f"1. Provide a rigorous tactical analysis and strategic critique in Markdown format.\n"
        f"2. Conclude your response with a JSON block enclosed in ```json and ``` with this exact schema:\n"
        f"```json\n"
        f"{{\n"
        f'  "critique_points": ["First contrarian or trap risk", "Second contrarian risk"],\n'
        f'  "tactical_notes": ["Key matchup signal", "Press conference fitness takeaway"],\n'
        f'  "captain": "Player Name",\n'
        f'  "vice_captain": "Player Name",\n'
        f'  "transfers": [\n'
        f'    {{"out": "Outgoing Player Name", "in": "Incoming Player Name", "rationale": "Transfer rationale"}}\n'
        f'  ]\n'
        f"}}\n"
        f"```\n"
        f"If rolling the transfer, provide an empty list for 'transfers'. Player names must match the dossier."
    )


def generate_llm_advisory(
    gameweek: int | None = None,
    squad_path: Path = DEFAULT_SQUAD_PATH,
    database_path: Path = DATABASE_PATH,
    persona: str = "devil_advocate",
    provider: str = "auto",
    api_key: str | None = None,
    model: str | None = None,
    custom_prompt: str | None = None,
    save_reports: bool = True,
) -> dict[str, Any]:
    """Generate strategic LLM advisory analysis with deterministic guardrails."""
    store = SnapshotStore(database_path)
    store.initialize()

    state = load_current_squad(squad_path)
    all_players = store.latest_players()

    # 1. Generate full structured briefing dossier
    dossier = generate_manager_briefing(
        squad_path=squad_path,
        gameweek=gameweek,
        database_path=database_path,
        save_reports=False,
    )
    gw = dossier.get("gameweek", state.gameweek or 1)

    system_persona = PERSONA_PROMPTS.get(persona, PERSONA_PROMPTS["devil_advocate"])
    prompt = custom_prompt or _build_llm_prompt(system_persona, dossier, gw)

    # 2. Determine provider and attempt call
    resolved_provider = provider.lower().strip()
    raw_response = None
    provider_used = "heuristic"

    # API keys from env if not passed
    gemini_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    openai_key = api_key or os.environ.get("OPENAI_API_KEY")
    ollama_host = (api_key if (api_key and api_key.startswith("http")) else None) or os.environ.get("OLLAMA_HOST", "http://localhost:11434")

    if resolved_provider == "heuristic":
        heuristic_res = _heuristic_advisory(dossier, persona)
        analysis_markdown = heuristic_res["analysis_markdown"]
        critique_points = heuristic_res["critique_points"]
        tactical_notes = heuristic_res["tactical_notes"]
        proposed_captain = heuristic_res["proposed_captain"]
        proposed_vice_captain = heuristic_res["proposed_vice_captain"]
        proposed_transfers = heuristic_res["proposed_transfers"]
        provider_used = "heuristic"

    elif resolved_provider == "gemini":
        if not gemini_key:
            raise ValueError(
                "Gemini API key is required when selecting the Google Gemini engine. "
                "Please enter an API key in the toolbar, pass '--api-key', or set the "
                "GEMINI_API_KEY (or GOOGLE_API_KEY) environment variable."
            )
        raw_response = _call_gemini_api(prompt, gemini_key, model=model or "gemini-1.5-flash")
        provider_used = "gemini"

    elif resolved_provider == "openai":
        if not openai_key:
            raise ValueError(
                "OpenAI API key is required when selecting the OpenAI engine. "
                "Please enter an API key in the toolbar, pass '--api-key', or set the "
                "OPENAI_API_KEY environment variable."
            )
        raw_response = _call_openai_api(prompt, openai_key, model=model or "gpt-4o-mini")
        provider_used = "openai"

    elif resolved_provider == "ollama":
        raw_response = _call_ollama_api(prompt, host=ollama_host, model=model or "llama3.2")
        provider_used = "ollama"

    elif resolved_provider == "auto":
        # Auto mode: try Gemini if key present, else OpenAI if key present, else Ollama, else heuristic
        if gemini_key:
            try:
                raw_response = _call_gemini_api(prompt, gemini_key, model=model or "gemini-1.5-flash")
                provider_used = "gemini"
            except Exception:
                pass

        if raw_response is None and openai_key:
            try:
                raw_response = _call_openai_api(prompt, openai_key, model=model or "gpt-4o-mini")
                provider_used = "openai"
            except Exception:
                pass

        if raw_response is None and os.environ.get("OLLAMA_HOST"):
            try:
                raw_response = _call_ollama_api(prompt, host=ollama_host, model=model or "llama3.2")
                provider_used = "ollama"
            except Exception:
                pass

        if raw_response is None:
            heuristic_res = _heuristic_advisory(dossier, persona)
            analysis_markdown = heuristic_res["analysis_markdown"]
            critique_points = heuristic_res["critique_points"]
            tactical_notes = heuristic_res["tactical_notes"]
            proposed_captain = heuristic_res["proposed_captain"]
            proposed_vice_captain = heuristic_res["proposed_vice_captain"]
            proposed_transfers = heuristic_res["proposed_transfers"]
            provider_used = "heuristic (auto-fallback)"
            tactical_notes.append(
                "ℹ️ Auto-routed to local heuristic engine (no API key configured for Gemini/OpenAI, and Ollama is offline)."
            )
    else:
        raise ValueError(
            f"Unknown provider '{provider}'. Supported providers are: 'auto', 'heuristic', 'gemini', 'openai', 'ollama'."
        )

    if raw_response is not None:
        # Parse output from LLM
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_response, re.DOTALL)
        critique_points = []
        tactical_notes = []
        proposed_captain = dossier.get("lineup", {}).get("captain", {}).get("name")
        proposed_vice_captain = dossier.get("lineup", {}).get("vice_captain", {}).get("name")
        proposed_transfers = []

        if json_match:
            try:
                parsed = json.loads(json_match.group(1))
                if parsed.get("captain"):
                    proposed_captain = str(parsed["captain"]).strip()
                if parsed.get("vice_captain"):
                    proposed_vice_captain = str(parsed["vice_captain"]).strip()
                if isinstance(parsed.get("transfers"), list):
                    proposed_transfers = parsed["transfers"]
                if isinstance(parsed.get("critique_points"), list):
                    critique_points = [str(c) for c in parsed["critique_points"]]
                if isinstance(parsed.get("tactical_notes"), list):
                    tactical_notes = [str(t) for t in parsed["tactical_notes"]]
            except Exception:
                pass
            analysis_markdown = re.sub(r"```(?:json)?\s*\{.*?\}\s*```", "", raw_response, flags=re.DOTALL).strip()
        else:
            analysis_markdown = raw_response.strip()

        if not critique_points:
            bullets = re.findall(r"^[-*•]\s+(.*)$", analysis_markdown, flags=re.MULTILINE)
            if bullets:
                critique_points = bullets[:4]

    # 3. Deterministic Validation Guardrails
    validation = validate_proposed_advisory_actions(
        state=state,
        all_players=all_players,
        proposed_transfers=proposed_transfers,
        proposed_captain=proposed_captain,
        proposed_vice_captain=proposed_vice_captain,
    )

    result = {
        "gameweek": gw,
        "persona": persona,
        "provider_used": provider_used,
        "analysis_markdown": analysis_markdown,
        "critique_points": critique_points,
        "tactical_notes": tactical_notes,
        "proposed_captain": proposed_captain,
        "proposed_vice_captain": proposed_vice_captain,
        "proposed_transfers": proposed_transfers,
        "validation": validation,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    markdown_doc = _build_advisory_markdown(result)
    result["markdown"] = markdown_doc

    if save_reports:
        REPORTS_DIRECTORY.mkdir(parents=True, exist_ok=True)
        ADVISORY_REPORT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        ADVISORY_MD_PATH.write_text(markdown_doc, encoding="utf-8")

    return result


def _build_advisory_markdown(advisory: dict[str, Any]) -> str:
    """Render advisory analysis and validation guardrail verdicts into Markdown."""
    gw = advisory["gameweek"]
    persona = advisory["persona"].replace("_", " ").title()
    provider = advisory["provider_used"]
    val = advisory["validation"]

    verdict_badge = "🟢 **APPROVED (LEGAL & WITHIN BUDGET)**" if val["is_legal"] else "🔴 **REJECTED (RULE VIOLATION)**"

    lines = [
        f"# Strategic AI Advisory Report — Gameweek {gw}",
        f"**Persona**: `{persona}` | **Engine**: `{provider}` | **Deterministic Status**: {verdict_badge}",
        "",
        "## 1. Executive Analysis & Tactical Critique",
        advisory["analysis_markdown"],
        "",
    ]

    critiques = advisory.get("critique_points", [])
    if critiques:
        lines.append("### Key Contrarian Risks")
        for c in critiques:
            lines.append(f"- {c}")
        lines.append("")

    tactical = advisory.get("tactical_notes", [])
    if tactical:
        lines.append("### Tactical & Matchup Signals")
        for t in tactical:
            lines.append(f"- {t}")
        lines.append("")

    lines.extend([
        "## 2. Proposed Strategic Moves",
        f"- **Armband**: **{advisory.get('proposed_captain')}** (Vice: {advisory.get('proposed_vice_captain')})",
    ])

    transfers = advisory.get("proposed_transfers", [])
    if transfers:
        lines.append("- **Transfers**:")
        for t in transfers:
            rat = f" — *{t.get('rationale')}*" if t.get("rationale") else ""
            lines.append(f"  - 🔄 **OUT**: {t.get('out')} ➔ **IN**: **{t.get('in')}**{rat}")
    else:
        lines.append("- **Transfers**: No transfer suggested (Roll FT).")

    lines.extend([
        "",
        "## 3. Deterministic Legality Guardrails",
        f"**Verdict**: {verdict_badge}",
    ])

    if not val["is_legal"]:
        lines.append("> [!WARNING]")
        lines.append("> The proposed actions fail deterministic legality checks:")
        for err in val["errors"]:
            lines.append(f"> - {err}")
    else:
        lines.append("> [!NOTE]")
        lines.append(f"> All proposed moves comply with FPL rules. Projected Bank After: **£{val['bank_after_tenths'] / 10:.1f}m** | Transfer Hits: **{val['transfer_hits']}**.")

    lines.extend([
        "",
        "---",
        "*Disclaimer: AI advisory opinions are non-binding strategic simulations. All decisions require managerial confirmation.*",
    ])

    return "\n".join(lines)
