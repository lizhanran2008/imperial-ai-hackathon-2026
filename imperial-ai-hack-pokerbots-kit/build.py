"""Bundle src/ modules into a standalone standard-library-only bot.py."""

import ast
import hashlib
import importlib.util
import os
import subprocess
import sys
import sysconfig
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(HERE, "src")
OUT_PATH = os.path.join(HERE, "bot.py")
MAX_BOT_BYTES = 200_000
LOAD_TIMEOUT_SECONDS = 5

MODULES = (
    "common",
    "handeval",
    "preflop",
    "opponents",
    "postflop",
    "agent",
)

_STDLIB_DIRS = {
    os.path.realpath(p)
    for p in (sysconfig.get_path("stdlib"), sysconfig.get_path("platstdlib"))
    if p
}


def _is_stdlib_module(top_name):
    """Return True if top_name is part of the Python standard library."""
    if top_name in sys.builtin_module_names:
        return True
    if hasattr(sys, "stdlib_module_names"):
        return top_name in sys.stdlib_module_names
    spec = importlib.util.find_spec(top_name)
    if spec is None:
        return False
    origin = spec.origin
    if origin in ("built-in", "frozen"):
        return True
    if origin is None:
        return False
    real_origin = os.path.realpath(origin)
    if "site-packages" in real_origin or "dist-packages" in real_origin:
        return False
    return any(
        real_origin == d or real_origin.startswith(d + os.sep) for d in _STDLIB_DIRS
    )


def _require_bundled(name, path):
    if name not in MODULES:
        raise SystemExit(f"Unknown bundled module 'src.{name}' in {path}")


def _validate_module(source, path):
    """Parse static imports and require supported bundled or standard-library modules."""
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        raise SystemExit(f"Syntax error in {path}: {exc}") from exc

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top, _, member = alias.name.partition(".")
                if top == "src":
                    if member:
                        _require_bundled(member, path)
                elif not _is_stdlib_module(top):
                    raise SystemExit(
                        f"Disallowed non-stdlib import '{alias.name}' in {path}"
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.level > 1:
                raise SystemExit(f"Relative import outside src in {path}")
            if (node.level == 1 and node.module is None) or (
                node.level == 0 and node.module == "src"
            ):
                for alias in node.names:
                    _require_bundled(alias.name, path)
            elif node.level == 1:
                _require_bundled(node.module, path)
            elif node.module.startswith("src."):
                _require_bundled(node.module[4:], path)
            elif not _is_stdlib_module(node.module.split(".")[0]):
                raise SystemExit(
                    f"Disallowed non-stdlib import 'from {node.module}' in {path}"
                )


def _source_digest(sources):
    """Identify the exact bundled sources independently of the Git checkout state."""
    digest = hashlib.sha256()
    for name in MODULES:
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(sources[name].encode("utf-8") + b"\0")
    return digest.hexdigest()


def _render_bot(sources, digest):
    """Render standalone single-file bot.py source."""
    lines = [
        f"# Bundled source SHA-256: {digest}",
        '"""Generated standalone AlgoSoc Pokerbot. Do not edit by hand; run build.py."""',
        "",
        "import sys as _sys",
        "import types as _types",
        "",
        "_PKG_NAME = 'src'",
        "_pkg = _types.ModuleType(_PKG_NAME)",
        "_pkg.__path__ = []",
        "_sys.modules[_PKG_NAME] = _pkg",
        "",
        "_MODULE_SOURCES = {",
    ]
    for name in MODULES:
        lines.append(f"    {name!r}: {sources[name]!r},")
    lines.extend(
        [
            "}",
            "",
            "for _mod_name, _mod_src in _MODULE_SOURCES.items():",
            "    _full_name = f'{_PKG_NAME}.{_mod_name}'",
            "    _mod = _types.ModuleType(_full_name)",
            "    _mod.__package__ = _PKG_NAME",
            "    _sys.modules[_full_name] = _mod",
            "    setattr(_pkg, _mod_name, _mod)",
            "    exec(compile(_mod_src, f'src/{_mod_name}.py', 'exec'), _mod.__dict__)",
            "",
            "Agent = _sys.modules[f'{_PKG_NAME}.agent'].Agent",
            "",
        ]
    )
    return "\n".join(lines)


def _verify_loads(bot_path):
    """Verify bot.py loads cleanly in an isolated Python process."""
    check_code = (
        "import importlib.util; "
        f"spec = importlib.util.spec_from_file_location('bot', {bot_path!r}); "
        "mod = importlib.util.module_from_spec(spec); "
        "spec.loader.exec_module(mod); "
        "agent = mod.Agent(); "
        "assert callable(agent.on_table_start); "
        "assert callable(agent.act); "
        "assert callable(agent.on_hand_end)"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-B", "-c", check_code],
            cwd=os.path.dirname(bot_path),
            capture_output=True,
            timeout=LOAD_TIMEOUT_SECONDS,
            text=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise SystemExit(
            f"Generated bot.py failed to load within {LOAD_TIMEOUT_SECONDS} seconds."
        ) from exc
    if proc.returncode != 0:
        raise SystemExit(
            f"Generated bot.py failed isolated load check:\n{proc.stderr or proc.stdout}"
        )


def main():
    sources = {}
    for name in MODULES:
        path = os.path.join(SRC_DIR, f"{name}.py")
        if not os.path.isfile(path):
            raise SystemExit(f"Missing module: {path}")
        with open(path, "r", encoding="utf-8") as fh:
            source = fh.read()
        _validate_module(source, path)
        sources[name] = source

    digest = _source_digest(sources)
    rendered = _render_bot(sources, digest).encode("utf-8")
    if len(rendered) > MAX_BOT_BYTES:
        raise SystemExit(
            f"Generated bot.py is {len(rendered)} bytes. Limit: {MAX_BOT_BYTES} bytes."
        )

    with tempfile.TemporaryDirectory(prefix=".pokerbot-build-", dir=HERE) as temp_dir:
        candidate = os.path.join(temp_dir, "bot.py")
        with open(candidate, "wb") as fh:
            fh.write(rendered)
        _verify_loads(candidate)
        os.replace(candidate, OUT_PATH)

    print(f"Built {OUT_PATH} ({len(rendered)} bytes, source SHA-256: {digest}).")


if __name__ == "__main__":
    main()
