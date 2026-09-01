import html
import pathlib
import shlex
from typing import Any

import sublime
import sublime_plugin

from .mise_shared import run_mise_json


def _find_best_dir(view: sublime.View, window: sublime.Window) -> str:
    """
    Decides what working_dir to run mise from.
    Heuristic:
    1. Parent of the open file
    2. First open folder in the sidebar
    3. $HOME
    """
    # Run from $HOME if we can't find a better path
    current_dir = str(pathlib.Path.home())
    if file := view.file_name():
        current_dir = str(pathlib.Path(file).parent)
    elif open_dirs := window.folders():
        current_dir = open_dirs[0]
    return current_dir


def _task_usage(mise_dir: str, task_name: str, window: sublime.Window) -> str:
    """
    A short usage summary for a task, e.g. "[-v --verbose] <name>", or an
    empty string if the task takes no arguments the user can supply.

    Uses `mise tasks info`, which resolves both `usage` specs and the legacy
    tera-style args()/option()/flag() calls. Versions of mise too old to have
    that subcommand (pre-2024.9.10) just never prompt.
    """
    info = run_mise_json(
        ["mise", "tasks", "info", task_name, "--json"], mise_dir, window, quiet=True
    )
    return (info or {}).get("usage_spec", {}).get("cmd", {}).get("usage", "")


def _split_args(text: str) -> "list[str]":
    """
    Split typed arguments into argv, keeping quoted runs together.

    Non-posix so Windows paths keep their backslashes and a bare apostrophe
    ("don't") isn't read as an opening quote; posix mode mangles both. That
    leaves the quotes on, so wrapping pairs are stripped afterwards.

    Raises ValueError if a quote is left open.
    """
    return [
        t[1:-1] if len(t) > 1 and t[0] == t[-1] and t[0] in "\"'" else t
        for t in shlex.split(text, posix=False)
    ]


class MiseTaskArgsInputHandler(sublime_plugin.TextInputHandler):
    def __init__(self, usage: str):
        self.usage = usage

    def name(self):
        return "task_args"

    def placeholder(self):
        return f"Arguments: {self.usage}"

    def description(self, text: str):
        return text or "(no args)"

    def validate(self, text: str):
        # Refuse an unterminated quote here; by the time the command runs,
        # there is nowhere left to report it but a traceback.
        try:
            _split_args(text)
        except ValueError:
            return False
        return True


class MiseRunTaskHandler(sublime_plugin.ListInputHandler):
    def placeholder(self):
        return "Choose task:"

    def name(self):
        return "task"

    def cancel(self):
        return sublime.active_window().status_message("No task selected")

    def list_items(self) -> "list[sublime.ListInputItem]":
        window = sublime.active_window()
        view = window.active_view()
        if view is None:
            window.status_message("No view is active")
            return []

        current_dir = _find_best_dir(view, window)

        settings = sublime.load_settings("Mise.sublime-settings")
        cmd = ["mise", "tasks", "--json"]
        if settings.get("include_all_monorepo_tasks", False) is True:
            cmd.append("--all")

        result = run_mise_json(cmd, current_dir)
        if result.error is not None:
            window.status_message(result.error)
            if result.stderr:
                print(f"stderr: {result.stderr}")
            return []

        if not result.data:
            window.status_message("No tasks available")
            return []

        return [self._build_item(x, current_dir) for x in result.data]

    def _build_item(self, x: Any, current_dir: str) -> sublime.ListInputItem:
        run = x["run"]
        details = (
            f"<code>{html.escape(run[0])}</code>{' ...' if len(run) > 1 else ''}"
            if run
            else ""
        )
        return sublime.ListInputItem(
            text=x["name"],
            value=(current_dir, x["name"]),
            details=details,
            annotation=x.get("description", ""),
        )

    def next_input(self, args: Any):
        task = args.get("task")
        if not task or not task[1]:
            return None

        usage = _task_usage(task[0], task[1], sublime.active_window())
        return MiseTaskArgsInputHandler(usage) if usage else None


class MiseRunTaskCommand(sublime_plugin.WindowCommand):
    def run(self, task: "tuple[str, str]" = ("", ""), task_args: str = ""):
        if not task or not task[1]:
            return

        mise_dir, task_name = task

        try:
            args = _split_args(task_args)
        except ValueError as e:
            # The palette rejects these in validate(); a keybinding can't.
            self.window.status_message(f"Could not parse task arguments: {e}")
            return

        exec_args: sublime.CommandArgs = {
            "cmd": ["mise", "run", task_name] + args,
            "working_dir": mise_dir,
            "env": {"NO_COLOR": "1"},
            "syntax": "Packages/Mise/Mise Build.sublime-syntax",
            "quiet": False,
        }

        self.window.run_command("exec", exec_args)

    def input(self, args: Any):
        return MiseRunTaskHandler()

    def input_description(self):
        return "Run Mise task"


class MiseTrustCommand(sublime_plugin.WindowCommand):
    def run(self):
        view = self.window.active_view()
        if view is None:
            self.window.status_message("No view is active")
            return

        mise_dir = _find_best_dir(view, self.window)

        exec_args: sublime.CommandArgs = {
            "cmd": ["mise", "trust"],
            "working_dir": mise_dir,
            "env": {"NO_COLOR": "1"},
            "quiet": False,
        }

        self.window.run_command("exec", exec_args)
