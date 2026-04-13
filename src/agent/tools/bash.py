from collections.abc import Sequence
from pathlib import Path
import shutil
import subprocess

MAX_OUTPUT_CHARS = 50000
DEFAULT_DANGEROUS_PATTERNS = (
    "rm -rf /",
    "rm -rf",
    "sudo",
    "shutdown",
    "reboot",
    "> /dev/",
    "curl ",
    "wget ",
    "scp ",
    "ssh ",
    "powershell -enc",
    "chmod ",
)

def collect_output(stdout: str | None, stderr: str | None,
                   limit: int = MAX_OUTPUT_CHARS,
                   default: str = "(no output)") -> str:
    output = ((stdout or "") + (stderr or "")).strip()
    return output[:limit] if output else default


def run_process(args: str | Sequence[str], cwd, timeout: int,
                shell: bool = False,
                encoding: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding=encoding,
        errors="replace",
        stdin=subprocess.DEVNULL,
        timeout=timeout,
        shell=shell,
    )


def run_shell_subprocess(command: str, cwd, timeout: int) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    if bash:
        return run_process([bash, "-lc", command], cwd=cwd, timeout=timeout, encoding="utf-8")
    return run_process(command, cwd=cwd, timeout=timeout, shell=True)


def run_bash_command(command: str, cwd, timeout: int = 30,
                     dangerous_patterns=DEFAULT_DANGEROUS_PATTERNS) -> str:
    if timeout > 30:
        return "Error: Timeout exceeds the 30 second safety limit"
    if any(pattern in command for pattern in dangerous_patterns):
        return "Error: Dangerous command blocked"
    try:
        result = run_shell_subprocess(command, cwd=Path(cwd), timeout=timeout)
        return collect_output(result.stdout, result.stderr)
    except subprocess.TimeoutExpired:
        return f"Error: Timeout ({timeout}s)"
    except Exception as e:
        return f"Error: {e}"