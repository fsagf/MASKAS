import ast
import os
import re
import pytest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def get_project_python_files():
    """Returns all project Python files excluding virtual environment and cache directories."""
    py_files = []
    for root, dirs, files in os.walk(ROOT_DIR):
        dirs[:] = [d for d in dirs if d not in ("venv", ".git", ".pytest_cache", "__pycache__", "build", "dist")]
        for file in files:
            if file.endswith(".py"):
                py_files.append(os.path.join(root, file))
    return py_files


def test_syntax_and_ast_parsing():
    """Verify that every python file in the codebase has valid syntax and compiles cleanly."""
    py_files = get_project_python_files()
    assert len(py_files) > 10, f"Expected project files, found only {len(py_files)}"

    for file_path in py_files:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            code = f.read()
        try:
            ast.parse(code, filename=file_path)
        except SyntaxError as e:
            pytest.fail(f"Syntax error in {file_path}: {e}")


def test_no_deprecated_flet_calls():
    """
    Strict check for flet 0.25.2 compatibility:
    - No page.window_width or page.window_height
    - No lowercase ft.icons.* or ft.colors.* calls
    """
    py_files = get_project_python_files()

    forbidden_patterns = [
        (r"\bpage\.window_width\b", "Deprecated page.window_width used (use page.width or page.window.width)"),
        (r"\bpage\.window_height\b", "Deprecated page.window_height used (use page.height or page.window.height)"),
        (r"\bft\.icons\.[a-z]", "Lowercase ft.icons.* used (must use UPPERCASE e.g. ft.icons.ADD)"),
        (r"\bft\.colors\.[a-z]", "Lowercase ft.colors.* used (must use UPPERCASE e.g. ft.colors.GREEN)"),
    ]

    errors = []
    for file_path in py_files:
        # Don't check the test file itself for patterns
        if "test_static_architecture.py" in file_path:
            continue

        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        for idx, line in enumerate(lines, 1):
            # Ignore comments
            clean_line = line.split("#")[0].strip()
            for pattern, desc in forbidden_patterns:
                if re.search(pattern, clean_line):
                    errors.append(f"{os.path.basename(file_path)}:{idx} -> {desc}: {clean_line}")

    assert not errors, "Forbidden / deprecated patterns found:\n" + "\n".join(errors)


def test_no_circular_imports_core_modules():
    """
    Verify that core modules can be imported independently without circular dependencies.
    """
    import database
    import analytics
    import services.chart_service
    import services.sync_service
    import ui.theme
    import ui.layout

    assert database.DatabaseManager is not None
    assert analytics.AnalyticsService is not None
    assert services.chart_service.generate_trade_chart is not None
    assert services.sync_service.SyncService is not None
    assert ui.theme.BG_APP is not None
    assert ui.theme.ACCENT_PRIMARY is not None
    assert ui.layout.AppLayout is not None
