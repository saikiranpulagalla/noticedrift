from pathlib import Path

FORBIDDEN = ("fastapi", "httpx", "serpapi", "google.generativeai", "langchain", "langgraph")


def test_domain_layer_has_no_external_integration_imports():
    root = Path(__file__).parents[2] / "app" / "domain"
    offenders = []
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        for term in FORBIDDEN:
            if f"import {term}" in text or f"from {term}" in text:
                offenders.append((path.name, term))
    assert offenders == []
