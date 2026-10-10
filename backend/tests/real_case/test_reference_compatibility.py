"""Publisher-wording compatibility and strict no-false-live guarantees."""
import importlib.util
from pathlib import Path
import pytest

SRC = Path(__file__).resolve().parents[3] / 'scripts'

def load(filename):
    spec=importlib.util.spec_from_file_location(filename[:-3],SRC/filename)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def probe():
    return load('real_case_probe.py')


def test_real_publisher_ordinal_date_wording(probe):
    result=probe.reviewed_deadlines(probe.REVIEWED_ORIGINAL,probe.REVIEWED_CORRECTION)
    assert result['original_deadline']=='2026-10-01'
    assert result['revised_deadline']=='2026-10-26'
    assert result['serpapi_verified'] is False
    assert result['captured_raw_sources_verified'] is False


@pytest.mark.parametrize('new,old',[
    ('1st October 2026','1st October 2026'),
    ('2nd September 2026','1st October 2026'),
    ('31st February 2026','1st October 2026'),
    ('26th October 2026','30th September 2026'),
])
def test_invalid_transitions_abstain(probe,new,old):
    txt=f'The revised deadline for receipt of applications is now {new} instead of {old}.'
    with pytest.raises(probe.ReviewedExcerptError):
        probe.reviewed_deadlines(probe.REVIEWED_ORIGINAL,txt)


@pytest.mark.parametrize('unsafe',[ 'This extension has been withdrawn.', 'This is a false rumor.', 'The extension was rescinded.', 'This is only proposed.'])
def test_negated_or_qualified_excerpt_abstains(probe,unsafe):
    with pytest.raises(probe.ReviewedExcerptError):
        probe.reviewed_deadlines(probe.REVIEWED_ORIGINAL, probe.REVIEWED_CORRECTION+' '+unsafe)


def test_multiple_conflicting_changes_abstain(probe):
    with pytest.raises(probe.ReviewedExcerptError):
        probe.reviewed_deadlines(probe.REVIEWED_ORIGINAL,probe.REVIEWED_CORRECTION+' '+probe.REVIEWED_CORRECTION)


def test_local_untrusted_file_can_be_probed_without_becoming_governing(tmp_path,probe):
    path=tmp_path/'candidate.html'
    path.write_text('<html><main><p>'+probe.REVIEWED_CORRECTION+'</p></main></html>')
    out=probe.probe_local_file(path,mime='text/html',source_url=probe.NCAF_CORRECTION_PAGE)
    assert out['parser_status']=='PARSED'
    assert out['contains_revised_deadline_phrase'] is True
    assert out['governing_evidence_admitted'] is False
    assert 'UNVERIFIED_NETWORK_ORIGIN' in out['provenance']


def test_probe_cli_does_not_require_key_or_network(capsys,probe):
    assert probe.main([])==0
    out=capsys.readouterr().out
    assert 'MANUALLY_REVIEWED_TEXT_NO_PROVIDER_REQUEST' in out
    assert '"serpapi_verified": false' in out


def test_live_operator_script_refuses_execution_without_credentials(monkeypatch,capsys):
    mod=load('live_ncaf_check.py')
    monkeypatch.delenv('SERPAPI_API_KEY',raising=False)
    assert mod.main(['--execute'])==2
    assert 'no network calls made' in capsys.readouterr().err


def test_live_operator_dryrun_prints_valid_preserved_ref_and_no_provider_calls(capsys):
    mod=load('live_ncaf_check.py')
    assert mod.main([])==0
    import json
    data=json.loads(capsys.readouterr().out)
    assert data['max_search_calls']<=8
    assert '4-22/ESTT./TEACHING ASSOCIATES/2026-NCA-F' in data['queries'][0]['query']
    assert data['mode']=='DRY_RUN_NO_REQUESTS'
