from pathlib import Path


def test_dongpo_pork_is_absent():
    text = Path("recipe.md").read_text(encoding="utf-8")
    assert "东坡肉" not in text
    assert "东坡肘子" not in text

