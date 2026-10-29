"""Run the dependency-free JavaScript controller regressions under pytest."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_gui_context_runtime():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for GUI controller runtime regressions")
    test_file = Path(__file__).with_suffix(".js")
    result = subprocess.run(
        [node, "--test", str(test_file)],
        cwd=test_file.parent.parent,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
