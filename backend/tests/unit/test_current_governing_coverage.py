import pytest
from app.domain import *


def evidence(family, helpers, kind):
    a, d, e, b = (helpers[name] for name in ('assertion', 'make_doc', 'event', 'binding'))
    original = d('orig', DocumentRole.ORIGINAL_NOTICE, [a('orig', CriticalField.DEADLINE, '2026-10-01')])
    documents = [original]
    events = [e('original', family.family_id, 'orig', EventType.DECLARES, [CriticalField.DEADLINE], 1)]
    bindings = [b('orig')]
    if kind != 'unchanged':
        cancel = kind == 'cancelled'
        documents.append(d('ext', DocumentRole.CANCELLATION if cancel else DocumentRole.EXTENSION,
            [] if cancel else [a('ext', CriticalField.DEADLINE, '2026-10-26')], issued_day=10))
        events.append(e('update', family.family_id, 'ext', EventType.CANCELS if cancel else EventType.EXTENDS,
            [] if cancel else [CriticalField.DEADLINE], 10, targets=('original',)))
        bindings.append(b('ext'))
    return documents, events, bindings


@pytest.mark.parametrize('coverage', [EvidenceCoverage.PARTIAL, EvidenceCoverage.INSUFFICIENT])
@pytest.mark.parametrize('kind', ['changed', 'cancelled', 'unchanged'])
def test_inadequate_coverage_never_certifies_current_value(family, helpers, coverage, kind):
    documents, events, bindings = evidence(family, helpers, kind)
    out = analyze(family, {CriticalField.DEADLINE: '2026-10-01'}, documents, events, bindings,
                  ResolutionContext(as_of=helpers['dt'](30)), coverage)
    print('DIRECT_COVERAGE', kind, coverage.value, out.verdict.value)
    assert out.verdict == Verdict.UNRESOLVED
    assert out.coverage == coverage
    assert 'EVIDENCE_COVERAGE_INADEQUATE' in out.warnings
    assert all(resolution.value is None and resolution.status == FieldResolutionStatus.UNRESOLVED
               for resolution in out.field_resolutions)


@pytest.mark.parametrize('coverage', list(EvidenceCoverage))
def test_established_conflict_survives_coverage_gate(family, helpers, coverage):
    documents, events, bindings = evidence(family, helpers, 'changed')
    a, d, e, b = (helpers[name] for name in ('assertion', 'make_doc', 'event', 'binding'))
    documents.append(d('fee', DocumentRole.EXTENSION, [a('fee', CriticalField.DEADLINE, '2026-10-20')], issued_day=11))
    events.append(e('competing', family.family_id, 'fee', EventType.EXTENDS, [CriticalField.DEADLINE], 11, targets=('original',)))
    bindings.append(b('fee'))
    out = analyze(family, {CriticalField.DEADLINE: '2026-10-01'}, documents, events, bindings,
                  ResolutionContext(as_of=helpers['dt'](30)), coverage)
    assert out.verdict == Verdict.CONFLICT
    assert out.field_resolutions[0].status == FieldResolutionStatus.CONFLICT
