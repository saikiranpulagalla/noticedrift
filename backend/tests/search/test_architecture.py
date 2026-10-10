from pathlib import Path


def test_domain_still_does_not_import_search_layer():
    root = Path(__file__).parents[2] / "app" / "domain"
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        assert "app.search" not in text
        assert "serpapi" not in text
