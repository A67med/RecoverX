"""Regression checks for the restored Windows Quick Recovery dropdown.

The Streamlit import is intentionally avoided so option mapping can be checked
without running Windows binaries or the interactive UI.
"""
import ast
from pathlib import Path

from recoverx.recovery.orchestrator import _select
from recoverx.quick import guided_recovery


def test_windows_quick_options_match_supported_methods():
    source = (Path(__file__).resolve().parents[2] / 'src/recoverx/ui/dashboard.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    mapping = next(ast.literal_eval(n.value) for n in tree.body
                   if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'QUICK_RECOVERY_METHODS'
                                                        for t in n.targets))
    assert mapping['Smart Recovery (CART + fallback)'] == 'smart'
    assert mapping['TSK only'] == 'tsk'
    assert mapping['PhotoRec only'] == 'photorec'
    assert mapping['TSK + PhotoRec (both)'] == 'combined'
    assert mapping['Automatic (CART only)'] == 'cart'
    assert mapping['Automatic (rule-v1 only)'] == 'rule'
    assert 'st.selectbox(\'Recovery strategy\'' in source
    assert 'method = QUICK_RECOVERY_METHODS[method_choice]' in source
    assert 'method=method, progress=' in source


def test_manual_engine_selection_remains_fixed():
    assert _select('tsk', None, None)['strategy_used'] == 'tsk'
    assert _select('photorec', None, None)['strategy_used'] == 'photorec'
    assert _select('combined', None, None)['strategy_used'] == 'combined'
