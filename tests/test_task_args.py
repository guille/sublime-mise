"""Self-check for prompting for mise task arguments.

Run from the repo root with a real mise on PATH:

    python3 tests/test_task_args.py

Sublime's `sublime`/`sublime_plugin` modules only exist inside the editor, so
they get stubbed before importing the plugin.
"""

import importlib.util
import subprocess
import sys
import tempfile
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

CONFIG = """
[tasks.noargs]
run = "echo hi"

[tasks.spec]
usage = '''
arg "<name>"
flag "-v --verbose"
'''
run = "echo hi"

[tasks.tera]
run = "echo {{arg(name='thing')}}"

[tasks.hidden]
usage = 'arg "<name>" hide=#true'
run = "echo hi"
"""


def load_plugin():
    sublime = types.ModuleType("sublime")
    for attr in ("Window", "View", "ListInputItem"):
        setattr(sublime, attr, object)
    sublime.active_window = lambda: _Window()  # pyright: ignore[reportAttributeAccessIssue]
    sys.modules["sublime"] = sublime

    plugin = types.ModuleType("sublime_plugin")
    for attr in (
        "EventListener",
        "WindowCommand",
        "ListInputHandler",
        "TextInputHandler",
    ):
        setattr(plugin, attr, object)
    sys.modules["sublime_plugin"] = plugin

    pkg = types.ModuleType("mise")
    pkg.__path__ = [str(REPO)]  # pyright: ignore[reportAttributeAccessIssue]
    sys.modules["mise"] = pkg

    module = None
    for name in ("mise_shared", "run_mise_task_command"):
        spec = importlib.util.spec_from_file_location(
            "mise.{}".format(name), str(REPO / "{}.py".format(name))
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["mise.{}".format(name)] = module
        spec.loader.exec_module(module)
    return module


class _Window(object):
    def __init__(self):
        self.messages = []

    def status_message(self, msg):
        self.messages.append(msg)

    def run_command(self, name, args):
        self.command = (name, args)


def test_split_args(rt):
    """Quoted runs stay together; Windows paths and apostrophes survive."""
    assert rt._split_args("") == []
    assert rt._split_args("   ") == []
    assert rt._split_args("bob --force") == ["bob", "--force"]
    assert rt._split_args('a "b c"') == ["a", "b c"]
    assert rt._split_args("a 'b c'") == ["a", "b c"]
    # posix=True would eat the backslashes and choke on the apostrophe
    assert rt._split_args(r"C:\path\to\file") == [r"C:\path\to\file"]
    assert rt._split_args("don't") == ["don't"]

    for bad in ('a "unbalanced', "x 'y", '"'):
        try:
            rt._split_args(bad)
        except ValueError:
            continue
        raise AssertionError("expected ValueError for {!r}".format(bad))


def test_validate_rejects_open_quote(rt):
    """The palette blocks enter rather than letting the command traceback."""
    handler = rt.MiseTaskArgsInputHandler("<name>")
    assert handler.validate("bob") is True
    assert handler.validate('a "unbalanced') is False


def test_usage_only_when_task_takes_args(rt):
    """Only tasks with usable args prompt, whichever DSL declared them."""
    root = Path(tempfile.mkdtemp()).resolve()
    (root / "mise.toml").write_text(CONFIG)
    subprocess.run(["mise", "trust", str(root / "mise.toml")], capture_output=True)

    usage = lambda name: rt._task_usage(str(root), name, _Window())
    assert usage("spec") == "[-v --verbose] <name>"
    assert usage("tera") == "<thing>"  # legacy tera arg() calls
    assert usage("noargs") == ""
    assert usage("hidden") == ""  # nothing the user can usefully type
    assert usage("nonexistent") == ""  # `tasks info` exits non-zero

    handler = rt.MiseRunTaskHandler()
    assert handler.next_input({"task": (str(root), "noargs")}) is None
    assert handler.next_input({"task": ("", "")}) is None
    assert handler.next_input({"task": (str(root), "spec")}) is not None


def test_command_builds_argv(rt):
    """Typed args reach mise as argv, and a bad quote never crashes."""
    window = _Window()
    cmd = rt.MiseRunTaskCommand.__new__(rt.MiseRunTaskCommand)
    cmd.window = window

    cmd.run(task=("/tmp", "spec"), task_args='-v "two words"')
    assert window.command[1]["cmd"] == ["mise", "run", "spec", "-v", "two words"]

    cmd.run(task=("/tmp", "spec"), task_args="")
    assert window.command[1]["cmd"] == ["mise", "run", "spec"]

    window.command = None
    cmd.run(task=("/tmp", "spec"), task_args='a "unbalanced')
    assert window.command is None
    assert window.messages


def main():
    if subprocess.run(["mise", "--version"], capture_output=True).returncode != 0:
        print("mise not available on PATH; skipping")
        return 0

    rt = load_plugin()
    tests = [
        test_split_args,
        test_validate_rejects_open_quote,
        test_usage_only_when_task_takes_args,
        test_command_builds_argv,
    ]
    failed = 0
    for test in tests:
        try:
            test(rt)
            print("ok   {}".format(test.__name__))
        except AssertionError:
            failed += 1
            import traceback

            print("FAIL {}".format(test.__name__))
            traceback.print_exc()
    print("\n{}/{} passed".format(len(tests) - failed, len(tests)))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
