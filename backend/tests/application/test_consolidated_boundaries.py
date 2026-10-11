"""Bounded offline cross-checks: fictional hosts, bytes and credential canaries only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
from threading import Barrier

import pytest

from app.search.client import parse_provider_payload
from app.search.models import PlannedQuery, QueryPurpose, QueryTier
from app.sources.fetch import safe_target
from app.sources.models import SourceSnapshot, SourceFailure
from app.sources.parse import parse_snapshot
from app.sources.store import SnapshotStore
from test_v07_workflow import ORIGINAL, UPDATE, ORIG_HTML, UPDATE_HTML, workflow, request
from test_v07_workflow import CANCEL_HTML


def snapshot(body=UPDATE_HTML, url=UPDATE):
    return SourceSnapshot(source_url=url, final_url=url, body=body,
                          captured_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
                          content_type='text/html', body_sha256=sha256(body).hexdigest())


def payload_response(parameters=None, **extra):
    planned = PlannedQuery(query='"A/2026"', purpose=QueryPurpose.IDENTITY,
                           tier=QueryTier.CORE, priority=1)
    payload = {'search_metadata': {'status': 'Success'}, 'organic_results': []}
    if parameters is not None:
        payload['search_parameters'] = parameters
    payload.update(extra)
    return parse_provider_payload(payload, planned, captured=datetime.now(timezone.utc),
        request_parameters=(('engine', 'google'), ('gl', 'in'), ('hl', 'en'), ('no_cache', 'true')))


@pytest.mark.asyncio
async def test_eleven_finding_crosscheck(tmp_path):
    """Policy observations plus secure post-repair controls."""
    observations = {}
    relation = b'The deadline is extended from 01 October 2026 to 26 October 2026.'
    cases = {
        'ND-ZIP-001': UPDATE_HTML.replace(relation, b'This notice is cancelled effective from 26 October 2026.'),
        'ND-ZIP-002': UPDATE_HTML.replace(relation, b'<dialog>' + relation + b'</dialog>'),
        'ND-ZIP-003': b'<link rel="stylesheet" href="/notice.css">' + UPDATE_HTML,
        'ND-ZIP-004': UPDATE_HTML.replace(b'</main>', b'<p>Issued under delegated powers.</p><p>Applicable exclusively within Zone 4.</p></main>'),
    }
    for finding, body in cases.items():
        w, _, _ = workflow([ORIGINAL, UPDATE], {ORIGINAL: ORIG_HTML, UPDATE: body})
        result = await w.check(request())
        observations[finding] = (parse_snapshot(snapshot(body)).status,
            result.analysis.verdict.value, result.analysis.coverage.value, len(result.sources))
    observations['ND-ZIP-005'] = payload_response().status.value
    extras = [f'https://issuer.example/page/{i}' for i in range(11)]
    w, _, transport = workflow([ORIGINAL, UPDATE, *extras], {ORIGINAL: ORIG_HTML, UPDATE: UPDATE_HTML,
        **{url: b'<main>General institutional information without a notice reference.</main>' for url in extras}})
    result = await w.check(request())
    result = await w.check(request(url=ORIGINAL))
    observations['ND-ANGLE2-001'] = (result.analysis.verdict.value, result.analysis.coverage.value, len(transport.calls))
    w, _, _ = workflow([ORIGINAL, UPDATE, 'https://other.example/a-cancellation'],
        {ORIGINAL: ORIG_HTML, UPDATE: UPDATE_HTML})
    result = await w.check(request())
    observations['ND-ANGLE2-002'] = (result.analysis.verdict.value, result.analysis.coverage.value)
    stores = [SnapshotStore(tmp_path, max_snapshots=1) for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(store.put, snapshot(body)) for store, body in
                   zip(stores, (UPDATE_HTML, ORIG_HTML))]
        outcomes = []
        for future in futures:
            try:
                future.result(timeout=10)
                outcomes.append('PUBLISHED')
            except Exception as exc:
                outcomes.append(type(exc).__name__)
    observations['ND-ANGLE2-003'] = (outcomes, len(list(tmp_path.glob('*.json'))))
    assert len(list(tmp_path.glob('*.json'))) == 1
    observations['ND-ANGLE3-001'] = payload_response(serpapi_pagination={'next': 'https://serpapi.com/search.json?start=10'}).status.value
    credential_results = {}
    for key in ('key', 'auth', 'credential', 'session', 'AWSAccessKeyId'):
        url = UPDATE + '?' + key + '=SYNTHETIC_CANARY'
        try:
            safe_target(url)
            credential_results[key] = 'ACCEPTED'
        except SourceFailure:
            credential_results[key] = 'REJECTED'
    observations['ND-ANGLE3-002'] = credential_results
    observations['ND-ANGLE3-003'] = [payload_response({'q': '"A/2026"', **echo}).status.value
        for echo in ({'engine': 'bing'}, {'gl': 'us'}, {'no_cache': False})]
    print('CROSSCHECK_MATRIX', observations)
    assert len(observations) == 11


@pytest.mark.asyncio
async def test_unqualified_visible_extension_positive_control():
    w, _, transport = workflow([ORIGINAL, UPDATE], {ORIGINAL: ORIG_HTML, UPDATE: UPDATE_HTML})
    result = await w.check(request())
    assert result.analysis.verdict.value == 'SUPERSEDED'
    assert result.analysis.coverage.value == 'ADEQUATE'
    assert len(result.sources) == len(transport.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('declaration', [
    'This notice is cancelled effective from 26 October 2026.',
    'This notice is cancelled subject to board approval.',
    'This notice is cancelled for Zone 4 vacancies.',
    'This notice is cancelled.\nPending board approval.',
])
async def test_qualified_cancellation_cannot_govern(declaration):
    body = UPDATE_HTML.replace(b'The deadline is extended from 01 October 2026 to 26 October 2026.', declaration.encode())
    w, _, _ = workflow([ORIGINAL, UPDATE], {ORIGINAL: ORIG_HTML, UPDATE: body})
    out = await w.check(request())
    assert out.analysis.verdict.value == 'UNRESOLVED'
    assert out.analysis.coverage.value == 'INSUFFICIENT'
    assert len(out.sources) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('wrapper', ['<dialog>{}</dialog>', '<details><summary>More</summary>{}</details>',
    '<dialog><details open>{}</details></dialog>'])
async def test_closed_amendment_cannot_govern(wrapper):
    relation = b'The deadline is extended from 01 October 2026 to 26 October 2026.'
    body = UPDATE_HTML.replace(relation, wrapper.format(relation.decode()).encode())
    w, _, _ = workflow([ORIGINAL, UPDATE], {ORIGINAL: ORIG_HTML, UPDATE: body})
    out = await w.check(request())
    assert out.analysis.verdict.value == 'UNRESOLVED'
    assert out.analysis.coverage.value == 'INSUFFICIENT'
    assert len(out.sources) == 1


@pytest.mark.parametrize('wrapper', ['<dialog open>{}</dialog>', '<details open>{}</details>',
    '<details><summary>{}</summary>Hidden unrelated text</details>'])
def test_open_controls_and_first_summary_remain_visible(wrapper):
    body = wrapper.format(UPDATE_HTML.decode()).encode()
    assert parse_snapshot(snapshot(body)).status == 'PARSED'


@pytest.mark.parametrize('style', ['<link rel="stylesheet" href="/notice.css">',
    '<style>@import url("notice.css");</style>'])
@pytest.mark.asyncio
async def test_unfetched_styles_never_certify_perceptibility(style):
    body = style.encode() + UPDATE_HTML
    w, _, transport = workflow([ORIGINAL, UPDATE], {ORIGINAL: ORIG_HTML, UPDATE: body})
    out = await w.check(request())
    assert out.analysis.verdict.value == 'UNRESOLVED'
    assert out.analysis.coverage.value == 'INSUFFICIENT'
    assert transport.calls == [ORIGINAL, UPDATE]


@pytest.mark.parametrize('style', ['<link rel="icon" href="/icon.ico">',
    '<link rel="stylesheet" disabled href="/notice.css">',
    '<style>/* @import url("unused.css"); */ .notice {color:black}</style>',
    '<style>.notice:before {content:"; @import fake"}</style>'])
def test_nonapplicable_style_controls_remain_supported(style):
    assert parse_snapshot(snapshot(style.encode() + UPDATE_HTML)).status == 'PARSED'


@pytest.mark.asyncio
@pytest.mark.parametrize('placement', ['before', 'after'])
async def test_distant_applicability_is_not_a_whole_notice_amendment(placement):
    scope = b'<p>Applicable exclusively within Zone 4.</p><p>Issued under delegated powers.</p>'
    body = UPDATE_HTML.replace(b'<main>', b'<main>' + scope) if placement == 'before' else UPDATE_HTML.replace(b'</main>', scope + b'</main>')
    w, _, _ = workflow([ORIGINAL, UPDATE], {ORIGINAL: ORIG_HTML, UPDATE: body})
    out = await w.check(request())
    assert out.analysis.verdict.value == 'UNRESOLVED'
    assert out.analysis.coverage.value == 'INSUFFICIENT'


@pytest.mark.parametrize('echo', [{'engine': 'bing'}, {'gl': 'us'}, {'hl': 'fr'}, {'no_cache': False}, {'no_cache': 0}])
def test_explicit_execution_parameter_conflicts_rejected(echo):
    response = payload_response({'q': '"A/2026"', **echo})
    assert response.status.value == 'ERROR'
    assert response.error_code == 'EXECUTION_PARAMETERS_MISMATCH'
    assert not response.results


@pytest.mark.parametrize('echo', [None, {'q': '"A/2026"', 'engine': 'google', 'gl': 'in', 'hl': 'en', 'no_cache': True},
    {'engine': 'google', 'no_cache': 'true'}])
def test_valid_and_optional_parameter_echoes_remain_supported(echo):
    assert payload_response(echo).status.value == 'OK'


@pytest.mark.asyncio
@pytest.mark.parametrize('qualifier', [
    '<footer>Applicable exclusively within Zone 4.</footer>',
    '<footer>Applicability: Zone 4 vacancies.</footer>',
    '<p>This extension is subject to board approval.</p>',
    '<p>Effective from 26 October 2026.</p>',
])
async def test_distant_document_qualifiers_cannot_disappear(qualifier):
    body = UPDATE_HTML.replace(b'</main>',
        b'<p>Issued under delegated powers.</p><p>Administrative reference.</p>' + qualifier.encode() + b'</main>')
    w, _, _ = workflow([ORIGINAL, UPDATE], {ORIGINAL: ORIG_HTML, UPDATE: body})
    out = await w.check(request())
    assert out.analysis.verdict.value == 'UNRESOLVED'
    assert out.analysis.coverage.value == 'INSUFFICIENT'


@pytest.mark.asyncio
@pytest.mark.parametrize('noise', ['<footer>Institution copyright 2026.</footer>',
    '<p>Historical scope: Zone 4 in 2025.</p>', '<nav>Applicable exclusively within Zone 4.</nav>',
    '<blockquote>This extension is subject to approval.</blockquote>'])
async def test_unrelated_and_quoted_scope_controls_remain_supported(noise):
    body = UPDATE_HTML.replace(b'</main>', noise.encode() + b'</main>')
    w, _, _ = workflow([ORIGINAL, UPDATE], {ORIGINAL: ORIG_HTML, UPDATE: body})
    out = await w.check(request())
    assert out.analysis.verdict.value == 'SUPERSEDED'
    assert out.analysis.coverage.value == 'ADEQUATE'


@pytest.mark.asyncio
async def test_overflow_ordering_policy_observation():
    """Unexamined official candidates never yield an unqualified decision."""
    urls = [f'https://issuer.example/page/{i}' for i in range(11)]
    cancellation_url = urls[-1]
    bodies = {ORIGINAL: ORIG_HTML, UPDATE: UPDATE_HTML,
        **{url: b'<main>Unrelated institutional information without a notice reference.</main>' for url in urls}}
    bodies[cancellation_url] = CANCEL_HTML.replace(b'2026-09-17', b'2026-09-19')
    outcomes = []
    for order in (urls, [cancellation_url, *urls[:-1]]):
        w, _, transport = workflow([ORIGINAL, UPDATE, *order], bodies)
        out = await w.check(request(url=ORIGINAL))
        outcomes.append((out.analysis.verdict.value, out.analysis.coverage.value, len(out.sources)))
        assert len(transport.calls) <= 12
        assert out.provider_calls <= 8
        assert out.analysis.verdict.value == 'UNRESOLVED'
        assert out.analysis.coverage.value == 'INSUFFICIENT'
    print('UNRESOLVED_OVERFLOW_POLICY', outcomes)


@pytest.mark.asyncio
@pytest.mark.parametrize('echo', [{'engine': 'bing'}, {'gl': 'us'}, {'no_cache': False}, {}])
async def test_mocked_provider_metadata_through_complete_workflow(echo):
    import httpx
    from app.search.client import SerpApiClient

    def provider_response(req):
        assert req.url.params['engine'] == 'google'
        assert req.url.params['no_cache'] == 'true'
        return httpx.Response(200, json={'search_metadata': {'status': 'Success'},
            'search_parameters': {'q': req.url.params['q'], **echo},
            'organic_results': [{'link': ORIGINAL}, {'link': UPDATE}]})

    w, _, source_transport = workflow([], {ORIGINAL: ORIG_HTML, UPDATE: UPDATE_HTML})
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider_response)) as transport:
        client = SerpApiClient('SYNTHETIC_TEST_CREDENTIAL', client=transport)
        w.executor.client = client
        out = await w.check(request())
    assert out.provider_calls == 6
    if echo:
        assert out.analysis.verdict.value == 'UNRESOLVED'
        assert out.analysis.coverage.value == 'INSUFFICIENT'
        assert out.sources == () and source_transport.calls == []
        assert all(entry.error_code == 'EXECUTION_PARAMETERS_MISMATCH' for entry in out.search_entries)
    else:
        assert out.analysis.verdict.value == 'SUPERSEDED'
        assert out.analysis.coverage.value == 'ADEQUATE'
        assert len(out.sources) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('extra_count, repeat, supplied_url, historical', [
    (10, 1, False, False), (10, 3, True, False),
    (11, 1, True, False), (11, 3, False, True),
])
async def test_source_budget_deduplication_and_historical_controls(extra_count, repeat, supplied_url, historical):
    extras = [f'https://issuer.example/general/{index}' for index in range(extra_count)]
    bodies = {ORIGINAL: ORIG_HTML, UPDATE: UPDATE_HTML,
        **{url: b'<main>General information without a notice reference or governing declaration.</main>' for url in extras}}
    w, _, transport = workflow([ORIGINAL, UPDATE, *extras] * repeat, bodies)
    req = request(url=ORIGINAL if supplied_url else None)
    if historical:
        req = req.model_copy(update={'as_of': datetime(2026, 9, 10, tzinfo=timezone.utc)})
    out = await w.check(req)
    assert out.provider_calls == 6
    if extra_count == 10:
        assert out.analysis.verdict.value == 'SUPERSEDED'
        assert out.analysis.coverage.value == 'ADEQUATE'
        assert len(transport.calls) == 12 and len(out.sources) == 2
    else:
        assert out.analysis.verdict.value == 'UNRESOLVED'
        assert out.analysis.coverage.value == 'INSUFFICIENT'
        assert 'SOURCE_CANDIDATE_BUDGET_EXCEEDED' in out.warnings
        assert not transport.calls and out.sources == ()


@pytest.mark.asyncio
@pytest.mark.parametrize('wrapper', ['<dialog open>{}</dialog>', '<details open>{}</details>',
    '<details><summary>{}</summary>Unrelated collapsed content</details>'])
async def test_visible_native_control_complete_workflow(wrapper):
    body = wrapper.format(UPDATE_HTML.decode()).encode()
    w, _, _ = workflow([ORIGINAL, UPDATE], {ORIGINAL: ORIG_HTML, UPDATE: body})
    out = await w.check(request())
    assert out.analysis.verdict.value == 'SUPERSEDED'
    assert out.analysis.coverage.value == 'ADEQUATE'
    assert len(out.sources) == 2
