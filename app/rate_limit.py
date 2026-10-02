"""
Brute-force protection for the admin login endpoint.

Before this, `/api/admin/login` answered an unlimited number of guesses at
full speed, so a public deployment's admin panel was one wordlist away from
being open. Failed attempts are now counted in a sliding window and locked
out once they pass a threshold.

Scope, stated plainly: the counters live in this process's memory. Under
several gunicorn workers each worker holds its own, so the effective limit
is `MAX_FAILURES` times the worker count, and a restart clears everything.
That is a real weakening, but it still turns an unbounded guess rate into a
few dozen tries per window — enough for a demo. A deployment that needs a
hard guarantee should move these counters into Redis (or put the limit in
front of the app, at the reverse proxy), which is why all the state lives
behind the three functions below rather than being read directly.
"""

import threading
import time

# Five wrong passwords is well past a typo and well short of a search.
MAX_FAILURES = 5

# How long the counter remembers a failure, and how long a lockout lasts.
WINDOW_SECONDS = 15 * 60

_lock = threading.Lock()

# key -> list of monotonic timestamps of recent failures.
_failures = {}


def _prune(timestamps, now):
    """Drop the failures that have aged out of the window."""
    cutoff = now - WINDOW_SECONDS
    return [t for t in timestamps if t > cutoff]


def check(key):
    """
    Report whether `key` is currently locked out.

    Returns `(allowed, retry_after_seconds)`. `retry_after_seconds` is 0
    when allowed, and otherwise the whole seconds until the oldest failure
    in the window expires — which is when the caller gets another attempt.
    """
    now = time.monotonic()
    with _lock:
        timestamps = _prune(_failures.get(key, []), now)
        if timestamps:
            _failures[key] = timestamps
        else:
            # Don't let keys that have aged out accumulate forever; a login
            # endpoint is a public surface and the key includes client IP.
            _failures.pop(key, None)

        if len(timestamps) < MAX_FAILURES:
            return True, 0

        retry_after = int(timestamps[0] + WINDOW_SECONDS - now) + 1
        return False, max(retry_after, 1)


def record_failure(key):
    """Count one failed attempt against `key`."""
    now = time.monotonic()
    with _lock:
        timestamps = _prune(_failures.get(key, []), now)
        timestamps.append(now)
        _failures[key] = timestamps


def clear(key):
    """
    Forget `key`'s failures — called after a successful login, so somebody
    who mistyped their password four times and then got it right isn't left
    one slip away from a lockout.
    """
    with _lock:
        _failures.pop(key, None)


def reset_all():
    """Drop every counter. For tests, which must not leak state into each other."""
    with _lock:
        _failures.clear()
