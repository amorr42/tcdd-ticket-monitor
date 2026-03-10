"""
Parse TCDD train-availability API response into structured train list.
Returns ALL trains with ALL cabin classes — no filtering.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
import pytz

ISTANBUL_TZ = pytz.timezone("Europe/Istanbul")


@dataclass
class CabinAvailability:
    name: str
    seats: int


@dataclass
class Train:
    train_id: str          # unique key: departure_time ISO string
    departure_time: datetime
    classes: list[CabinAvailability] = field(default_factory=list)

    @property
    def total_seats(self) -> int:
        return sum(c.seats for c in self.classes)

    @property
    def has_seats(self) -> bool:
        return self.total_seats > 0

    def seats_by_class(self) -> dict[str, int]:
        return {c.name: c.seats for c in self.classes}

    def summary(self) -> str:
        dep = self.departure_time.strftime("%H:%M")
        classes = ", ".join(
            f"{c.name}:{c.seats}" for c in self.classes if c.seats > 0
        ) or "no seats"
        return f"[{dep}] {classes}"


def parse_response(response: dict) -> list[Train]:
    """
    Parse raw API response dict into list of Train objects.
    Handles missing/malformed fields gracefully.
    """
    trains: list[Train] = []

    try:
        legs = response.get("trainLegs", [])
        if not legs:
            return trains

        availabilities = legs[0].get("trainAvailabilities", [])
        for avail in availabilities:
            for train_data in avail.get("trains", []):
                train = _parse_train(train_data)
                if train:
                    trains.append(train)
    except Exception as e:
        print(f"[parser] Error parsing response: {e}")

    return trains


def _parse_train(train_data: dict) -> Train | None:
    try:
        # Departure time (milliseconds UTC → Istanbul time)
        segments = train_data.get("segments", [])
        if not segments:
            return None
        dep_ms = segments[0].get("departureTime")
        if dep_ms is None:
            return None
        dep_utc = datetime.utcfromtimestamp(dep_ms / 1000).replace(tzinfo=pytz.utc)
        dep_local = dep_utc.astimezone(ISTANBUL_TZ)

        train_id = dep_local.isoformat()

        # All cabin classes
        classes: list[CabinAvailability] = []
        for fare_info in train_data.get("availableFareInfo", []):
            for cabin in fare_info.get("cabinClasses", []):
                name = cabin.get("cabinClass", {}).get("name", "UNKNOWN")
                seats = int(cabin.get("availabilityCount", 0))
                classes.append(CabinAvailability(name=name, seats=seats))

        return Train(train_id=train_id, departure_time=dep_local, classes=classes)

    except Exception as e:
        print(f"[parser] Error parsing single train: {e}")
        return None
