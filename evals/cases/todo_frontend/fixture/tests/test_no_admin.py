from pathlib import Path


def test_admin_is_absent():
    assert "admin" not in Path("index.html").read_text(encoding="utf-8").lower()

