import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location('compatibility_checker', Path(__file__).resolve().parents[1] / 'scripts/check_compatibility.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def pair():
    return ({'component':'miniworlds-editor','version':'1.0.0','api':{'min':1,'max':1},'requires':{'backend_api':{'min':1,'max':1},'capabilities':['project-files']}},
            {'component':'miniworlds-editor-backend','version':'1.0.0','api':{'min':1,'max':1},'requires':{'frontend_api':{'min':1,'max':1}},'capabilities':['project-files']})


def test_compatible_pair_and_independent_patch_updates():
    frontend, backend = pair()
    backend['version'] = '1.0.99'
    assert checker.check(frontend, backend) == []


def test_checker_identifies_required_backend_update():
    frontend, backend = pair()
    frontend['requires']['backend_api'] = {'min':2,'max':2}
    assert any('Backend aktualisieren' in problem for problem in checker.check(frontend, backend))


def test_checker_identifies_required_frontend_update():
    frontend, backend = pair()
    backend['requires']['frontend_api'] = {'min':2,'max':2}
    assert any('Frontend aktualisieren' in problem for problem in checker.check(frontend, backend))


def test_missing_capability_is_incompatible_even_with_overlapping_version_ranges():
    frontend, backend = pair()
    backend['capabilities'] = []
    assert any('project-files' in problem for problem in checker.check(frontend, backend))
