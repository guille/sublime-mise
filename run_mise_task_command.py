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


def _task_usage_summary(mise_dir: str, task_name: str, window: sublime.Window) -> str:
    """
    Figures out whether a task accepts arguments, and if so a short usage
    summary to show the user.

    Prefers the `mise tasks info` facility, which understands `usage` specs
    (and legacy tera-style args()/option()/flag() calls). Falls back to the
    raw `usage` field from `mise tasks --json` (already fetched to build the
    task list) for older mise versions that lack the `info` subcommand.

    Returns an empty string if the task doesn't appear to accept arguments.
    """
    info = run_mise_json(
        ["mise", "tasks", "info", task_name, "--json"], mise_dir, window, quiet=True
    )
    if info is not None:
        cmd = info.get("usage_spec", {}).get("cmd", {})
        if cmd.get("args") or cmd.get("flags"):
            return cmd.get("usage", "")
        return ""

    # Fallback: re-read the task list directly, since `tasks info` isn't
    # available. Raw `usage` DSL is truthy whenever the task declares args.
    data = run_mise_json(["mise", "tasks", "--json"], mise_dir, window, quiet=True)
    for task in data or []:
        if task.get("name") == task_name:
            return task.get("usage", "")
    return ""


class MiseTaskArgsInputHandler(sublime_plugin.TextInputHandler):
    def __init__(self, usage_summary: str):
        self.usage_summary = usage_summary

    def name(self):
        return "task_args"

    def placeholder(self):
        return f"Arguments ({self.usage_summary})" if self.usage_summary else "Arguments"

    def description(self, text: str):
        return text or "(no args)"


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

        data = run_mise_json(cmd, current_dir, window)
        if data is None:
            return []

        if not data:
            window.status_message("No tasks available")

        return [self._build_item(x, current_dir) for x in data]

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

        mise_dir, task_name = task
        window = sublime.active_window()
        usage_summary = _task_usage_summary(mise_dir, task_name, window)
        if usage_summary:
            return MiseTaskArgsInputHandler(usage_summary)
        return None


class MiseRunTaskCommand(sublime_plugin.WindowCommand):
    def run(self, task: "tuple[str, str]" = ("", ""), task_args: str = ""):
        if not task or not task[1]:
            return

        mise_dir, task_name = task

        cmd = ["mise", "run", task_name]
        if task_args.strip():
            cmd.extend(shlex.split(task_args))

        exec_args: sublime.CommandArgs = {
            "cmd": cmd,
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
