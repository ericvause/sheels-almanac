"""
astro_data.py
--------------
Uses Kerykeion to fetch current planetary positions and converts them into
an AstroSnapshot ready for the scoring model.

Usage:
    from astro_data import build_snapshot, build_chart, snapshot_from_chart, build_planet_data
    chart    = build_chart()
    snapshot = snapshot_from_chart(chart)
    planets  = build_planet_data(chart)
"""

import logging
import os
from datetime import date, datetime, timezone

# Suppress Kerykeion's geonames warning — we don't need location-based features
logging.getLogger("kerykeion").setLevel(logging.CRITICAL)
os.environ.setdefault("KERYKEION_GEONAMES_USERNAME", "anonymous")

from kerykeion import AstrologicalSubject

from scoring_model import AstroSnapshot

# ---------------------------------------------------------------------------
# Sign name normalization (Kerykeion uses 3-letter abbrevs)
# ---------------------------------------------------------------------------

SIGN_MAP = {
    "Ari": "aries",   "Tau": "taurus",  "Gem": "gemini",
    "Can": "cancer",  "Leo": "leo",     "Vir": "virgo",
    "Lib": "libra",   "Sco": "scorpio", "Sag": "sagittarius",
    "Cap": "capricorn","Aqu": "aquarius","Pis": "pisces",
}


# ---------------------------------------------------------------------------
# Known Mercury & Venus retrograde windows (station dates)
# Shadow = 14 days either side of station.
# These are approximate — kerykeion's retrograde flag is ground truth for
# current status; shadows are inferred from proximity to station dates.
# ---------------------------------------------------------------------------

# (retrograde_start, retrograde_end)
MERCURY_RX_WINDOWS = [
    (date(2024, 8,  5), date(2024, 8, 28)),
    (date(2024,11, 26), date(2024,12, 15)),
    (date(2025, 3, 15), date(2025, 4,  7)),
    (date(2025, 7, 18), date(2025, 8, 11)),
    (date(2025,11,  9), date(2025,11, 29)),
    (date(2026, 3,  3), date(2026, 3, 27)),
    (date(2026, 7,  1), date(2026, 7, 25)),
    (date(2026,10, 22), date(2026,11, 11)),
]

VENUS_RX_WINDOWS = [
    (date(2023, 7, 22), date(2023, 9,  3)),
    (date(2025, 3,  1), date(2025, 4, 12)),
    (date(2026,10,  3), date(2026,11, 13)),
]

SHADOW_DAYS = 14


def _planet_status(is_retrograde: bool, rx_windows: list) -> str:
    """Returns 'retrograde', 'shadow_pre', 'shadow_post', or 'direct'."""
    if is_retrograde:
        return "retrograde"

    today = date.today()
    for start, end in rx_windows:
        days_before = (start - today).days
        days_after  = (today - end).days
        if 0 < days_before <= SHADOW_DAYS:
            return "shadow_pre"
        if 0 < days_after <= SHADOW_DAYS:
            return "shadow_post"

    return "direct"


# ---------------------------------------------------------------------------
# Known solar/lunar eclipse dates (±14-day window = volatile, 14-28 days after = clarity)
# ---------------------------------------------------------------------------

ECLIPSE_DATES = [
    date(2024, 3, 25),  # lunar
    date(2024, 4,  8),  # solar total
    date(2024, 9, 18),  # lunar
    date(2024,10,  2),  # solar annular
    date(2025, 3, 14),  # lunar
    date(2025, 3, 29),  # solar partial
    date(2025, 9,  7),  # lunar
    date(2025, 9, 21),  # solar annular
    date(2026, 2, 17),  # solar annular
    date(2026, 3,  3),  # lunar
    date(2026, 8, 12),  # solar total
    date(2026, 8, 28),  # lunar
]


def _eclipse_proximity() -> str:
    today = date.today()
    for eclipse in ECLIPSE_DATES:
        delta = (today - eclipse).days
        abs_delta = abs(delta)
        if abs_delta <= 14:
            return "within_2_weeks"
        if 14 < delta <= 28:
            return "post_2_to_4_weeks"
    return "none"


# ---------------------------------------------------------------------------
# Aspect helpers
# ---------------------------------------------------------------------------

def _angle_between(abs1: float, abs2: float) -> float:
    """Shortest angular distance between two ecliptic longitudes (0-180)."""
    diff = abs(abs1 - abs2) % 360
    return min(diff, 360 - diff)


def _has_hard_aspect(p1_abs: float, p2_abs: float, orb: float = 8.0) -> bool:
    """True if p1 and p2 are in square (90) or opposition (180), within orb."""
    angle = _angle_between(p1_abs, p2_abs)
    return abs(angle - 90) <= orb or abs(angle - 180) <= orb


def _has_conjunction(p1_abs: float, p2_abs: float, orb: float = 10.0) -> bool:
    return _angle_between(p1_abs, p2_abs) <= orb


# ---------------------------------------------------------------------------
# Void-of-course Moon detection
# ---------------------------------------------------------------------------

