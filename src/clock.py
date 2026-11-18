from datetime import datetime, timedelta


class SystemClock:
    """The real time. Used in production."""

    def now(self):
        return datetime.now()


class FakeClock:
    """A clock the tests control, to simulate maintenance windows and time changes."""

    def __init__(self, start):
        self._now = start

    def now(self):
        return self._now

    def set(self, moment):
        self._now = moment

    def advance(self, **kwargs):
        self._now += timedelta(**kwargs)


def in_time_window(now_time, start, end):
    """True if now_time is inside [start, end). Works for windows that cross midnight."""
    if start <= end:
        return start <= now_time < end
    return now_time >= start or now_time < end