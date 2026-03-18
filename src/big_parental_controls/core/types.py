"""Type definitions used across the application."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class AgeGroup(Enum):
    """Age groups for supervised users."""

    CHILD = "child"
    PRETEEN = "preteen"
    TEEN = "teen"
    YOUNG_ADULT = "young-adult"

    @property
    def label(self) -> str:
        labels = {
            AgeGroup.CHILD: "Child (< 10)",
            AgeGroup.PRETEEN: "Pre-teen (10-12)",
            AgeGroup.TEEN: "Teen (13-17)",
            AgeGroup.YOUNG_ADULT: "Young adult (16-17)",
        }
        return labels[self]


@dataclass(frozen=True)
class TimeRange:
    """A single allowed time range within a day."""

    start_hour: int
    start_min: int
    end_hour: int
    end_min: int

    @property
    def start_total_minutes(self) -> int:
        return self.start_hour * 60 + self.start_min

    @property
    def end_total_minutes(self) -> int:
        return self.end_hour * 60 + self.end_min

    def is_valid(self) -> bool:
        return self.end_total_minutes > self.start_total_minutes

    def to_dict(self) -> dict[str, int]:
        return {
            "start_hour": self.start_hour,
            "start_min": self.start_min,
            "end_hour": self.end_hour,
            "end_min": self.end_min,
        }

    @classmethod
    def from_dict(cls, data: dict[str, int]) -> TimeRange:
        return cls(
            start_hour=data.get("start_hour", 8),
            start_min=data.get("start_min", 0),
            end_hour=data.get("end_hour", 22),
            end_min=data.get("end_min", 0),
        )


@dataclass
class UserSchedule:
    """Schedule configuration for a supervised user."""

    ranges: list[TimeRange] = field(default_factory=list)
    days: list[str] | None = None
    daily_minutes: int = 0


@dataclass(frozen=True)
class DnsConfig:
    """DNS configuration for a supervised user."""

    provider: str
    dns1: str
    dns2: str

    def to_dict(self) -> dict[str, str]:
        return {"provider": self.provider, "dns1": self.dns1, "dns2": self.dns2}

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> DnsConfig:
        return cls(
            provider=data["provider"],
            dns1=data["dns1"],
            dns2=data["dns2"],
        )
