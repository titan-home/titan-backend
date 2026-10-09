"""The limit on password guessing per client address and account (decision #27)."""

import ipaddress
import math
import os
import time
from collections.abc import Callable

MAX_FAILURES = 10
WINDOW_SECONDS = 15 * 60
LOCKOUT_SECONDS = 15 * 60


class GuessingLimit:
    """Count failed sign-ins per client address and username; refuse a pair at 10.

    10 failures within 15 minutes refuse the pair for 15 minutes from the
    10th; then it starts with a clean count.

    NOTE: the count lives in this process's memory (decision #151): it holds
    for one api process, and an attacker spraying usernames grows it for up
    to two windows, fine for one node on a tailnet; move it to the database
    when the api runs as more than one process or on a cluster.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.failures: dict[tuple[str, str], list[float]] = {}
        self.refused_until: dict[tuple[str, str], float] = {}
        self.next_sweep = clock() + WINDOW_SECONDS

    def attempt(self, address: str, username: str) -> int | None:
        """Start a sign-in: None to go ahead, or the seconds the pair must wait.

        An attempt that goes ahead counts as a failure at once, until
        succeeded takes it back: counting only after the password is verified
        would let parallel attempts all pass the check meanwhile.
        """
        now = self.clock()
        self.sweep(now)
        pair = (address, username)
        until = self.refused_until.get(pair)
        if until is not None and now < until:
            return max(1, math.ceil(until - now))
        if until is not None:
            del self.refused_until[pair]
            self.failures.pop(pair, None)
        failures = [t for t in self.failures.get(pair, []) if t > now - WINDOW_SECONDS]
        failures.append(now)
        self.failures[pair] = failures
        if len(failures) >= MAX_FAILURES:
            self.refused_until[pair] = now + LOCKOUT_SECONDS
        return None

    def succeeded(self, address: str, username: str) -> None:
        """Take back the attempt of a sign-in that succeeded.

        A success does not clear the earlier failures: a guess that happened
        to be right should not open the door for ten more.
        """
        pair = (address, username)
        failures = self.failures.get(pair, [])
        if failures:
            failures.pop()
        if not failures:
            self.failures.pop(pair, None)
        if len(failures) < MAX_FAILURES:
            self.refused_until.pop(pair, None)

    def sweep(self, now: float) -> None:
        """Forget, once per window, the pairs whose failures and lockout expired."""
        if now < self.next_sweep:
            return
        self.failures = {
            pair: failures
            for pair, failures in self.failures.items()
            if failures[-1] > now - WINDOW_SECONDS
        }
        self.refused_until = {
            pair: until for pair, until in self.refused_until.items() if until > now
        }
        self.next_sweep = now + WINDOW_SECONDS


def trusted_proxies() -> list[str]:
    """Our own proxies, from TITAN_TRUSTED_PROXIES: addresses or networks.

    Only from these is X-Forwarded-For believed; empty or unset trusts none.
    """
    value = os.environ.get("TITAN_TRUSTED_PROXIES", "").strip()
    proxies = [item.strip() for item in value.split(",")] if value else []
    for proxy in proxies:
        try:
            ipaddress.ip_network(proxy)
        except ValueError:
            raise ValueError(
                f"TITAN_TRUSTED_PROXIES: {proxy!r} is not an address or network"
            ) from None
    return proxies
