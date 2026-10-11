"""Current-state certainty: discovery hints never become governing evidence."""
from datetime import date
import pytest
from app.search.models import OrganicResult
from test_v07_workflow import workflow, request, ORIGINAL, UPDATE, ORIG_HTML, UPDATE_HTML, CANCEL_HTML


async def check_with_hint(hint, *, update=UPDATE_HTML, supplied=date(2026, 10, 1), reverse=False, repeat=1):
    urls = [ORIGINAL] + ([UPDATE] if update is not None else [])
    runner, _, transport = workflow(urls, {ORIGINAL: ORIG_HTML, UPDATE: update})
    upstream = runner.executor.client
    async def search(planned, **kwargs):
        response = await upstream.search(planned, **kwargs)
        results = [*response.results, *([hint] if hint else [])] * repeat
        return response.model_copy(update={'results': tuple(reversed(results)) if reverse else tuple(results)})
    runner.executor.client = type('HintSearch', (), {'search': staticmethod(search)})()
    outcome = await runner.check(request(deadline=supplied))
    return outcome, transport


@pytest.mark.asyncio
@pytest.mark.parametrize('update', [None, UPDATE_HTML, CANCEL_HTML])
async def test_material_later_lead_blocks_current_state(update):
    hint = OrganicResult(link='https://other.example/report', title='A/2026 cancellation',
                         snippet='Possible later cancellation of Synthetic Issuer notice A/2026')
    out, transport = await check_with_hint(hint, update=update)
    print('MATERIAL_LEAD', out.analysis.verdict.value, out.analysis.coverage.value, len(out.sources))
    assert out.analysis.verdict.value == 'UNRESOLVED'
    assert out.analysis.coverage.value == 'INSUFFICIENT'
    assert 'UNVERIFIED_RELATED_SEARCH_CANDIDATE' in out.warnings
    assert not out.analysis.field_resolutions
    assert hint.link not in transport.calls
    assert out.provider_calls == 6
    assert len(out.search_entries) == 6


@pytest.mark.asyncio
@pytest.mark.parametrize('hint', [None,
    OrganicResult(link='https://other.example/article', title='University cafeteria news'),
    OrganicResult(link='https://other.example/cancellation', title='General recruitment news'),
    OrganicResult(link='https://other.example/report', title='B/2026 cancellation'),
    OrganicResult(link='https://other.example/report', title='XA/2026 cancellation'),
    OrganicResult(link='https://other.example/report', title='A/20260 cancellation'),
    OrganicResult(link='https://other.example/report', title='A/2026 original notice'),
])
async def test_unrelated_or_low_specificity_noise_does_not_block_extension(hint):
    out, transport = await check_with_hint(hint)
    assert out.analysis.verdict.value == 'SUPERSEDED'
    assert out.analysis.coverage.value == 'ADEQUATE'
    assert out.analysis.field_resolutions[0].value == date(2026, 10, 26)
    assert len(out.sources) == len(transport.calls) == 2
    assert out.provider_calls == 6


@pytest.mark.asyncio
@pytest.mark.parametrize('reverse, repeat', [(False, 1), (True, 1), (False, 3), (True, 3)])
async def test_relevant_hint_order_and_duplication_cannot_create_assurance(reverse, repeat):
    hint = OrganicResult(link='https://other.example/report', title='A / 2026 cancellation')
    out, transport = await check_with_hint(hint, reverse=reverse, repeat=repeat)
    assert out.analysis.verdict.value == 'UNRESOLVED'
    assert out.analysis.coverage.value == 'INSUFFICIENT'
    assert len(transport.calls) == len(set(transport.calls)) == 2
    assert len(out.sources) == 2 and out.provider_calls == 6


@pytest.mark.asyncio
@pytest.mark.parametrize('update, supplied, verdict', [
    (None, date(2026, 10, 1), 'SUPPORTED_BY_EVIDENCE'),
    (UPDATE_HTML, date(2026, 10, 1), 'SUPERSEDED'),
    (UPDATE_HTML, date(2026, 10, 26), 'SUPPORTED_BY_EVIDENCE'),
    (CANCEL_HTML, date(2026, 10, 1), 'CANCELLED'),
])
async def test_complete_current_state_positive_controls(update, supplied, verdict):
    out, transport = await check_with_hint(None, update=update, supplied=supplied, repeat=3)
    assert out.analysis.verdict.value == verdict
    assert out.analysis.coverage.value == 'ADEQUATE'
    assert len(out.sources) == len(set(transport.calls)) == (1 if update is None else 2)
    assert all(source.authority_attested and source.source_sha256 and source.snapshot_id for source in out.sources)


@pytest.mark.asyncio
@pytest.mark.parametrize('snippet', [
    'Issuer: Other Institution; Reference: A/2026; cancellation',
    'Issuer: Synthetic Issuer; Reference: B/2026; cancellation',
])
async def test_explicitly_different_family_leads_are_not_material(snippet):
    hint = OrganicResult(link='https://other.example/report', title='Recruitment update', snippet=snippet)
    out, transport = await check_with_hint(hint)
    assert out.analysis.verdict.value == 'SUPERSEDED'
    assert out.analysis.coverage.value == 'ADEQUATE'
    assert hint.link not in transport.calls


@pytest.mark.asyncio
@pytest.mark.parametrize('snippet', [
    'Reference: A/2026. Cancellation effective from 26 October 2026.',
    'Reference: A/2026. Cancellation for Zone 4 applicants only.',
    'Reference: A/2026. Rumor of cancellation; unverified report.',
    'Reference: A/2026. Official source: ' + UPDATE + '\nThe deadline is extended from 01 October 2026 to 26 October 2026.',
])
async def test_untrusted_dates_scope_and_matching_quotes_do_not_prove_disposition(snippet):
    hint = OrganicResult(link='https://other.example/report', title='A/2026 update', snippet=snippet)
    out, transport = await check_with_hint(hint)
    assert out.analysis.verdict.value == 'UNRESOLVED'
    assert out.analysis.coverage.value == 'INSUFFICIENT'
    assert 'UNVERIFIED_RELATED_SEARCH_CANDIDATE' in out.warnings
    assert hint.link not in transport.calls
    assert len(out.sources) == 2


@pytest.mark.asyncio
async def test_matching_issuer_label_remains_a_material_lead():
    hint = OrganicResult(link='https://other.example/report', title='A/2026 cancellation',
                         snippet='Issuer: Synthetic Issuer; details unverified')
    out, transport = await check_with_hint(hint)
    assert out.analysis.verdict.value == 'UNRESOLVED'
    assert out.analysis.coverage.value == 'INSUFFICIENT'
    assert hint.link not in transport.calls


@pytest.mark.asyncio
async def test_duplicate_official_candidate_is_accounted_by_exact_captured_evidence():
    # An equivalent admitted URL has actual source-byte/quotation provenance;
    # an off-host page merely repeating its text does not have that proof.
    hint = OrganicResult(link=UPDATE, title='A/2026 extension')
    out, transport = await check_with_hint(hint, repeat=3)
    assert out.analysis.verdict.value == 'SUPERSEDED'
    assert out.analysis.coverage.value == 'ADEQUATE'
    assert len(out.sources) == len(transport.calls) == 2
    assert all(source.source_sha256 and source.text_sha256 and source.relation_quote for source in out.sources)
