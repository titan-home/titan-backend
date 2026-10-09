"""Tests for the limit on password guessing per client address and account."""

import pytest

from titan_api.app import create_app
from titan_api.guessing import GuessingLimit, trusted_proxies


class Clock:
    """A clock the test moves by hand, in seconds."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def fail(limit: GuessingLimit, times: int, username: str = "owner") -> None:
    for _ in range(times):
        assert limit.attempt("203.0.113.5", username) is None


def test_ten_failures_refuse_the_pair_for_15_minutes_from_the_tenth() -> None:
    """Accounts spec, guessing limit 1 and 3: refused, with the seconds to wait."""
    clock = Clock()
    limit = GuessingLimit(clock)
    fail(limit, 9)
    clock.now += 14 * 60
    fail(limit, 1)

    clock.now += 2 * 60
    assert limit.attempt("203.0.113.5", "owner") == 13 * 60
    clock.now += 13 * 60 - 0.5
    assert limit.attempt("203.0.113.5", "owner") == 1
    clock.now += 0.5
    assert limit.attempt("203.0.113.5", "owner") is None


def test_after_the_lockout_the_pair_starts_with_a_clean_count() -> None:
    """Decision #27: the pair is refused for 15 minutes, then counts from zero."""
    clock = Clock()
    limit = GuessingLimit(clock)
    fail(limit, 10)
    clock.now += 15 * 60

    fail(limit, 9)

    assert limit.attempt("203.0.113.5", "owner") is None


def test_a_tenth_attempt_that_succeeds_does_not_lock_the_pair() -> None:
    """Accounts spec, sign in 3: only failed attempts count towards the limit."""
    limit = GuessingLimit(Clock())
    fail(limit, 10)
    limit.succeeded("203.0.113.5", "owner")

    assert limit.attempt("203.0.113.5", "owner") is None


def test_an_attempt_counts_before_its_outcome_is_known() -> None:
    """Parallel attempts cannot all pass the check before the first one fails."""
    limit = GuessingLimit(Clock())
    fail(limit, 10)

    assert limit.attempt("203.0.113.5", "owner") == 900


def test_a_success_does_not_count_as_a_failure() -> None:
    """Accounts spec, sign in 3: only failed attempts count towards the limit."""
    limit = GuessingLimit(Clock())
    for _ in range(20):
        assert limit.attempt("203.0.113.5", "owner") is None
        limit.succeeded("203.0.113.5", "owner")


def test_failures_older_than_the_window_do_not_count() -> None:
    """Accounts spec, guessing limit 1: only failures within 15 minutes count."""
    clock = Clock()
    limit = GuessingLimit(clock)
    fail(limit, 9)
    clock.now += 15 * 60
    fail(limit, 1)

    assert limit.attempt("203.0.113.5", "owner") is None


def test_pairs_are_counted_apart() -> None:
    """Accounts spec, guessing limit 1: only that pair is refused."""
    limit = GuessingLimit(Clock())
    fail(limit, 10)

    assert limit.attempt("203.0.113.6", "owner") is None
    assert limit.attempt("203.0.113.5", "other") is None


def test_a_pair_whose_failures_all_expired_is_forgotten() -> None:
    clock = Clock()
    limit = GuessingLimit(clock)
    fail(limit, 10, "sprayed")
    clock.now += 15 * 60

    fail(limit, 1)

    assert ("203.0.113.5", "sprayed") not in limit.failures
    assert ("203.0.113.5", "sprayed") not in limit.refused_until
    assert ("203.0.113.5", "owner") in limit.failures


def test_a_success_that_leaves_no_failures_forgets_the_pair() -> None:
    limit = GuessingLimit(Clock())
    fail(limit, 1)
    limit.succeeded("203.0.113.5", "owner")

    assert limit.failures == {}


def test_trusted_proxies_are_read_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accounts spec, guessing limit 2: a configured list of our own proxies."""
    monkeypatch.delenv("TITAN_TRUSTED_PROXIES", raising=False)
    assert trusted_proxies() == []
    monkeypatch.setenv("TITAN_TRUSTED_PROXIES", "")
    assert trusted_proxies() == []
    monkeypatch.setenv("TITAN_TRUSTED_PROXIES", " 172.18.0.0/16, 10.0.0.2 ,fd00::/8")
    assert trusted_proxies() == ["172.18.0.0/16", "10.0.0.2", "fd00::/8"]


@pytest.mark.parametrize("value", ["nginx", "*", "10.0.0.1/8", "10.0.0.2,,"])
def test_an_invalid_trusted_proxy_stops_the_api_from_starting(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    # A typo would otherwise trust nobody, silently, and every user would
    # share the proxy's address; "*" would trust everybody.
    monkeypatch.setenv("TITAN_TRUSTED_PROXIES", value)

    with pytest.raises(ValueError, match="TITAN_TRUSTED_PROXIES"):
        create_app()
