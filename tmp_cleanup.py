import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Union


DEFAULT_AT_WHEN = "17:00 tomorrow"
DISABLE_ENV_VAR = "POPIT3_DISABLE_AT_CLEANUP"


PathLike = Union[str, os.PathLike]


def _as_paths(paths: Union[PathLike, Sequence[PathLike]]) -> List[Path]:
    if isinstance(paths, (str, os.PathLike)):
        paths = [paths]
    return [Path(p).expanduser().resolve() for p in paths]


def _validate_tmp_prefix(path: Path) -> None:
    if not path.name.startswith("tmp_"):
        raise ValueError(f"Refusing to schedule cleanup for non tmp_ file: {path}")


def schedule_tmp_cleanup(
    paths: Union[PathLike, Sequence[PathLike]],
    *,
    when: str = DEFAULT_AT_WHEN,
    allow_missing: bool = False,
) -> Optional[str]:
    """Schedule deletion of one or more temp files via `at`.

    Safety rules:
    - Only files whose basename starts with `tmp_` are accepted.
    - Paths are resolved to absolute paths.

    Returns the `at` command output on success, None if disabled or `at` missing.
    """

    if os.environ.get(DISABLE_ENV_VAR):
        return None

    if shutil.which("at") is None:
        return None

    resolved_paths = _as_paths(paths)
    for path in resolved_paths:
        _validate_tmp_prefix(path)
        if not allow_missing and not path.exists():
            raise FileNotFoundError(path)

    at_args = ["at", *shlex.split(when)]
    script_lines = [
        "set -e",
        *(f"rm -f -- {shlex.quote(str(p))}" for p in resolved_paths),
        "",
    ]
    proc = subprocess.run(
        at_args,
        input="\n".join(script_lines),
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"at failed ({proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}")

    return (proc.stdout + proc.stderr).strip() or "scheduled"
