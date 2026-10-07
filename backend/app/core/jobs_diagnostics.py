"""Value-free diagnostics for the Admin jobs request only."""
import logging
import re

# Use Uvicorn's configured INFO handler without changing global logging policy.
_logger = logging.getLogger("uvicorn.error.admin_jobs")


def jobs_point(component: str, operation: str, marker: str = "") -> None:
    # Callers pass fixed literals only, never request or database values.
    _logger.info("component=%s operation=%s%s", component, operation,
                 " " + marker if marker else "")


def _attribute(value, name):
    try:
        return getattr(value, name, None)
    except Exception:
        return None


def _class_name(value):
    name = type(value).__name__ if value is not None else "unavailable"
    return name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", name) else "unavailable"


def jobs_failure(component: str, operation: str, error: Exception) -> None:
    driver = None
    sqlstate = "unavailable"
    current = error
    # _rows retains a suppressed context when translating a SQLAlchemy error.
    # Inspect metadata only; never format exceptions, SQL, args or traceback.
    for _ in range(4):
        if current is None:
            break
        original = _attribute(current, "orig")
        if isinstance(original, BaseException):
            driver = original
        for source in (original, current):
            for key in ("sqlstate", "pgcode"):
                code = _attribute(source, key)
                if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9]{5}", code):
                    sqlstate = code
                    break
            if sqlstate != "unavailable":
                break
        if driver is not None or sqlstate != "unavailable":
            break
        current = _attribute(current, "__cause__") or _attribute(current, "__context__")
    _logger.error(
        "component=%s operation=%s exception_class=%s driver_exception_class=%s sqlstate=%s",
        component, operation, _class_name(error), _class_name(driver), sqlstate,
    )
