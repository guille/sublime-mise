import json
import shlex
import subprocess
from typing import Any, NamedTuple

SUBPROCESS_TIMEOUT = 10  # seconds
# Windows-only flag to avoid a console window flash; 0 elsewhere
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class MiseJson(NamedTuple):
    data: "Any | None"
    error: "str | None"
    stderr: str = ""


def split_args(text: str) -> "list[str]":
    """
    Split typed arguments into argv, keeping quoted runs together
    (e.g. --name="two words" -> ["--name=two words"]).

    Only double quotes are treated as quoting so a bare apostrophe
    ("don't") and Windows path backslashes pass through untouched;
    posix mode's default escape char would otherwise eat backslashes.

    Raises ValueError if a quote is left open.
    """
    lexer = shlex.shlex(text, posix=True)
    lexer.whitespace_split = True
    lexer.quotes = '"'
    lexer.escape = ""
    return list(lexer)


def run_mise_json(cmd: "list[str]", cwd: str) -> MiseJson:
    """Run a mise command and parse its JSON stdout.

    Returns the parsed data, or an error message fit for the status bar.
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            timeout=SUBPROCESS_TIMEOUT,
            creationflags=CREATE_NO_WINDOW,
        )
        return MiseJson(json.loads(result.stdout), None)
    except subprocess.CalledProcessError as e:
        return MiseJson(None, f"Command failed with exit code {e.returncode}", e.stderr)
    except subprocess.TimeoutExpired:
        return MiseJson(
            None, f"{' '.join(cmd[:2])} timed out after {SUBPROCESS_TIMEOUT}s in {cwd}"
        )
    except json.JSONDecodeError as e:
        return MiseJson(None, f"Command output was not valid JSON: {e}")
    except OSError as e:
        # Most often mise missing from Sublime's PATH.
        return MiseJson(None, f"Could not run {cmd[0]}: {e}")
