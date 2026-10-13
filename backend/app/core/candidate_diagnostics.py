"""Temporary, value-free diagnostics scoped to candidate-list requests."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import logging
import re
from time import monotonic

from app.core.jobs_diagnostics import _attribute, _class_name

_logger = logging.getLogger("uvicorn.error.admin_candidates")
_active = ContextVar("candidate_diagnostics", default=False)
_reasons = {"timeout", "connection", "http", "contract", "identity_mismatch", "unavailable"}


def point(stage, **counts):
    if not _active.get():
        return
    # Callers supply fixed stages; only explicitly allowed numeric fields survive.
    fields = {k: v for k, v in counts.items()
              if k in {"count", "request_count", "response_count", "matched_count", "http_status"}
              and type(v) is int and v >= 0}
    _logger.info("stage=%s%s", stage, "".join(f" {k}={v}" for k, v in fields.items()))


def failure(stage, error, elapsed):
    current = error
    reason, sqlstate, cause_class = "unavailable", "unavailable", "unavailable"
    for _ in range(8):
        if current is None:
            break
        cause_class = _class_name(current)
        category = _attribute(current, "reason_category")
        if isinstance(category, str) and category in _reasons:
            reason = category
        for source in (current, _attribute(current, "orig")):
            code = _attribute(source, "sqlstate") or _attribute(source, "pgcode")
            if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9]{5}", code):
                sqlstate = code
        current = (_attribute(current, "orig") or _attribute(current, "__cause__")
                   or _attribute(current, "__context__"))
    _logger.error("stage=%s elapsed_ms=%.1f exception_class=%s cause_class=%s reason_category=%s sqlstate=%s",
                  stage, elapsed, _class_name(error), cause_class, reason, sqlstate)


@contextmanager
def span(stage):
    if not _active.get():
        yield
        return
    start = monotonic()
    point(stage + "_start")
    try:
        yield
    except Exception as error:
        failure(stage + "_failed", error, (monotonic() - start) * 1000)
        raise
    else:
        _logger.info("stage=%s_complete elapsed_ms=%.1f", stage, (monotonic() - start) * 1000)


def candidate_request(function):
    @wraps(function)
    async def wrapped(*args, **kwargs):
        token = _active.set(True)
        try:
            with span("list_candidates"):
                return await function(*args, **kwargs)
        finally:
            _active.reset(token)
    return wrapped
