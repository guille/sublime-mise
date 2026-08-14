import os
from pathlib import Path
from typing import Any, cast

import sublime
import sublime_plugin

from .mise_shared import run_mise_json

MISE_KEYFILES = ("mise.toml", "mise.local.toml")


# Python 3.9
def is_relative_to(path: Path, other: Path):
    try:
        path.relative_to(other)
        return True
    except ValueError:
        return False


def upglob(start: Path) -> "Path | None":
    current = start.resolve()
    if not current.is_dir():  # handles files deleted from disk too
        current = current.parent

    try:
        current_dev = os.stat(current).st_dev
    except OSError:
        return None
    home = Path.home().resolve()

    # Determine the ceiling: $HOME if we start at/below it, else filesystem root
    try:
        current.relative_to(home)
        ceiling = home
    except ValueError:
        ceiling = None  # No ceiling — walk all the way to root

    while True:
        for marker in MISE_KEYFILES:
            if (current / marker).exists():
                return current
        if current == ceiling:
            return None  # Hit $HOME without finding the marker
        parent = current.parent
        if parent == current:
            return None
        try:
            if os.stat(parent).st_dev != current_dev:
                return None  # Stop at filesystem boundary
        except OSError:
            return None
        current = parent


_mise_env_cache: "dict[int, list[tuple[str, str | None, str]]]" = {}


class MiseEnvListener(sublime_plugin.EventListener):
    def _is_enabled(self) -> bool:
        settings = sublime.load_settings("Mise.sublime-settings")
        return settings.get("load_env_in_projects", False) is True

    def _has_keyfiles(self, path: Path) -> bool:
        return any((path / name).exists() for name in MISE_KEYFILES)

    def _project_folders_with_keyfiles(self, window: sublime.Window) -> "list[Path]":
        proj_file = window.project_file_name()
        if proj_file is None:
            project_path = None
        else:
            project_path = Path(proj_file).parent

        project_data = cast("dict[str, Any] | None", window.project_data())
        if project_data is None:
            return []

        folders = project_data.get("folders", [])

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
        return normalized

    def fetch_env_vars(self, window: sublime.Window) -> "dict[str,str]":
        normalized = self._project_folders_with_keyfiles(window)
        if not normalized:
            return {}

        # Sort by path depth so parents are always checked before children.
        normalized.sort(key=lambda p: len(p.parts))

        vars_to_apply: "dict[str,str]" = {}
        vars_to_skip = cast(
            "list[str]",
            sublime.load_settings("Mise.sublime-settings").get(
                "vars_to_exclude_from_autoloading", []
            ),
        )

        for path in normalized:
            data = run_mise_json(["mise", "env", "--json"], str(path), window)
            if data is None:
                continue
            for k, v in cast("dict[str, str]", data).items():
                if k not in vars_to_skip:
                    vars_to_apply.setdefault(k, v)

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
            # Only revert if the value hasn't been changed by someone else
            if os.environ.get(key) == new_value:
                if old_value is None:
                    print(f"mise: deleting {key}")
                    del os.environ[key]
                else:
                    print(f"mise: restoring {key}")
                    os.environ[key] = old_value

    def on_init(
        self,
        views: "list[sublime.View]",  # pyright: ignore[reportUnusedParameter]
    ):
        if self._is_enabled():
            # sublime.windows() instead of the views' windows: a project
            # window with no open files has no views
            for window in sublime.windows():
                variables = self.fetch_env_vars(window)
                self.apply_env_vars(window.id(), variables)

    def on_load_project(self, window: sublime.Window):
        if self._is_enabled():
            # Revert first so a reload doesn't orphan previous changes
            self.revert_env_vars(window.id())
            variables = self.fetch_env_vars(window)
            self.apply_env_vars(window.id(), variables)

    def on_pre_close_project(self, window: sublime.Window):
        if self._is_enabled():
            self.revert_env_vars(window.id())

    def _eval_ctx(
        self, found: bool, operator: sublime.QueryOperator, operand: bool
    ) -> "bool | None":
        if operator == sublime.OP_EQUAL:
            return found == operand
        elif operator == sublime.OP_NOT_EQUAL:
            return found != operand
        else:
            return None  # I'm not bothering with OP_REGEX_MATCH et al

    def handle_ctx_upglob_has_keyfile(
        self,
        view: sublime.View,
        operator: sublime.QueryOperator,
        operand: bool,
    ) -> "bool | None":
        file = view.file_name()

        if file is None and (window := view.window()):
            file = window.extract_variables().get("file")

        found = bool(file and upglob(Path(file)))
        return self._eval_ctx(found, operator, operand)

    def handle_ctx_project_has_keyfile(
        self,
        view: sublime.View,
        operator: sublime.QueryOperator,
        operand: bool,
    ) -> "bool | None":
        window = view.window()
        found = window is not None and bool(self._project_folders_with_keyfiles(window))
        return self._eval_ctx(found, operator, operand)

    def on_query_context(
        self,
        view: sublime.View,
        key: str,
        operator: sublime.QueryOperator,
        operand: "sublime.Value",
        match_all: bool,  # pyright: ignore[reportUnusedParameter]
    ) -> "bool | None":
        if not isinstance(operand, bool):
            return None

        if key == "mise.upglob_has_keyfile":
            return self.handle_ctx_upglob_has_keyfile(view, operator, operand)
        if key == "mise.project_has_keyfile":
            return self.handle_ctx_project_has_keyfile(view, operator, operand)

        return None
