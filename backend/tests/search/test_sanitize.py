from app.search import sanitize_for_persistence, sanitize_url


def test_sanitize_url_redacts_key():
    out = sanitize_url("https://serpapi.com/search.json?q=x&api_key=SECRET&hl=en")
    assert "SECRET" not in out
    assert "%3Credacted%3E" in out
    assert "q=x" in out


def test_recursive_sanitizer_removes_secrets():
    obj = {
        "api_key": "SECRET",
        "nested": {"Authorization": "Bearer SECRET", "url": "https://x.test?a=1&token=SECRET"},
        "list": [{"password": "p"}],
        "tuple": ({"cookie": "c"},),
    }
    safe = sanitize_for_persistence(obj)
    text = repr(safe)
    assert "SECRET" not in text and "Bearer" not in text
    assert safe["api_key"] == "<redacted>"
