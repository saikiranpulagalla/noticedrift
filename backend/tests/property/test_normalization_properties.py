import random
from app.domain import normalize_reference, canonicalize_url


def test_reference_normalization_idempotence_over_generated_whitespace():
    rnd = random.Random(12345)
    base = ["ADV", "/", "01", "-", "2026"]
    for _ in range(500):
        raw = "".join((" " * rnd.randint(0, 3)) + part + (" " * rnd.randint(0, 3)) for part in base)
        once = normalize_reference(raw)
        assert normalize_reference(once) == once


def test_url_canonicalization_idempotence_over_tracking_variants():
    rnd = random.Random(6789)
    for i in range(300):
        url = f"https://EXAMPLE.com//notice?id={i}&utm_source=s{rnd.randint(1,99)}&foo=x#frag"
        once = canonicalize_url(url)
        assert canonicalize_url(once) == once
        assert "utm_source" not in once
        assert f"id={i}" in once
