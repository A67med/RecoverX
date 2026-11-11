"""One recovery worker per server; UI reruns only observe its state.

Case-level OS locks additionally protect against duplicate work from other processes.
Worker threads never call Streamlit. A process restart releases OS locks; active_run.json
retains the last checkpoint, but interrupted tool outputs are never resumed or mixed.
"""
from __future__ import annotations
import threading
from dataclasses import dataclass, field
from typing import Any
from .orchestrator import run_recovery
from ..exceptions import RecoverXError


@dataclass
class RecoveryJob:
    case_id: str
    cancel: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    events: list[dict] = field(default_factory=list)
    result: dict | None = None
    error: str | None = None

    def progress(self, event):
        with self.lock:
            self.events.append(event)
            self.events[:] = self.events[-100:]

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {"case_id": self.case_id, "done": self.done.is_set(), "events": list(self.events),
                    "result": self.result, "error": self.error, "cancelling": self.cancel.is_set()}


_guard = threading.Lock()
_current: RecoveryJob | None = None


def current_job() -> RecoveryJob | None:
    return _current


def start_recovery(case, method, **kwargs) -> RecoveryJob:
    global _current
    with _guard:
        if _current and not _current.done.is_set():
            raise RecoverXError("A recovery is already running on this server")
        job = RecoveryJob(case.id)
        _current = job

        def work():
            try:
                job.result = run_recovery(case, method, cancel_event=job.cancel,
                                          progress=job.progress, **kwargs)
            except Exception as exc:
                job.error = f"{type(exc).__name__}: {exc}"
            finally:
                job.done.set()
        threading.Thread(target=work, name=f"recoverx-{case.id}", daemon=True).start()
        return job
