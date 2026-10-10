from .models import NoticeDocument, NoticeFamily, FamilyBinding
from .enums import BindingStrength
from .normalization import normalize_reference


def bind_document(document: NoticeDocument, family: NoticeFamily) -> FamilyBinding:
    doc_issuer = document.identity.issuer_id
    issuer_ok = bool(doc_issuer and doc_issuer == family.issuer_id)
    doc_refs = {x for r in document.identity.reference_numbers if (x := normalize_reference(r))}
    fam_refs = {x for r in family.reference_aliases if (x := normalize_reference(r))}
    ref_match = bool(doc_refs & fam_refs)

    # Identifiers are reused across years; a conflicting explicit year vetoes strong identity.
    if (document.identity.notice_year is not None and family.notice_year is not None
            and document.identity.notice_year != family.notice_year):
        return FamilyBinding(document_id=document.document_id, family_id=family.family_id,
                             strength=BindingStrength.REJECTED, reasons=("NOTICE_YEAR_CONFLICT",))
    if ref_match and issuer_ok:
        return FamilyBinding(document_id=document.document_id, family_id=family.family_id,
                             strength=BindingStrength.STRONG,
                             reasons=("EXACT_REFERENCE", "ISSUER_MATCH"))
    if ref_match and doc_issuer and not issuer_ok:
        return FamilyBinding(document_id=document.document_id, family_id=family.family_id,
                             strength=BindingStrength.REJECTED,
                             reasons=("REFERENCE_MATCH_BUT_ISSUER_CONFLICT",))

    # Conservative fallback: title-only evidence may be displayed, never govern.
    if issuer_ok and document.identity.notice_year in (None, family.notice_year):
        return FamilyBinding(document_id=document.document_id, family_id=family.family_id,
                             strength=BindingStrength.POSSIBLE,
                             reasons=("ISSUER_MATCH_ONLY",))

    return FamilyBinding(document_id=document.document_id, family_id=family.family_id,
                         strength=BindingStrength.REJECTED,
                         reasons=("INSUFFICIENT_IDENTITY",))
