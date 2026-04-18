from dataclasses import dataclass
from typing import Optional


@dataclass
class SearchConfig:
    enabled: bool
    force_run_once: bool
    origin: str
    destination: str
    travel_date: str
    preferred_time_start: str
    preferred_time_end: str
    adult_count: int = 1
    child_count: int = 0
    headless: bool = True
    timeout_ms: int = 60000
    screenshot_on_error: str = "ktmb_error.png"
    screenshot_on_result: Optional[str] = "ktmb_result.png"
    min_seats: int = 1


@dataclass
class TrainOption:
    label: str
    available: bool
    seats: int = 0
    departure_code: str = ""
    departure_time: str = ""


@dataclass
class CheckResult:
    success: bool
    available: bool
    matched_trains: list[TrainOption]
    message: str