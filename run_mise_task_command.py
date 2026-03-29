import json
import pathlib
import subprocess
from typing import Any

import sublime
import sublime_plugin


class RunMiseTaskHandler(sublime_plugin.ListInputHandler):
    def placeholder(self):
        return "Choose task:"

    def name(self):
        return "task"

    def cancel(self):
        return sublime.active_window().status_message("No task selected")

    def list_items(self) -> "list[sublime.ListInputItem]":
        window = sublime.active_window()
        view = window.active_view()
        # Run from $HOME if we can't find a better path
        current_dir = str(pathlib.Path.home())
        if view:
            file = view.file_name()
            if file:
                current_dir = str(pathlib.Path(file).parent)
            else:
                open_dirs = window.folders()
                if open_dirs:
                    current_dir = open_dirs[0]
        else:
            window.status_message("No view is active")
            return []

        try:
            result = subprocess.run(
                ["mise", "tasks", "--json", "--cd", current_dir],
                capture_output=True,
                text=True,
                check=True,
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

        return [
            sublime.ListInputItem(
                text=x["name"],
                value=(current_dir, x["name"]),
                details=x["run"],
                annotation=x.get("description", ""),
            )
            for x in data
        ]


class RunMiseTaskCommand(sublime_plugin.WindowCommand):
    def run(self, task: "tuple[str, str]" = ("", "")):
        if not task or not task[1]:
            return

        mise_dir, task_name = task
        # print(f"Running {task_name} inside {mise_dir}")

        exec_args: sublime.CommandArgs = {
            "cmd": ["mise", "run", task_name],
            "working_dir": mise_dir,
            "syntax": "Packages/Mise/Mise Build.sublime-syntax",
            "quiet": False,
        }

        self.window.run_command("exec", exec_args)

    def input(self, args: Any):
        return RunMiseTaskHandler()

    def input_description(self):
        return "Run Mise task"
