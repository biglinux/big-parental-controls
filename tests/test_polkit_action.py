"""The window's startup polkit check must use the group-helper's action.

polkit keeps an auth_admin_keep authorization per action, so checking a
different action at startup makes every later pkexec call ask again.
"""

import ast
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WINDOW = REPO / "src" / "big_parental_controls" / "window.py"
POLICY = (
    REPO
    / "big-parental-controls/usr/share/polkit-1/actions/br.com.biglinux.parental-controls.policy"
)
HELPER = "/usr/lib/big-parental-controls/group-helper"
EXEC_PATH = "org.freedesktop.policykit.exec.path"


def _window_action() -> str:
    tree = ast.parse(WINDOW.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "POLKIT_ACTION" for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("POLKIT_ACTION not found in window.py")


def _helper_action() -> str:
    for action in ET.parse(POLICY).getroot().iter("action"):
        for annotate in action.iter("annotate"):
            if annotate.get("key") == EXEC_PATH and annotate.text == HELPER:
                return action.get("id")
    raise AssertionError("no polkit action for group-helper")


def test_startup_check_uses_group_helper_action() -> None:
    assert _window_action() == _helper_action()


def test_group_helper_action_keeps_authorization() -> None:
    action_id = _helper_action()
    action = next(a for a in ET.parse(POLICY).getroot().iter("action") if a.get("id") == action_id)
    assert action.findtext("defaults/allow_active") == "auth_admin_keep"
