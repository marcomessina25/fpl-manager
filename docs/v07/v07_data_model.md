# V0.7 Historical Data Model & Point-in-Time Contract

## 1. Overview & Core Invariants

The V0.7 historical backtesting subsystem establishes a reproducible, deterministic experimental foundation for Fantasy Premier League (FPL) projections and decision support.

The fundamental invariant of this architecture is **strict point-in-time separation**:
```text
┌─────────────────────────────────────────────────────────┐
│               BEFORE GAMEWEEK N DEADLINE                │
│  - Available player status, price, ownership            │
│  - Past fixtures & cumulative statistics (GW 1..N-1)    │
│  - Upcoming fixture schedule & FDR ratings              │
│  ===> MODEL INPUT (Snapshot at GW N Deadline)           │
└────────────────────────────┬────────────────────────────┘
                             │  Decision Point
                             ▼
┌─────────────────────────────────────────────────────────┐
│                AFTER GAMEWEEK N COMPLETION              │
│  - GW N match results, final scorelines                 │
│  - GW N player minutes, goals, assists, bonus, points   │
│  - Future GW news, injuries, transfers                  │
│  ===> GROUND TRUTH (Evaluation Only)                    │
└─────────────────────────────────────────────────────────┘
```

**Zero Future-Data Leakage Rule:**
Under no circumstance may any calculation determining expected points ($xP$), expected minutes ($xM$), transfer recommendations, or lineup selection for Gameweek $N$ access:
1. GW $N$ (or later) minutes, points, goals, assists, bonus, or autosub results.
2. Price or ownership changes occurring after the GW $N$ deadline.
3. Post-deadline injury reports, suspensions, or lineup press conferences.
4. Postponements or fixture rescheduling announced after the GW $N$ deadline.

---

## 2. Field Inventory & Temporal Classification

The following table documents all FPL fields consumed or evaluated by `fpl-manager`, categorized by their point-in-time availability:

| Field Name | Description | Pre-Decision Input (GW $N$) | Ground Truth Outcome (GW $N$) | Leakage Risk |
| :--- | :--- | :---: | :---: | :---: |
| `element_id` / `player_id` | Unique FPL player identifier | Yes (Historical ID) | Yes | Low |
| `web_name` | Display name | Yes | Yes | Low |
| `position` | GKP (1), DEF (2), MID (3), FWD (4) | Yes | Yes | Low |
| `team_id` | Current team ID at GW $N$ | Yes | Yes | Medium (Transfers) |
| `now_cost` / `price_tenths` | Price at deadline $N$ | Yes | Post-GW price is forbidden | High |
| `selected_by_percent` | Global ownership % at deadline | Yes | Post-GW ownership is forbidden | High |
| `status` | Availability flag ('a', 'd', 'i', 's', 'u') | Yes (as of deadline) | Forbidden | Very High |
| `chance_of_playing_next_round` | Official FPL probability % | Yes (as of deadline) | Forbidden | Very High |
| `cumulative_minutes` | Total minutes played up to GW $N-1$ | Yes (GW 1..N-1) | GW $N$ minutes forbidden | Critical |
| `cumulative_starts` | Total starts up to GW $N-1$ | Yes (GW 1..N-1) | GW $N$ starts forbidden | Critical |
| `cumulative_total_points` | Total points scored up to GW $N-1$| Yes (GW 1..N-1) | GW $N$ points forbidden | Critical |
| `cumulative_xG` / `cumulative_xA` | Cumulative expected stats to $N-1$ | Yes (GW 1..N-1) | GW $N$ stats forbidden | Critical |
| `form` / `points_per_game` | Form computed over GW $1..N-1$ | Yes | Post-deadline form forbidden | High |
| `fixtures` | Scheduled matches for GW $N$ | Yes (as known at deadline)| Match outcomes forbidden | High |
| `fdr` (team_h/a_difficulty) | Opponent fixture difficulty rating | Yes | Forbidden to alter retroactively | Medium |
| `gw_minutes` | Actual minutes played in GW $N$ | **NO** | **YES (Ground Truth)** | Critical |
| `gw_points` | Actual points scored in GW $N$ | **NO** | **YES (Ground Truth)** | Critical |
| `gw_goals`, `gw_assists`, etc. | Matchday statistics in GW $N$ | **NO** | **YES (Ground Truth)** | Critical |
| `gw_bonus`, `gw_bps` | Matchday bonus in GW $N$ | **NO** | **YES (Ground Truth)** | Critical |

---

## 3. Dataset Architecture & Directory Layout

Historical datasets are stored in normalized formats under `data/historical/<season>/`:

```text
data/historical/
    2023-24/
        season_manifest.json          # Season metadata, deadline timestamps, team mappings
        teams.json                    # 20 Premier League teams with IDs, short names, strengths
        fixtures.json                 # Complete fixture list across 38 gameweeks
        players_raw.json              # Canonical player catalog and attributes
        gws/
            gw1.csv                   # Raw player match outcomes and point-in-time metrics
            gw2.csv
            ...
            gw38.csv
        snapshots/                    # Precomputed, immutable point-in-time SQLite/JSON snapshots
            gw01_snapshot.json
            gw02_snapshot.json
            ...
            gw38_snapshot.json
```

---

## 4. Point-in-Time Snapshot Specification

A snapshot for Gameweek $N$ encapsulates the exact state of the world available **prior to the official Gameweek $N$ deadline**.

```python
@dataclass(frozen=True, slots=True)
class HistoricalPlayerState:
    player_id: int
    web_name: str
    position: Position
    team_id: int
    price_tenths: int
    status: str
    chance_of_playing_next_round: int | None
    total_points: int            # Cumulative GW 1..N-1
    minutes: int                 # Cumulative GW 1..N-1
    starts: int                  # Cumulative GW 1..N-1
    expected_goals: float        # Cumulative GW 1..N-1
    expected_assists: float      # Cumulative GW 1..N-1
    expected_goals_per_90: float
    expected_assists_per_90: float
    expected_goals_conceded_per_90: float
    clean_sheets_per_90: float
    bps: int                     # Cumulative GW 1..N-1
    ict_index: float             # Cumulative GW 1..N-1
    form: float
    points_per_game: float
    selected_by_percent: float
    news: str

@dataclass(frozen=True, slots=True)
class HistoricalGameweekSnapshot:
    season: str
    gameweek: int
    deadline_time: str
    players: tuple[HistoricalPlayerState, ...]
    teams: tuple[dict[str, Any], ...]
    upcoming_fixtures: tuple[dict[str, Any], ...]
    finished_gameweeks: int      # N - 1
```

---

## 5. Ground Truth Outcome Specification

The evaluation layer records ground truth after Gameweek $N$ has concluded:

```python
@dataclass(frozen=True, slots=True)
class GameweekOutcome:
    season: str
    gameweek: int
    player_id: int
    minutes: int
    total_points: int
    goals_scored: int
    assists: int
    clean_sheets: int
    goals_conceded: int
    bonus: int
    bps: int
    was_home: bool
    opponent_team_id: int
```

Ground truth data is strictly isolated from model projection methods and is only queried by the evaluation and backtesting engine after decision generation has completed.
