"""
Heuristic detectors for price-action setups: breakout, liquidity sweep,
support/resistance retest, and CISD (change in state of delivery).

These are simplified approximations, not textbook-precise ICT implementations —
treat flagged setups as "worth a look," not guaranteed signals. Feel free to
tune the thresholds below (LOOKBACK, tolerance, min_streak) once you see how
it performs against pairs you know well.
"""

LOOKBACK = 20  # candles used to establish recent highs/lows


def recent_high_low(candles, lookback=LOOKBACK, exclude_last=1):
    """Highest high / lowest low over the lookback window, excluding the most recent candle(s)."""
    window = candles[-(lookback + exclude_last):-exclude_last]
    if not window:
        return None, None
    highs = [c["high"] for c in window]
    lows = [c["low"] for c in window]
    return max(highs), min(lows)


def detect_breakout(candles):
    if len(candles) < LOOKBACK + 1:
        return None
    high, low = recent_high_low(candles)
    last = candles[-1]
    if high and last["close"] > high:
        return "Breakout above recent range high"
    if low and last["close"] < low:
        return "Breakout below recent range low"
    return None


def detect_sweep(candles):
    if len(candles) < LOOKBACK + 1:
        return None
    high, low = recent_high_low(candles)
    last = candles[-1]
    if high and last["high"] > high and last["close"] < high:
        return "Liquidity sweep of recent highs (possible reversal down)"
    if low and last["low"] < low and last["close"] > low:
        return "Liquidity sweep of recent lows (possible reversal up)"
    return None


def detect_retest(candles):
    """Looks for price breaking a level earlier in the window, then returning to retest it."""
    if len(candles) < LOOKBACK + 5:
        return None

    window = candles[-(LOOKBACK + 5):]
    broken_high = None
    broken_low = None

    for i in range(10, len(window) - 1):
        sub_high = max(c["high"] for c in window[i - 10:i])
        sub_low = min(c["low"] for c in window[i - 10:i])
        if window[i]["close"] > sub_high:
            broken_high = sub_high
        if window[i]["close"] < sub_low:
            broken_low = sub_low

    last = window[-1]
    price_range = max(c["high"] for c in window) - min(c["low"] for c in window)
    tolerance = price_range * 0.02

    if broken_high and abs(last["close"] - broken_high) <= tolerance:
        return "Retesting previously broken resistance (now support)"
    if broken_low and abs(last["close"] - broken_low) <= tolerance:
        return "Retesting previously broken support (now resistance)"
    return None


def detect_cisd(candles, min_streak=3):
    """
    Simplified Change in State of Delivery: finds a streak of same-direction
    candles, then checks if the latest candle closes back through the OPEN
    of the first candle in that streak — signaling a potential order flow shift.
    """
    if len(candles) < min_streak + 1:
        return None

    directions = [c["close"] > c["open"] for c in candles]  # True = bullish

    streak_dir = directions[-2]
    streak_start = len(candles) - 2
    while streak_start > 0 and directions[streak_start - 1] == streak_dir:
        streak_start -= 1

    streak_len = (len(candles) - 1) - streak_start
    if streak_len < min_streak:
        return None

    streak_open = candles[streak_start]["open"]
    last = candles[-1]

    if streak_dir and last["close"] < streak_open:
        return "Bearish CISD — shift against the prior bullish streak"
    if not streak_dir and last["close"] > streak_open:
        return "Bullish CISD — shift against the prior bearish streak"
    return None


def scan(candles):
    """Runs all detectors, returns a list of (signal_type, message) tuples found."""
    results = []
    checks = [
        ("breakout", detect_breakout),
        ("sweep", detect_sweep),
        ("retest", detect_retest),
        ("cisd", detect_cisd),
    ]
    for signal_type, fn in checks:
        message = fn(candles)
        if message:
            results.append((signal_type, message))
    return results
