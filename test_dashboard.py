"""Check the dashboard script after Python renders the actual HTTP response."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from config import BridgeSettings
from server import create_app


def test_served_dashboard_javascript_parses(tmp_path: Path) -> None:
    node = shutil.which("node")
    assert node is not None, "Node.js is required to validate the dashboard JavaScript"
    settings = BridgeSettings(auto_export_extension=False, generated_dir=str(tmp_path))
    with TestClient(create_app(settings)) as client:
        response = client.get("/")
    assert response.status_code == 200
    scripts = re.findall(r"<script\b[^>]*>(.*?)</script>", response.text, re.S | re.I)
    assert scripts, "The dashboard must contain its interactive script"
    for script in scripts:
        result = subprocess.run(
            [node, "--check", "--input-type=commonjs"],
            input=script, capture_output=True, text=True, timeout=10, check=False,
        )
        assert result.returncode == 0, result.stderr
