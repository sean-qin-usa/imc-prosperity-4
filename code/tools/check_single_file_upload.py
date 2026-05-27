from __future__ import annotations

import argparse
import ast
import importlib.util
import py_compile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MAX_UPLOAD_BYTES = 100_000
FORBIDDEN_SNIPPETS = {
    "spec_from_file_location": "dynamic sibling-file import",
    "module_from_spec": "dynamic sibling-file import",
    "exec_module(": "dynamic module execution",
    "Path(__file__)": "filesystem-relative dependency",
    "__file__": "filesystem-relative dependency",
}
ALLOWED_MODULES = {"datamodel"}


def resolves_inside_repo(module_name: str) -> bool:
    if not module_name or module_name in ALLOWED_MODULES:
        return False
    spec = importlib.util.find_spec(module_name)
    if spec is None or spec.origin in {None, "built-in", "frozen"}:
        return False
    origin = Path(spec.origin).resolve()
    try:
        origin.relative_to(REPO_ROOT)
    except ValueError:
        return False
    return True


def import_issues(path: Path, text: str) -> list[str]:
    issues: list[str] = []
    tree = ast.parse(text, filename=str(path))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_name = alias.name.split(".")[0]
                if resolves_inside_repo(top_name):
                    issues.append(f"imports local repo module `{alias.name}`")
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[0]
            if node.level:
                issues.append("uses relative import")
            elif resolves_inside_repo(module):
                issues.append(f"imports local repo module `{node.module}`")
    return issues


def check_path(path: Path) -> list[str]:
    issues: list[str] = []
    if not path.exists():
        return [f"missing file: {path}"]

    text = path.read_text(encoding="utf-8")
    if path.stat().st_size > MAX_UPLOAD_BYTES:
        issues.append(
            f"file size {path.stat().st_size} bytes exceeds {MAX_UPLOAD_BYTES}-byte upload limit"
        )

    for snippet, reason in FORBIDDEN_SNIPPETS.items():
        if snippet in text:
            issues.append(f"contains `{snippet}` ({reason})")

    try:
        py_compile.compile(str(path), doraise=True)
    except py_compile.PyCompileError as exc:
        issues.append(f"py_compile failed: {exc.msg}")

    try:
        issues.extend(import_issues(path, text))
    except SyntaxError as exc:
        issues.append(f"ast parse failed: {exc}")

    return issues


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check whether a strategy file is safe for IMC single-file upload."
    )
    parser.add_argument("paths", nargs="+", type=Path, help="Python files to check")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    failed = False

    for raw_path in args.paths:
        path = raw_path if raw_path.is_absolute() else (Path.cwd() / raw_path).resolve()
        issues = check_path(path)
        if issues:
            failed = True
            print(f"FAIL {path}")
            for issue in issues:
                print(f"  - {issue}")
        else:
            print(f"OK   {path}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
