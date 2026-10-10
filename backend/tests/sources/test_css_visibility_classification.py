"""Static evidence visibility: definite hiding versus conditional rendering."""
from datetime import datetime, timezone
from hashlib import sha256

import pytest

from app.sources import parse_snapshot
from app.sources.models import SourceSnapshot


def parsed(css, *, attribute='class="notice"', before='', after='', content=None):
    content = content or ('Corrigendum Reference A/2026 issued 2026-09-17. '
                          'The deadline is extended from 01 October 2026 to 26 October 2026.')
    body = (f'<html><head><style>{css}</style></head><body>{before}'
            f'<main {attribute}>{content}</main>{after}</body></html>').encode()
    return parse_snapshot(SourceSnapshot(
        source_url='https://issuer.example/notices/a',
        final_url='https://issuer.example/notices/a',
        captured_at=datetime.now(timezone.utc), content_type='text/html',
        body=body, body_sha256=sha256(body).hexdigest()))


@pytest.mark.parametrize('selector,attribute', [
    ('.notice', 'class="notice"'), ('#notice', 'id="notice"')])
def test_unconditional_root_is_definitely_hidden(selector, attribute):
    result = parsed(f'{selector} {{display:none}}', attribute=attribute)
    assert result.status == 'UNSUPPORTED'
    assert result.warning_codes == ('HIDDEN_EVIDENCE_ROOT',)
    assert result.text == ''


@pytest.mark.parametrize('condition', [
    '@media print', '@media screen', '@supports (display: grid)',
    '@container (width > 600px)', '@media screen { @supports (display:grid)'])
def test_conditional_root_is_not_claimed_definitely_hidden(condition):
    css = condition + ' { .notice { display:none } }'
    if '{' in condition:
        css += ' }'
    result = parsed(css)
    assert result.status == 'UNSUPPORTED'
    assert result.warning_codes == ('CSS_RESPONSIVE_VISIBILITY_UNVERIFIED',)
    assert result.text == ''


@pytest.mark.parametrize('condition', ['@media print', '@supports (display:grid)'])
def test_conditional_ancestor_blocks_evidence(condition):
    result = parsed(condition + ' { .wrapper {visibility:hidden} }',
                    before='<section class="wrapper">', after='</section>')
    assert result.status == 'UNSUPPORTED'
    assert result.warning_codes == ('CSS_RESPONSIVE_VISIBILITY_UNVERIFIED',)


@pytest.mark.parametrize('condition', ['', '@media screen'])
def test_irrelevant_visibility_rule_does_not_taint_main(condition):
    css = '.menu {display:none}'
    if condition:
        css = condition + ' {' + css + '}'
    # Keep an actual matched node outside main (not a nav removed earlier).
    result = parsed(css, after='<div class="menu">Unrelated menu</div>')
    assert result.status == 'PARSED'
    assert result.warning_codes == ()
    assert 'extended' in result.text
    assert 'Unrelated menu' not in result.text


def test_hidden_descendant_cannot_supply_the_amendment():
    result = parsed('.concealed {display:none}', content=(
        'Reference A/2026 issued 2026-09-17. '
        '<p class="concealed">The deadline is extended to 26 October 2026.</p>'))
    assert 'extended' not in result.text
    assert '26 October' not in result.text


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('other', [
    '@media print {.notice {display:none}}',
    '@media screen {.menu {display:none}}'])
def test_mixed_rules_keep_unconditional_root_exclusion(reverse, other):
    rules = ['.notice {display:none}', other]
    if reverse:
        rules.reverse()
    result = parsed(' '.join(rules), after='<div class="menu">Menu</div>')
    assert result.status == 'UNSUPPORTED'
    assert 'HIDDEN_EVIDENCE_ROOT' in result.warning_codes
    assert ('CSS_RESPONSIVE_VISIBILITY_UNVERIFIED' in result.warning_codes) == ('.notice' in other)


@pytest.mark.parametrize('reverse', [False, True])
def test_visible_override_does_not_certify_conditional_visibility(reverse):
    rules = ['.notice {display:block}', '@media print {.notice {display:none}}']
    if reverse:
        rules.reverse()
    result = parsed(' '.join(rules))
    assert result.status == 'UNSUPPORTED'
    assert result.warning_codes == ('CSS_RESPONSIVE_VISIBILITY_UNVERIFIED',)


def test_comments_do_not_change_rule_context():
    result = parsed('/* @media print { */ .notice {display:none} /* } */')
    assert result.status == 'UNSUPPORTED'
    assert result.warning_codes == ('HIDDEN_EVIDENCE_ROOT',)


def test_plain_visible_correction_remains_parsed():
    result = parsed('.notice {display:block}')
    assert result.status == 'PARSED'
    assert result.warning_codes == ()
    assert 'extended from 01 October 2026 to 26 October 2026' in result.text
