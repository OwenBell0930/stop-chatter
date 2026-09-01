from pathlib import Path


def test_analytics_is_absent():
    assert "analytics" not in Path("validator.py").read_text(encoding="utf-8").lower()

