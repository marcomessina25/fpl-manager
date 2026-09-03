# Squad Import Utility

`fpl-manager` provides an automated utility script to populate your private `config/current_squad.json` file from a plain text list of player names (`players.txt`), avoiding manual searches and copy-pasting.

## Prerequisites

Before running the import script, make sure you have fetched the latest official FPL data:

```powershell
fpl update
```

## Creating `players.txt`

Create a file named `players.txt` in the root of the project. List the 15 players in your squad, one per line (using player display names or search queries).

Example `players.txt`:

```text
Raya
Gabriel
Saliba
Gvardiol
Alexander-Arnold
Saka
Palmer
Eze
Rogers
Gordon
Haaland
Isak
Wood
Fabianski
Pickford
```

> [!NOTE]
> `players.txt` contains your personal squad draft and is ignored by Git. Do not commit it.

## Running the Utility Script

You can execute the import using either the utility script directly or the `fpl import-squad` CLI command:

### Option 1: Via Utility Script

```powershell
python scripts/import_squad.py
```

### Option 2: Via FPL CLI

```powershell
fpl import-squad
```

### Optional Arguments

Both tools accept optional path arguments:

- `--players <path>`: Path to the input player list (default: `players.txt`)
- `--squad <path>`: Path to the target squad JSON file (default: `config/current_squad.json`)

Example with custom paths:

```powershell
python scripts/import_squad.py --players my_squad.txt --squad config/current_squad.json
```

## Execution Output & Rules

For each non-empty row in `players.txt`, the script queries the local FPL snapshot:

1. **Successful Match**: When the search query uniquely identifies a single player (or uniquely matches `web_name` exactly), the script outputs:
   ```text
   importing id <id> player <name> team <team> price <price>
   ```
   Example:
   ```text
   importing id 328 player Salah team LIV price 125
   ```

2. **Failed Match**: If no matching player is found, or if multiple ambiguous players match the search query, the script outputs:
   ```text
   failed importing player <query>
   ```
   Example:
   ```text
   failed importing player NonExistentPlayer
   ```

## Updated File Structure

Upon completion, `config/current_squad.json` is automatically generated or updated with the successfully matched player IDs and purchase prices (in tenths of a million):

```json
{
  "season": "2026/27",
  "player_ids": [
    10, 20, 30, ...
  ],
  "purchase_prices_tenths": {
    "10": 55,
    "20": 125,
    "30": 80
  },
  "bank_tenths": 0,
  "free_transfers": 1,
  "chips_remaining": ["wildcard_1", "wildcard_2", "free_hit", "bench_boost", "triple_captain"]
}
```

## Validating Your Squad

After running the import script, verify your squad state and rule compliance using player names (`-n`) or IDs:

```powershell
fpl validate-transfers -n --transfer "Raya:Pickford"
```

Or using integer IDs:

```powershell
fpl validate-transfers --transfer 10:30
```

