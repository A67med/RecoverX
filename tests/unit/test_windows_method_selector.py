"""The Quick Recovery method selector exposes exactly the six supported strategies.

Parsed with ast so the mapping is checked without importing Streamlit.
"""
import ast
from pathlib import Path

from recoverx.recovery.orchestrator import _select
from recoverx.workflow import METHODS as WORKFLOW_METHODS


def _methods():
    source = (Path(__file__).resolve().parents[2] / 'src/recoverx/ui/quick_app.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    node = next(n for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'METHODS' for t in n.targets))
    return [(k, label) for k, label, _ in ast.literal_eval(node.value)], source


def test_six_quick_options_map_to_supported_methods():
    methods, source = _methods()
    assert methods == [('smart', 'Smart Recovery'), ('tsk', 'TSK only'), ('photorec', 'PhotoRec only'),
                       ('combined', 'TSK + PhotoRec'), ('cart', 'Automatic (CART only)'),
                       ('rule', 'Automatic (rule-v1 only)')]
    assert {k for k, _ in methods} == set(WORKFLOW_METHODS)
    assert 'st.radio("Recovery method"' in source


def test_manual_engine_selection_remains_fixed():
    assert _select('tsk', None, None)['strategy_used'] == 'tsk'
    assert _select('photorec', None, None)['strategy_used'] == 'photorec'
    assert _select('combined', None, None)['strategy_used'] == 'combined'
