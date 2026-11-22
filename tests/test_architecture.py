"""The core, backends, and controllers must stay GUI-framework-agnostic.

PySide6 is the default UI adapter and may only be imported under src/myloai/ui/
(and by plugins, which are user code). This test enforces that boundary so the
application is not permanently hardwired to one GUI framework.
"""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK_MODULES = ("PySide6", "PyQt6", "PyQt5", "tkinter", "kivy", "wx")


def _qt_imports(package_dir: Path) -> list[tuple[str, int, str]]:
    offenders = []
    for path in sorted(package_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for module in modules:
                if module.split(".")[0] in FRAMEWORK_MODULES:
                    offenders.append((str(path.relative_to(REPO_ROOT)), node.lineno, module))
    return offenders


def test_core_and_backends_have_no_gui_framework_imports():
    offenders = _qt_imports(REPO_ROOT / "src" / "myloai" / "core")
    offenders += _qt_imports(REPO_ROOT / "src" / "myloai" / "backends")
    assert offenders == []


def test_controllers_use_window_ports_not_gui_imports():
    offenders = _qt_imports(REPO_ROOT / "src" / "myloai" / "ui" / "controllers")
    assert offenders == []
