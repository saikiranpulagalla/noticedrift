from app.domain import *

def test_exact_reference_and_issuer_is_strong(family, helpers):
    d = helpers["make_doc"]("d", DocumentRole.ORIGINAL_NOTICE)
    result = bind_document(d, family)
    assert result.strength == BindingStrength.STRONG

def test_same_reference_wrong_issuer_is_rejected(family, helpers):
    d = helpers["make_doc"]("d", DocumentRole.ORIGINAL_NOTICE, issuer="issuer-2")
    result = bind_document(d, family)
    assert result.strength == BindingStrength.REJECTED

def test_issuer_only_never_becomes_strong(family, helpers):
    d = helpers["make_doc"]("d", DocumentRole.ORIGINAL_NOTICE, refs=("OTHER/99/2026",))
    result = bind_document(d, family)
    assert result.strength == BindingStrength.POSSIBLE