MAJOR_ASPECT_ANGLES = [0, 60, 90, 120, 180, 240, 270, 300]
VOC_ORB = 1.0  # degrees


def _is_void_of_course(chart: AstrologicalSubject) -> bool:
    """
    True if the Moon makes no more major applying aspects to any planet
    before it leaves its current sign.
    """
    moon_abs = chart.moon.abs_pos
    remaining = 30.0 - chart.moon.position  # degrees until sign boundary

    planets = [
        chart.sun, chart.mercury, chart.venus, chart.mars,
        chart.jupiter, chart.saturn, chart.uranus, chart.neptune, chart.pluto,
    ]

    for planet in planets:
        p_abs = planet.abs_pos
        for aspect_angle in MAJOR_ASPECT_ANGLES:
            # Exact point where Moon would form this aspect with the planet
            exact = (p_abs - aspect_angle) % 360
            # Distance Moon must travel forward to reach that point
            travel = (exact - moon_abs) % 360
            if travel <= remaining + VOC_ORB:
                return False  # Moon will perfect this aspect before sign change

    return True  # No more aspects — void of course


# ---------------------------------------------------------------------------
# Mars status
# ---------------------------------------------------------------------------

def _mars_status(chart: AstrologicalSubject) -> str:
    if chart.mars.retrograde:
        return "retrograde"
    # Hard aspect to Jupiter or Saturn = volatile/disruptive
    if (_has_hard_aspect(chart.mars.abs_pos, chart.jupiter.abs_pos) or
            _has_hard_aspect(chart.mars.abs_pos, chart.saturn.abs_pos)):
        return "direct_hard_aspect"
    return "direct_neutral"


# ---------------------------------------------------------------------------
# Jupiter status
# ---------------------------------------------------------------------------

def _jupiter_status(chart: AstrologicalSubject) -> str:
    if chart.jupiter.retrograde:
        return "retrograde"
    # Conjunct Neptune = bubble/mania risk
    if _has_conjunction(chart.jupiter.abs_pos, chart.neptune.abs_pos):
        return "hard_aspect"
    # Hard aspect to Saturn = contraction tension
    if _has_hard_aspect(chart.jupiter.abs_pos, chart.saturn.abs_pos):
        return "hard_aspect"
    # Favorable signs: fire and air
    if chart.jupiter.sign in ("Ari", "Leo", "Sag", "Gem", "Lib", "Aqu", "Can", "Sco"):
        return "direct_favorable"
    return "direct_neutral"


# ---------------------------------------------------------------------------
# Saturn status
# ---------------------------------------------------------------------------

def _saturn_status(chart: AstrologicalSubject) -> str:
    if chart.saturn.retrograde:
        return "retrograde"
    # Conjunction, square, or opposition to Pluto = systemic stress
    if (_has_conjunction(chart.saturn.abs_pos, chart.pluto.abs_pos) or
            _has_hard_aspect(chart.saturn.abs_pos, chart.pluto.abs_pos)):
        return "hard_aspect"
    # Hard aspect to Uranus = structural disruption
    if _has_hard_aspect(chart.saturn.abs_pos, chart.uranus.abs_pos):
        return "hard_aspect"
    return "direct_supportive" if not chart.saturn.retrograde else "direct_neutral"


# ---------------------------------------------------------------------------
# Outer planet cycle detection
# ---------------------------------------------------------------------------

def _outer_planet_cycle(chart: AstrologicalSubject) -> str:
    """Returns the most notable active outer planet conjunction, or 'none'."""
    checks = [
        ("saturn_pluto_conjunction",   chart.saturn.abs_pos,  chart.pluto.abs_pos),
        ("jupiter_neptune_conjunction", chart.jupiter.abs_pos, chart.neptune.abs_pos),
        ("jupiter_saturn_conjunction",  chart.jupiter.abs_pos, chart.saturn.abs_pos),
        ("jupiter_uranus_conjunction",  chart.jupiter.abs_pos, chart.uranus.abs_pos),
    ]
    for name, p1, p2 in checks:
        if _has_conjunction(p1, p2, orb=10.0):
            return name
    return "none"


# ---------------------------------------------------------------------------
# Chart creation
# ---------------------------------------------------------------------------

def build_chart(dt: datetime | None = None) -> AstrologicalSubject:
    """
    Creates and returns a raw AstrologicalSubject for the given UTC datetime.

    Args:
        dt: Optional datetime (UTC). Defaults to now.

    Returns:
        AstrologicalSubject from Kerykeion
    """
    if dt is None:
        dt = datetime.now(timezone.utc)

    return AstrologicalSubject(
        "Now",
        dt.year, dt.month, dt.day, dt.hour, dt.minute,
        lng=0.0, lat=0.0, tz_str="UTC",
    )


# ---------------------------------------------------------------------------
# Snapshot from chart
# ---------------------------------------------------------------------------

