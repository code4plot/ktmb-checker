def is_time_in_range(hhmm: str, start_hhmm: str, end_hhmm: str) -> bool:
    value = int(hhmm)
    start = int(start_hhmm)
    end = int(end_hhmm)

    if start <= end:
        return start <= value <= end
    return value >= start or value <= end