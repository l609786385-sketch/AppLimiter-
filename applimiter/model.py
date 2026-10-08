from __future__ import annotations

import ntpath
from dataclasses import dataclass, field


def canonical_path(path: str) -> str:
    # Windows paths remain comparable when the pure engine is tested on Linux.
    path = path.strip().removeprefix("\\\\?\\")
    if not ntpath.isabs(path) or not path.lower().endswith(".exe"):
        raise ValueError("请选择完整的 Windows EXE 路径")
    return ntpath.normcase(ntpath.normpath(path))


@dataclass(frozen=True)
class Rule:
    id: int
    name: str
    paths: tuple[str, ...]
    single_seconds: int
    daily_seconds: int
    enabled: bool


@dataclass(frozen=True)
class ProcessRef:
    pid: int
    created: float
    path: str

    @property
    def token(self) -> str:
        return f"{self.pid}:{self.created:.6f}"


@dataclass(frozen=True)
class Snapshot:
    processes: tuple[ProcessRef, ...] = ()
    foreground_pid: int | None = None
    complete: bool = True


@dataclass
class Session:
    seconds: float = 0.0
    tokens: set[str] = field(default_factory=set)
    warnings: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class Action:
    rule_id: int
    name: str
    reason: str
    targets: tuple[ProcessRef, ...]