def snapshot_from_chart(chart: AstrologicalSubject) -> AstroSnapshot:
    """
    Builds an AstroSnapshot from an existing AstrologicalSubject.

    Args:
        chart: AstrologicalSubject from Kerykeion

    Returns:
        AstroSnapshot ready for scoring_model.score()
    """
    # Moon phase from Sun-Moon elongation
    elongation = (chart.moon.abs_pos - chart.sun.abs_pos) % 360

    if _is_void_of_course(chart):
        moon_phase = "void_of_course"
    elif elongation < 22.5 or elongation >= 337.5:
        moon_phase = "new_moon"
    elif elongation < 67.5:
        moon_phase = "waxing_crescent"
    elif elongation < 112.5:
        moon_phase = "first_quarter"
    elif elongation < 157.5:
        moon_phase = "waxing_gibbous"
    elif elongation < 202.5:
        moon_phase = "full_moon"
    elif elongation < 247.5:
        moon_phase = "waning_gibbous"
    elif elongation < 292.5:
        moon_phase = "last_quarter"
    else:
        moon_phase = "waning_crescent"

    return AstroSnapshot(
        moon_phase       = moon_phase,
        moon_sign        = SIGN_MAP[chart.moon.sign],
        sun_sign         = SIGN_MAP[chart.sun.sign],
        mercury_status   = _planet_status(chart.mercury.retrograde, MERCURY_RX_WINDOWS),
        venus_status     = _planet_status(chart.venus.retrograde,   VENUS_RX_WINDOWS),
        mars_status      = _mars_status(chart),
        jupiter_status   = _jupiter_status(chart),
        saturn_status    = _saturn_status(chart),
        outer_planet_cycle = _outer_planet_cycle(chart),
        eclipse_proximity  = _eclipse_proximity(),
    )


# ---------------------------------------------------------------------------
# Planet position data for canvas rendering
# ---------------------------------------------------------------------------

def build_planet_data(chart: AstrologicalSubject) -> dict:
    """
    Returns raw planet position data for canvas rendering.

    Returns:
        Dict with keys: sun, moon, mercury, venus, mars, jupiter, saturn,
        uranus, neptune, pluto. Each entry has lon, sign, retrograde, degree.
        Moon also has phase_angle.
    """
    planet_attrs = {
        "sun":     chart.sun,
        "moon":    chart.moon,
        "mercury": chart.mercury,
        "venus":   chart.venus,
        "mars":    chart.mars,
        "jupiter": chart.jupiter,
        "saturn":  chart.saturn,
        "uranus":  chart.uranus,
        "neptune": chart.neptune,
        "pluto":   chart.pluto,
    }

    result = {}
    for name, p in planet_attrs.items():
        entry = {
            "lon":       round(p.abs_pos, 2),
            "sign":      SIGN_MAP.get(p.sign, p.sign.lower()),
            "retrograde": bool(p.retrograde),
            "degree":    round(p.position, 2),
        }
        result[name] = entry

    # Add phase_angle to moon: (moon.abs_pos - sun.abs_pos) % 360
    phase_angle = (chart.moon.abs_pos - chart.sun.abs_pos) % 360
    result["moon"]["phase_angle"] = round(phase_angle, 2)

    return result


# ---------------------------------------------------------------------------
# Main builder (backwards-compatible)
# ---------------------------------------------------------------------------

def build_snapshot(dt: datetime | None = None) -> AstroSnapshot:
    """
    Builds an AstroSnapshot from current (or provided) UTC datetime.

    Args:
        dt: Optional datetime (UTC). Defaults to now.

    Returns:
        AstroSnapshot ready for scoring_model.score()
    """
    chart = build_chart(dt)
    return snapshot_from_chart(chart)


# ---------------------------------------------------------------------------
# CLI diagnostic
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from scoring_model import score_all

    snapshot = build_snapshot()

    print("\n=== Current Astrological Snapshot ===")
    print(f"  Moon phase    : {snapshot.moon_phase}")
    print(f"  Moon sign     : {snapshot.moon_sign}")
    print(f"  Sun sign      : {snapshot.sun_sign}")
    print(f"  Mercury       : {snapshot.mercury_status}")
    print(f"  Venus         : {snapshot.venus_status}")
    print(f"  Mars          : {snapshot.mars_status}")
    print(f"  Jupiter       : {snapshot.jupiter_status}")
    print(f"  Saturn        : {snapshot.saturn_status}")
    print(f"  Outer cycle   : {snapshot.outer_planet_cycle}")
    print(f"  Eclipse       : {snapshot.eclipse_proximity}")

    results = score_all(snapshot)

    print("\n=== Sentiment Scores ===")
    for tf, result in results.items():
        print(f"\n  {tf.upper()} ({result['label']}, {result['total']:+.3f})")
        for b in result["breakdown"]:
            bar = "+" if b["contribution"] >= 0 else "-"
            print(f"    {bar} {b['signal']:<22} [{b['value_key']:<22}]  "
                  f"score={b['raw_score']:+.1f}  wt={b['weight']:.2f}  => {b['contribution']:+.3f}")
