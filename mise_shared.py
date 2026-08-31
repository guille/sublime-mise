import json
import subprocess
from typing import Any

import sublime

SUBPROCESS_TIMEOUT = 10  # seconds
# Windows-only flag to avoid a console window flash; 0 elsewhere
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run_mise_json(
    cmd: "list[str]", cwd: str, window: sublime.Window, quiet: bool = False
) -> "Any | None":
    """Run a mise command and parse its JSON stdout.

    Reports failures to the window's status bar and returns None, unless
    `quiet` is set, in which case failures are silent (useful when the
    caller has a fallback for an optional facility that may not exist).
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
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        if not quiet:
            window.status_message(f"Command failed with exit code {e.returncode}")
            print(f"stderr: {e.stderr}")
    except subprocess.TimeoutExpired:
        if not quiet:
            window.status_message(
                f"{' '.join(cmd[:2])} timed out after {SUBPROCESS_TIMEOUT}s in {cwd}"
            )
    except json.JSONDecodeError as e:
        if not quiet:
            window.status_message(f"Command output was not valid JSON: {e}")
    except OSError as e:
        # Most often mise missing from Sublime's PATH.
        if not quiet:
            window.status_message(f"Could not run {cmd[0]}: {e}")
    return None
