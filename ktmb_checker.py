"""
KTMB Shuttle ticket availability checker
----------------------------------------
What this script does:
1. Opens the KTMB ShuttleTrip page
2. Fills in trip details
3. Submits the search
4. Checks whether tickets appear available
5. Prints structured output
6. Optionally saves a screenshot on failure

Install:
    pip install playwright
    playwright install

Run:
    python ktmb_checker.py
"""


import json
import os
from dataclasses import asdict
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from config_models import SearchConfig, CheckResult, TrainOption
from storage import (
    load_config_dict,
    load_runtime_status,
    save_runtime_status,
    load_alert_state,
    save_alert_state,
)
from lock import try_acquire_lock, release_lock, new_lock_owner
from telegram import send_telegram
from parser import is_time_in_range


URL = "https://shuttleonline.ktmb.com.my/Home/Shuttle"


SELECTORS = {
    "origin_input": "#FromStationId",
    "destination_input": "#ToStationId",
    "swap_button": 'i[onclick="SwapFromToTerminal()"]:visible',
    "date_input": "#OnwardDate",   # verify
    "calendar_days_container": ".lightpick__days",
    "calendar_month_select": ".lightpick__select-months",
    "calendar_year_select": ".lightpick__select-years",
    "calendar_day_available": ".lightpick__day.is-available",
    "calendar_next_month": ".lightpick__next-action",       # still verify
    "calendar_prev_month": ".lightpick__previous-action",   # still verify
    "adult_input": "#PassengerCount",       # verify
    "search_button": '#btnSubmit',
    "results_container": "tbody.depart-trips",
    "train_rows": "tbody.depart-trips > tr",
    "no_results_text": 'text=/no trips|no seats|not available|sold out/i',
}


MONTH_NAME_TO_NUM = {
    "January": 1, "February": 2, "March": 3, "April": 4,
    "May": 5, "June": 6, "July": 7, "August": 8,
    "September": 9, "October": 10, "November": 11, "December": 12,
}



def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_config() -> SearchConfig:
    raw = load_config_dict()
    return SearchConfig(
        enabled=raw.get("enabled", True),
        origin=raw["origin"],
        destination=raw["destination"],
        travel_date=raw["travel_date"],
        preferred_time_start=raw["preferred_time_start"],
        preferred_time_end=raw["preferred_time_end"],
        adult_count=raw.get("adult_count", 1),
        child_count=raw.get("child_count", 0),
        headless=raw.get("headless", True),
        timeout_ms=raw.get("timeout_ms", 60000),
        screenshot_on_error=raw.get("screenshot_on_error", "ktmb_error.png"),
        screenshot_on_result=raw.get("screenshot_on_result", "ktmb_result.png"),
        min_seats=raw.get("min_seats", 1),
    )


def get_visible_calendar_month_year(page) -> tuple[int, int]:
    month_select = page.locator(SELECTORS["calendar_month_select"])
    year_select = page.locator(SELECTORS["calendar_year_select"])
    visible_month_name = month_select.locator("option[selected='selected']").inner_text().strip()
    visible_year = int(year_select.locator("option[selected='selected']").inner_text().strip())
    return MONTH_NAME_TO_NUM[visible_month_name], visible_year


def select_departure_date(page, input_selector: str, date_str: str) -> None:
    from datetime import datetime

    target = datetime.strptime(date_str, "%Y-%m-%d")
    target_day = str(target.day)

    field = page.locator(input_selector)
    field.wait_for(state="visible", timeout=10000)
    field.click()
    page.locator(SELECTORS["calendar_days_container"]).wait_for(state="visible", timeout=10000)

    for _ in range(24):
        visible_month, visible_year = get_visible_calendar_month_year(page)

        if visible_month == target.month and visible_year == target.year:
            day_locator = page.locator(
                f'{SELECTORS["calendar_day_available"]}:not(.is-previous-month):not(.is-next-month)',
                has_text=target_day,
            )
            if day_locator.count() == 0:
                raise ValueError(f"Day {target_day} not selectable for {date_str}")
            day_locator.first.click()
            return

        visible_key = (visible_year, visible_month)
        target_key = (target.year, target.month)

        if visible_key < target_key:
            page.locator(SELECTORS["calendar_next_month"]).click()
        else:
            page.locator(SELECTORS["calendar_prev_month"]).click()

        page.wait_for_timeout(250)

    raise ValueError(f"Could not navigate calendar to {date_str}")


def maybe_swap_stations(page, desired_origin: str, desired_destination: str) -> None:
    origin_value = (page.locator(SELECTORS["origin_input"]).input_value() or "").strip().upper()
    destination_value = (page.locator(SELECTORS["destination_input"]).input_value() or "").strip().upper()

    desired_origin = desired_origin.strip().upper()
    desired_destination = desired_destination.strip().upper()

    if origin_value == desired_origin and destination_value == desired_destination:
        return

    if origin_value == desired_destination and destination_value == desired_origin:
        page.locator(SELECTORS["swap_button"]).first.click()
        page.wait_for_timeout(1000)
        return

    raise ValueError(
        f"Unexpected route on page: origin={origin_value}, destination={destination_value}"
    )


