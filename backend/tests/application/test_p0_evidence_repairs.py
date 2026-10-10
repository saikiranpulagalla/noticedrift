"""Regression tests for evidence-admission invariants found in the P0 audit."""
from __future__ import annotations

import pytest

from app.domain.enums import Verdict
from app.sources import parse_snapshot
from test_v07_workflow import ORIGINAL, UPDATE, ORIG_HTML, UPDATE_HTML, workflow, request


def correction(body: str) -> bytes:
    return ("<main>Corrigendum\nReference: A/2026\nIssued: 2026-09-17\n"
            + body + "</main>").encode()


async def verdict_for(update: bytes):
    runner, _, _ = workflow([ORIGINAL, UPDATE], {ORIGINAL: ORIG_HTML, UPDATE: update})
    return await runner.check(request())


@pytest.mark.asyncio
@pytest.mark.parametrize('selector, attribute', [
    ('.concealed', 'class="concealed"'),
    ('#concealed', 'id="concealed"'),
])
async def test_css_hidden_selected_root_cannot_govern(selector, attribute):
    update = (f'<style>{selector} {{ display:none }}</style>'
              f'<main {attribute}>Corrigendum\nReference: A/2026\nIssued: 2026-09-17\n'
              'The deadline is extended from 01 October 2026 to 26 October 2026</main>').encode()
    outcome = await verdict_for(update)
    assert outcome.analysis.verdict is Verdict.UNRESOLVED


@pytest.mark.asyncio
async def test_css_hidden_evidence_ancestor_cannot_govern():
    update = (b'<style>.concealed { visibility:hidden }</style>'
              b'<section class="concealed"><main>Corrigendum\nReference: A/2026\nIssued: 2026-09-17\n'
              b'The deadline is extended from 01 October 2026 to 26 October 2026</main></section>')
    outcome = await verdict_for(update)
    assert outcome.analysis.verdict is Verdict.UNRESOLVED


@pytest.mark.asyncio
async def test_hidden_descendant_cannot_supply_only_correction():
    update = correction('<style>.concealed { display:none }</style>'
                        '<p class="concealed">The deadline is extended from 01 October 2026 to 26 October 2026</p>')
    outcome = await verdict_for(update)
    assert outcome.analysis.verdict is Verdict.UNRESOLVED


@pytest.mark.asyncio
async def test_visible_correction_with_unrelated_hidden_navigation_still_governs():
    update = correction('<nav class="concealed">administration</nav>'
                        '<style>.concealed { display:none }</style>'
                        'The deadline is extended from 01 October 2026 to 26 October 2026')
    outcome = await verdict_for(update)
    assert outcome.analysis.verdict is Verdict.SUPERSEDED


@pytest.mark.asyncio
@pytest.mark.parametrize('style', [
    '<style>.menu { display:none } .notice { display:block }</style>',
    '<style>.notice { display:block } .menu { display:none }</style>',
])
async def test_unrelated_selector_order_does_not_change_visible_evidence(style):
    update = (style + '<main class="notice">Corrigendum\nReference: A/2026\nIssued: 2026-09-17\n'
              'The deadline is extended from 01 October 2026 to 26 October 2026</main>'
              '<nav class="menu">hidden navigation</nav>').encode()
    outcome = await verdict_for(update)
    assert outcome.analysis.verdict is Verdict.SUPERSEDED


@pytest.mark.asyncio
async def test_responsive_visibility_of_evidence_root_is_conservative():
    update = (b'<style>@media screen { .concealed { display:none } }</style>'
              b'<main class="concealed">Corrigendum\nReference: A/2026\nIssued: 2026-09-17\n'
              b'The deadline is extended from 01 October 2026 to 26 October 2026</main>')
    outcome = await verdict_for(update)
    assert outcome.analysis.verdict is Verdict.UNRESOLVED


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [
    'The deadline is extended from 01 October 2026 to 26 October 2026 for applicants with disabilities. '
    'All other applicants retain the original deadline.',
    'Only for category A, the deadline is extended from 01 October 2026 to 26 October 2026.',
    'The deadline is extended from 01 October 2026 to 26 October 2026 for post A.',
])
async def test_scoped_extension_cannot_become_whole_notice_update(body):
    outcome = await verdict_for(correction(body))
    assert outcome.analysis.verdict is Verdict.UNRESOLVED


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [
    'If the board approves the proposal, the deadline is extended from 01 October 2026 to 26 October 2026.',
    'The deadline is extended from 01 October 2026 to 26 October 2026 subject to board approval.',
    'Proposed extension: the deadline is extended from 01 October 2026 to 26 October 2026.',
    'The deadline is extended from 01 October 2026 to 26 October 2026, pending approval.',
])
async def test_conditional_or_proposed_extension_cannot_govern(body):
    outcome = await verdict_for(correction(body))
    assert outcome.analysis.verdict is Verdict.UNRESOLVED


@pytest.mark.asyncio
async def test_unrelated_distant_condition_does_not_reclassify_standalone_extension():
    outcome = await verdict_for(correction(
        'The deadline is extended from 01 October 2026 to 26 October 2026.\n'
        'The application portal remains available for notices.\n'
        'For help, contact the office if assistance is required.'))
    assert outcome.analysis.verdict is Verdict.SUPERSEDED


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [
    'The deadline is extended from 01 October 2026 to 26 October 2026.\nApplication deadline: 10 October 2026',
    'Application deadline: 10 October 2026\nThe deadline is extended from 01 October 2026 to 26 October 2026.',
    'The deadline is extended from 01 October 2026 to 26 October 2026.\nApplication deadline: 26 October 2026\nApplication deadline: 10 October 2026',
])
async def test_conflicting_application_deadline_cannot_be_discarded(body):
    outcome = await verdict_for(correction(body))
    assert outcome.analysis.verdict is Verdict.UNRESOLVED


@pytest.mark.asyncio
async def test_repeated_consistent_new_application_deadline_is_conservatively_ambiguous():
    outcome = await verdict_for(correction(
        'The deadline is extended from 01 October 2026 to 26 October 2026.\n'
        'Application deadline: 26 October 2026'))
    # The exact quotation grounder deliberately refuses a repeated value without
    # an offset; conservative abstention is preferable to choosing a mention.
    assert outcome.analysis.verdict is Verdict.UNRESOLVED


@pytest.mark.asyncio
async def test_historical_old_deadline_and_publication_date_do_not_conflict():
    outcome = await verdict_for(correction(
        'Published: 10 October 2026\n'
        'The original application deadline: 01 October 2026\n'
        'The deadline is extended from 01 October 2026 to 26 October 2026.'))
    assert outcome.analysis.verdict is Verdict.SUPERSEDED


@pytest.mark.asyncio
async def test_fee_deadline_is_not_an_application_deadline_conflict():
    outcome = await verdict_for(correction(
        'Fee payment deadline: 10 October 2026\n'
        'The deadline is extended from 01 October 2026 to 26 October 2026.'))
    assert outcome.analysis.verdict is Verdict.SUPERSEDED


def test_visible_document_with_unrelated_hidden_navigation_remains_parsed():
    runner, _, _ = workflow([ORIGINAL], {ORIGINAL: ORIG_HTML})
    snapshot = runner.fetcher.fetch(ORIGINAL, allowed_hosts=frozenset({'issuer.example'}))
    assert parse_snapshot(snapshot).status == 'PARSED'
