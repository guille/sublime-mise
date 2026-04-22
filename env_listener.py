import json
import os
import subprocess
from pathlib import Path
from typing import Any, cast

import sublime
import sublime_plugin

MISE_KEYFILES = ("mise.toml", "mise.local.toml")


# Python 3.9
def is_relative_to(path: Path, other: Path):
    try:
        path.relative_to(other)
        return True
    except ValueError:
        return False


_mise_env_cache: "dict[int, list[tuple[str, str | None, str]]]" = {}


class MiseEnvListener(sublime_plugin.EventListener):
    def is_enabled(self) -> bool:
        settings = sublime.load_settings("Mise.sublime-settings")
        return settings.get("load_env_in_projects", False) is True

    def _has_keyfiles(self, path: Path) -> bool:
        return any((path / name).exists() for name in MISE_KEYFILES)

    def fetch_env_vars(self, window: sublime.Window) -> "dict[str,str]":
        proj_file = window.project_file_name()
        if proj_file is None:
            project_path = None
        else:
            project_path = Path(proj_file).parent

        vars_to_apply: "dict[str,str]" = {}
        folders = cast("dict[str, Any]", window.project_data()).get("folders", [])

        normalized: list[Path] = []
        for folder in folders:
            path = Path(folder["path"])
            if not path.is_absolute():
                if project_path is None:
                    window.status_message(
                        "Can't find relative path without a project path"
                    )
                    continue
                path = project_path / path
            if not self._has_keyfiles(path):
                continue
            normalized.append(path.resolve())

        # Exclude any folder that is a child of another folder in the list.
        # Sort by path depth so parents are always checked before children.
        normalized.sort(key=lambda p: len(p.parts))
        filtered: list[Path] = []
        for path in normalized:
            if not any(
                path != other and is_relative_to(path, other) for other in filtered
            ):
                filtered.append(path)

        for path in filtered:
            try:
                result = subprocess.run(
                    ["mise", "env", "--json", "--cd", str(path)],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                data = cast("dict[str, str]", json.loads(result.stdout))
                vars_to_apply.update(data)
            except subprocess.CalledProcessError as e:
                window.status_message(f"Command failed with exit code {e.returncode}")
                print(f"stderr: {e.stderr}")
                continue
            except json.JSONDecodeError as e:
                window.status_message(f"Command output was not valid JSON: {e}")
                continue

        return vars_to_apply

    def apply_env_vars(self, id: int, new_vars: "dict[str,str]"):
        changes: "list[tuple[str, str | None, str]]" = []

        for key, new_value in new_vars.items():
            old_value = os.environ.get(key)

            if old_value is None or old_value != new_value:
                action = "setting" if old_value is None else "updating"
                print(f"mise: {action} {key}")
                os.environ[key] = new_value
                changes.append((key, old_value, new_value))

        _mise_env_cache[id] = changes

    def revert_env_vars(self, id: int):
        changes = _mise_env_cache.pop(id, [])

        for key, old_value, new_value in reversed(changes):
            print(key, old_value, new_value)
            # Only revert if the value hasn't been changed by someone else
            if os.environ.get(key) == new_value:
                if old_value is None:
                    print(f"mise: deleting {key}")
                    del os.environ[key]
                else:
                    print(f"mise: restoring {key}")
                    os.environ[key] = old_value

    def on_init(self, views: "list[sublime.View]"):
        if self.is_enabled():
            windows = list({w for v in views if (w := v.window()) is not None})
            for window in windows:
                variables = self.fetch_env_vars(window)
                self.apply_env_vars(window.id(), variables)

    def on_load_project(self, window: sublime.Window):
        if self.is_enabled():
            variables = self.fetch_env_vars(window)
            self.apply_env_vars(window.id(), variables)

    def on_pre_close_project(self, window: sublime.Window):
        if self.is_enabled():
            self.revert_env_vars(window.id())