def detect_availability(page, config: SearchConfig) -> CheckResult:
    matched_trains: list[TrainOption] = []

    try:
        page.locator(SELECTORS["results_container"]).wait_for(state="visible", timeout=15000)
    except PlaywrightTimeoutError:
        return CheckResult(False, False, [], "Could not find departure results table.")

    rows = page.locator(SELECTORS["train_rows"])
    any_available = False

    for i in range(rows.count()):
        row = rows.nth(i)
        departure_code = (row.get_attribute("data-hourminute") or "").strip()

        if not departure_code or not is_time_in_range(
            departure_code,
            config.preferred_time_start,
            config.preferred_time_end,
        ):
            continue

        cells = row.locator("td")
        if cells.count() < 7:
            continue

        train_name = cells.nth(0).inner_text().strip()
        depart_time = cells.nth(1).inner_text().strip()
        seats_text = cells.nth(4).inner_text().strip()
        digits_only = "".join(ch for ch in seats_text if ch.isdigit())
        seats = int(digits_only) if digits_only else 0

        row_classes = (row.get_attribute("class") or "").lower()
        is_disabled = "disabled" in row_classes
        available = (not is_disabled) and seats >= config.min_seats

        any_available = any_available or available
        matched_trains.append(
            TrainOption(
                label=f"{train_name} {depart_time}",
                available=available,
                seats=seats,
                departure_code=departure_code,
                departure_time=depart_time,
            )
        )

    return CheckResult(True, any_available, matched_trains, "Checked preferred departure time range.")


def run_check(config: SearchConfig) -> CheckResult:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=config.headless)
        page = browser.new_page()
        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=config.timeout_ms)
            page.wait_for_load_state("networkidle", timeout=15000)

            maybe_swap_stations(page, config.origin, config.destination)
            select_departure_date(page, SELECTORS["date_input"], config.travel_date)

            page.locator(SELECTORS["search_button"]).click()
            page.wait_for_load_state("networkidle", timeout=20000)

            return detect_availability(page, config)
        finally:
            browser.close()


def build_availability_key(config: SearchConfig, available_trains: list[TrainOption]) -> str:
    times = sorted(t.departure_code for t in available_trains)
    return (
        f"{config.travel_date}|{config.origin}|{config.destination}|"
        f"{config.preferred_time_start}-{config.preferred_time_end}|{','.join(times)}"
    )


def main() -> int:
    owner = new_lock_owner()

    if not try_acquire_lock(owner):
        runtime = load_runtime_status()
        runtime.update({
            "is_running": False,
            "last_check_time": utc_now_iso(),
            "last_check_success": False,
            "last_check_message": "Skipped: another checker run is already in progress.",
            "last_error": "Checker already running.",
        })
        save_runtime_status(runtime)
        print(json.dumps({"success": False, "available": False, "message": "Another checker run is already in progress."}, indent=2))
        return 2

    runtime = load_runtime_status()
    runtime["is_running"] = True
    runtime["run_started_at"] = utc_now_iso()
    save_runtime_status(runtime)

    try:
        config = load_config()

        if not config.enabled:
            runtime = load_runtime_status()
            runtime.update({
                "is_running": True,
                "last_check_time": utc_now_iso(),
                "last_check_success": True,
                "last_check_message": "Checker is disabled.",
                "last_available": False,
                "last_available_trains": [],
                "last_error": "",
            })
            save_runtime_status(runtime)
            print(json.dumps({"success": True, "available": False, "message": "Checker is disabled."}, indent=2))
            return 0

        result = run_check(config)
        available_now = [t for t in result.matched_trains if t.available]

        runtime = load_runtime_status()
        runtime.update({
            "last_check_time": utc_now_iso(),
            "last_check_success": result.success,
            "last_check_message": result.message,
            "last_available": result.available,
            "last_available_trains": [asdict(t) for t in available_now],
            "last_error": "" if result.success else result.message,
        })
        save_runtime_status(runtime)

        alert_state = load_alert_state()
        current_key = build_availability_key(config, available_now) if available_now else ""
        last_key = alert_state.get("last_alert_key", "")

        if result.success and available_now and current_key != last_key:
            lines = [f"{t.departure_time} - {t.seats} seats" for t in available_now]
            message = (
                f"KTMB trains available for {config.travel_date}\n"
                f"Route: {config.origin} -> {config.destination}\n"
                f"Preferred time range: {config.preferred_time_start}-{config.preferred_time_end}\n\n"
                + "\n".join(lines)
            )
            send_telegram(message)
            alert_state["last_alert_key"] = current_key
            save_alert_state(alert_state)

            runtime = load_runtime_status()
            runtime["last_alert_time"] = utc_now_iso()
            save_runtime_status(runtime)

        elif result.success and not available_now:
            alert_state["last_alert_key"] = ""
            save_alert_state(alert_state)

        print(json.dumps({
            "success": result.success,
            "available": result.available,
            "available_matches": [asdict(t) for t in available_now],
            "checked_trains": [asdict(t) for t in result.matched_trains],
            "message": result.message,
        }, indent=2))
        return 0 if result.success else 1

    except Exception as e:
        runtime = load_runtime_status()
        runtime.update({
            "last_check_time": utc_now_iso(),
            "last_check_success": False,
            "last_check_message": f"{type(e).__name__}: {e}",
            "last_available": False,
            "last_available_trains": [],
            "last_error": f"{type(e).__name__}: {e}",
        })
        save_runtime_status(runtime)
        raise

    finally:
        runtime = load_runtime_status()
        runtime["is_running"] = False
        runtime["run_started_at"] = ""
        save_runtime_status(runtime)
        release_lock(owner)


if __name__ == "__main__":
    raise SystemExit(main())