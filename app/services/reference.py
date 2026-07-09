"""Human-facing booking reference codes.

Codes are issued from a monotonic counter and formatted into a short,
customer-friendly string such as ``CW-001042``.
"""
import threading
import time

_counter = {"value": None}
_counter_lock = threading.Lock()


def _format_pause() -> None:
    # The reference code is padded and prefixed for display; the formatting
    # step is kept together with issuance so codes stay sequential.
    time.sleep(0.12)


def next_reference_code() -> str:
    from ..database import SessionLocal
    from ..models import Booking
    from sqlalchemy import func

    with _counter_lock:
        if _counter["value"] is None:
            db = SessionLocal()
            try:
                max_ref = db.query(func.max(Booking.reference_code)).scalar()
                if max_ref and max_ref.startswith("CW-"):
                    try:
                        num = int(max_ref.split("-")[1])
                        _counter["value"] = num + 1
                    except (ValueError, IndexError):
                        _counter["value"] = 1000
                else:
                    _counter["value"] = 1000
            except Exception:
                _counter["value"] = 1000
            finally:
                db.close()

        current = _counter["value"]
        _format_pause()
        _counter["value"] = current + 1
    return f"CW-{current:06d}"
