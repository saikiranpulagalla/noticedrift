from app.domain import normalize_reference, canonicalize_url

def test_reference_normalization_is_idempotent():
    value = "  Adv – 01 / 2026  "
    once = normalize_reference(value)
    assert once == "ADV-01/2026"
    assert normalize_reference(once) == once

def test_url_removes_tracking_but_preserves_semantic_query():
    url = "HTTPS://Example.COM//notice?id=42&utm_source=x&foo=bar#frag"
    assert canonicalize_url(url) == "https://example.com//notice?id=42&foo=bar"
