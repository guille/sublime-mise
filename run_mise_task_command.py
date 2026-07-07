import html
import json
import pathlib
import subprocess
from typing import Any

import sublime
import sublime_plugin


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

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                cwd=current_dir,
            )
            data = json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            window.status_message(f"Command failed with exit code {e.returncode}")
            print(f"stderr: {e.stderr}")
            return []
        except json.JSONDecodeError as e:
            window.status_message(f"Command output was not valid JSON: {e}")
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


class MiseRunTaskCommand(sublime_plugin.WindowCommand):
    def run(self, task: "tuple[str, str]" = ("", "")):
        if not task or not task[1]:
            return

        mise_dir, task_name = task

        exec_args: sublime.CommandArgs = {
            "cmd": ["mise", "run", task_name],
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
            "quiet": False,
        }

        self.window.run_command("exec", exec_args)
