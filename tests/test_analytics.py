"""Tests for time-weighted occupancy analytics in memory mode.

The same logic backs the Postgres SQL, but the Postgres path needs a live
DB to exercise. The memory-mode implementation is the source of truth for
verifying that intervals are computed correctly.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from backend.services.database import Database


def _seed(db: Database, camera_id: str, events: list[tuple[str, datetime, bool]]) -> None:
    for slot_id, event_time, occupied in events:
        db._events.append(
            {
                "camera_id": camera_id,
                "slot_id": slot_id,
                "occupied": occupied,
                "confidence": 1.0,
                "event_time": event_time,
            }
        )


@pytest.fixture
def db():
    # Skip the real connect() path so this test works regardless of whether
    # the "DATABASE_URL=memory" opt-in (issue #10) is in this branch yet.
    database = Database()
    database.memory_mode = True
    return database


def test_history_credits_long_occupied_period_to_every_hour(db):
    """A single occupied event that lasts 5 hours must contribute to all 5 hours."""
    base = datetime(2026, 6, 17, 10, 0, 0, tzinfo=UTC)
    # Slot A1: becomes occupied at 10:00, vacated at 15:00 -> 5 hours occupied.
    _seed(
        db,
        "cam1",
        [
            ("A1", base, True),
            ("A1", base + timedelta(hours=5), False),
        ],
    )

    rows = asyncio.run(db.history("cam1", hours=12))
    # We expect five buckets — 10:00 through 14:00 — each with 3600s occupied
    # and 3600s total (slot was tracked the whole time).
    occupied_buckets = {
        row["bucket"]: row for row in rows if row["occupied_seconds"] > 0
    }
    assert len(occupied_buckets) == 5
    for hour in range(10, 15):
        key = base.replace(hour=hour).isoformat()
        assert key in occupied_buckets, f"missing bucket {key}"
        bucket = occupied_buckets[key]
        assert bucket["occupied_seconds"] == 3600.0
        assert bucket["total_seconds"] == 3600.0
        assert bucket["occupancy_pct"] == 100.0


def test_history_mixed_intervals_split_correctly(db):
    """A slot that flips state at :30 produces half-hour chunks per bucket."""
    base = datetime(2026, 6, 17, 9, 0, 0, tzinfo=UTC)
    _seed(
        db,
        "cam1",
        [
            ("A1", base, True),                         # 09:00 occupied
            ("A1", base + timedelta(minutes=30), False),# 09:30 vacated
            ("A1", base + timedelta(hours=1), True),    # 10:00 occupied again
            ("A1", base + timedelta(hours=1, minutes=30), False),  # 10:30 vacated
        ],
    )

    rows = asyncio.run(db.history("cam1", hours=12))
    by_bucket = {row["bucket"]: row for row in rows}

    nine = base.isoformat()
    ten = (base + timedelta(hours=1)).isoformat()

    assert by_bucket[nine]["occupied_seconds"] == 1800.0  # 09:00-09:30
    assert by_bucket[nine]["total_seconds"] == 3600.0      # 09:00-10:00 covered
    assert by_bucket[nine]["occupancy_pct"] == 50.0

    assert by_bucket[ten]["occupied_seconds"] == 1800.0    # 10:00-10:30
    assert by_bucket[ten]["total_seconds"] == 3600.0
    assert by_bucket[ten]["occupancy_pct"] == 50.0


def test_history_does_not_leak_old_occupied_intervals_into_window(db):
    """An occupied interval that ended before the window starts must not
    contribute occupied seconds to any bucket inside the window."""
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    # The occupied stretch is between -30h and -29h, fully outside the 24h window.
    # (The trailing "free" interval after -29h does run into the window, which
    # is intentional — the slot's known continuous state — but it must show 0%.)
    _seed(
        db,
        "cam1",
        [
            ("A1", now - timedelta(hours=30), True),
            ("A1", now - timedelta(hours=29), False),
        ],
    )
    rows = asyncio.run(db.history("cam1", hours=24))
    assert all(row["occupied_seconds"] == 0.0 for row in rows)
    assert all(row["occupancy_pct"] == 0.0 for row in rows)


def test_peak_hours_sorts_by_occupied_seconds(db):
    """peak_hours surfaces the busiest hour of day by occupied time, not event count."""
    base = datetime(2026, 6, 17, 8, 0, 0, tzinfo=UTC)
    # Hour 8: lots of brief flips -> many events, ~1800 occupied seconds.
    flips = [base + timedelta(minutes=m) for m in range(0, 60, 5)]
    for index, event_time in enumerate(flips):
        _seed(db, "cam1", [("A1", event_time, index % 2 == 0)])
    # Hour 12: one long occupied period -> few events, 3600 occupied seconds.
    _seed(
        db,
        "cam1",
        [
            ("A2", base.replace(hour=12), True),
            ("A2", base.replace(hour=13), False),
        ],
    )

    rows = asyncio.run(db.peak_hours("cam1"))
    assert rows, "expected at least one peak hour row"
    top = rows[0]
    # Hour 12 (the single long occupied interval) must rank ahead of hour 8
    # (lots of events but only ~half the seconds), demonstrating that ranking
    # by occupied SECONDS — not event counts — gives the right answer.
    assert top["hour"] == 12
    assert top["occupied_seconds"] == 3600.0
