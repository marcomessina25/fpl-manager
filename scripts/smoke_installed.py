"""Exercise an installed wheel outside the source checkout, without live data."""

import importlib.resources
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import fpl_manager
from fpl_manager.application import CommandBus, HistoricalContext, read_state_text, write_state_text


def main() -> None:
    checkout = Path(__file__).resolve().parents[1]
    assert not Path(fpl_manager.__file__).resolve().is_relative_to(checkout / "src"), "Source checkout shadowed the wheel."
    assets = importlib.resources.files("fpl_manager.gui").joinpath("static")
    for name in ("index.html", "app.js", "app.css"):
        assert assets.joinpath(name).is_file(), f"Missing packaged GUI resource: {name}"
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        journal = root / "simulations" / "command_journal.sqlite3"
        state = root / "state.json"
        context = HistoricalContext("wheel-smoke", "2023-24", 1)
        bus = CommandBus(journal, historical_database_path=journal)
        receipt = bus.execute(
            context, "smoke", {}, lambda: write_state_text(state, '{"installed": true}'),
            expected_revision=0, command_id="installed-smoke",
        )
        assert receipt.revision_after == 1
        assert read_state_text(state) == '{"installed": true}'
        assert bus.revision(context) == 1
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        subprocess.run(
            [sys.executable, "-m", "fpl_manager.cli", "--help"],
            cwd=root, env=environment, check=True, stdout=subprocess.DEVNULL,
        )
    print(f"Installed wheel smoke passed ({fpl_manager.__version__}).")


if __name__ == "__main__":
    main()
