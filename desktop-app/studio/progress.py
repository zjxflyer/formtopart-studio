"""Progress callbacks are scoped to one operation, including nested streamed work."""


def monotonic_progress(callback):
    if callback is None:
        return None
    current_phase = None
    current_percent = 0

    def report(phase, percent):
        nonlocal current_phase, current_percent
        if current_phase is None or percent >= current_percent:
            current_phase = phase
            current_percent = percent
        callback(current_phase, current_percent)

    return report
