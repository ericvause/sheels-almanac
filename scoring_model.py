"""
Financial Astrology Scoring Model
----------------------------------
Produces a bullish/bearish sentiment score (-1.0 to +1.0) based on
current astrological conditions, weighted by trade timeframe.

Timeframes:
  short  = day trading (1-5 days)   → Moon-heavy
  mid    = swing trading (1-8 weeks) → Zodiac season + inner planets
  long   = position/investment (months-years) → Outer planet cycles

Score ranges:
  +0.6 to +1.0 = Strong bullish
  +0.2 to +0.6 = Mild bullish
  -0.2 to +0.2 = Neutral / uncertain
  -0.6 to -0.2 = Mild bearish
  -1.0 to -0.6 = Strong bearish / avoid
"""

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Signal value tables
# ---------------------------------------------------------------------------

MOON_PHASE_SCORES = {
    "new_moon":        0.8,   # new beginnings, initiating
    "waxing_crescent": 0.5,
    "first_quarter":   0.2,   # minor resistance point
    "waxing_gibbous":  0.4,
    "full_moon":      -0.6,   # peak / reversal risk / emotional
    "waning_gibbous": -0.3,
    "last_quarter":   -0.4,
    "waning_crescent":-0.7,
    "void_of_course": -1.0,   # hard no — avoid all trades
}

MOON_SIGN_SCORES = {
    "taurus":      0.6,   # Venus-ruled, stable, financial
    "cancer":      0.5,   # Moon-ruled, supportive
    "capricorn":   0.3,   # disciplined, structured
    "aries":       0.2,   # energetic but impulsive
    "leo":         0.2,   # confident, speculative
    "sagittarius": 0.2,   # optimistic
    "aquarius":   -0.1,   # scattered, unpredictable
    "libra":      -0.1,   # indecisive
    "virgo":      -0.2,   # critical, corrective
    "gemini":     -0.3,   # volatile, mixed signals
    "pisces":     -0.4,   # confused, speculative fog
    "scorpio":    -0.5,   # intense, volatile
}

SUN_SIGN_SCORES = {
    "sagittarius": 0.7,   # Jupiter-ruled, year-end optimism
    "taurus":      0.7,   # Venus-ruled, stable growth
    "aries":       0.6,   # new year energy, momentum
    "capricorn":   0.3,   # conservative, fundamentals
    "leo":         0.3,   # speculative, risk-on
    "cancer":      0.2,   # real estate / housing focus
    "aquarius":    0.1,   # tech/innovation, neutral
    "gemini":     -0.2,   # choppy, news-driven
    "libra":      -0.3,   # rebalancing, indecision
    "pisces":     -0.4,   # confusion, bubble risk
    "virgo":      -0.5,   # analytical correction season
    "scorpio":    -0.6,   # historically crash-prone (October effect)
}

MERCURY_STATUS_SCORES = {
    "direct":          0.4,
    "shadow_pre":     -0.3,   # pre-retrograde shadow
    "retrograde":     -0.8,   # avoid contracts, expect reversals
    "shadow_post":    -0.2,   # post-retrograde shadow, slowly clearing
}

VENUS_STATUS_SCORES = {
    "direct":         0.3,
    "shadow_pre":    -0.3,
    "retrograde":    -0.6,   # avoid financial commitments
    "shadow_post":   -0.2,
}

MARS_STATUS_SCORES = {
    "direct_favorable":  0.3,
    "direct_neutral":    0.1,
    "direct_hard_aspect":-0.4,   # square/opposition to Jupiter/Saturn
    "retrograde":       -0.4,
}

JUPITER_STATUS_SCORES = {
    "direct_favorable":  0.8,   # expansion, growth, bullish
    "direct_neutral":    0.4,
    "retrograde":       -0.2,   # internalized growth, pullback in speculative
    "hard_aspect":      -0.5,   # conjunct Neptune (bubble/bust) or Saturn
}

SATURN_STATUS_SCORES = {
    "direct_supportive": 0.3,   # structural foundation
    "direct_neutral":    0.0,
    "retrograde":       -0.3,
    "hard_aspect":      -0.7,   # square/opposition or conjunct Pluto
}

OUTER_PLANET_CYCLE_SCORES = {
    "jupiter_uranus_conjunction":  0.5,   # innovation boom
    "jupiter_saturn_conjunction": -0.3,   # transition turbulence
    "jupiter_neptune_conjunction":-0.5,   # bubble peak / speculative mania
    "saturn_pluto_conjunction":   -0.8,   # systemic stress (e.g. 2020)
    "none":                        0.0,
}

ECLIPSE_PROXIMITY_SCORES = {
    "within_2_weeks":    -0.6,   # volatile window, avoid
    "post_2_to_4_weeks":  0.3,   # direction established, trend follows
    "none":               0.0,
}


# ---------------------------------------------------------------------------
# Weights by timeframe
# Each dict must sum to 1.0
# ---------------------------------------------------------------------------

WEIGHTS = {
    "short": {
        # Day trading (1-5 days) — Moon dominates
        "moon_phase":           0.35,
        "moon_sign":            0.25,
        "mercury_status":       0.18,
        "eclipse_proximity":    0.10,
        "sun_sign":             0.07,
        "venus_status":         0.05,
        # not relevant at this timeframe
        "mars_status":          0.00,
        "jupiter_status":       0.00,
        "saturn_status":        0.00,
        "outer_planet_cycle":   0.00,
    },
    "mid": {
        # Swing trading (1-8 weeks) — Zodiac season + inner planets
        "sun_sign":             0.25,
        "mercury_status":       0.20,
        "venus_status":         0.15,
        "moon_phase":           0.15,
        "mars_status":          0.12,
        "eclipse_proximity":    0.08,
        "moon_sign":            0.05,
        # not heavily weighted at this timeframe
        "jupiter_status":       0.00,
        "saturn_status":        0.00,
        "outer_planet_cycle":   0.00,
    },
    "long": {
        # Position / investment (months–years) — outer planets dominate
        "jupiter_status":       0.28,
        "saturn_status":        0.22,
        "outer_planet_cycle":   0.20,
        "mars_status":          0.10,
        "sun_sign":             0.10,
        "eclipse_proximity":    0.07,
        "venus_status":         0.03,
        # not relevant at macro timeframe
        "moon_phase":           0.00,
        "moon_sign":            0.00,
        "mercury_status":       0.00,
    },
}


# ---------------------------------------------------------------------------
# Input snapshot dataclass
# ---------------------------------------------------------------------------

@dataclass
class AstroSnapshot:
    """
    Current astrological conditions. Populate this from your API/library calls.
    All values should be string keys matching the score tables above.
    """
    moon_phase: str            # e.g. "waxing_gibbous"
    moon_sign: str             # e.g. "taurus"
    sun_sign: str              # e.g. "pisces"
    mercury_status: str        # e.g. "direct" | "retrograde" | "shadow_pre" | "shadow_post"
    venus_status: str          # e.g. "direct" | "retrograde" | "shadow_pre" | "shadow_post"
    mars_status: str           # e.g. "direct_favorable" | "direct_hard_aspect" | "retrograde"
    jupiter_status: str        # e.g. "direct_favorable" | "retrograde" | "hard_aspect"
    saturn_status: str         # e.g. "direct_supportive" | "hard_aspect"
    outer_planet_cycle: str    # e.g. "saturn_pluto_conjunction" | "none"
    eclipse_proximity: str     # e.g. "within_2_weeks" | "post_2_to_4_weeks" | "none"


# ---------------------------------------------------------------------------
# Scoring engine
# ---------------------------------------------------------------------------

SIGNAL_TABLES = {
    "moon_phase":         MOON_PHASE_SCORES,
    "moon_sign":          MOON_SIGN_SCORES,
    "sun_sign":           SUN_SIGN_SCORES,
    "mercury_status":     MERCURY_STATUS_SCORES,
    "venus_status":       VENUS_STATUS_SCORES,
    "mars_status":        MARS_STATUS_SCORES,
    "jupiter_status":     JUPITER_STATUS_SCORES,
    "saturn_status":      SATURN_STATUS_SCORES,
    "outer_planet_cycle": OUTER_PLANET_CYCLE_SCORES,
    "eclipse_proximity":  ECLIPSE_PROXIMITY_SCORES,
}

TIMEFRAMES = ["short", "mid", "long"]


def score(snapshot: AstroSnapshot, timeframe: str) -> dict:
    """
    Returns a dict with:
      - total: float in [-1.0, 1.0]
      - label: str ("Strong Bullish" / "Mild Bullish" / "Neutral" / "Mild Bearish" / "Strong Bearish")
      - breakdown: list of (signal, value, weight, contribution) tuples
    """
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"timeframe must be one of {TIMEFRAMES}")

    weights = WEIGHTS[timeframe]
    snapshot_dict = {
        "moon_phase":         snapshot.moon_phase,
        "moon_sign":          snapshot.moon_sign,
        "sun_sign":           snapshot.sun_sign,
        "mercury_status":     snapshot.mercury_status,
        "venus_status":       snapshot.venus_status,
        "mars_status":        snapshot.mars_status,
        "jupiter_status":     snapshot.jupiter_status,
        "saturn_status":      snapshot.saturn_status,
        "outer_planet_cycle": snapshot.outer_planet_cycle,
        "eclipse_proximity":  snapshot.eclipse_proximity,
    }

    total = 0.0
    breakdown = []

    for signal, weight in weights.items():
        if weight == 0.0:
            continue
        value_key = snapshot_dict[signal]
        table = SIGNAL_TABLES[signal]
        if value_key not in table:
            raise ValueError(f"Unknown value '{value_key}' for signal '{signal}'")
        value = table[value_key]
        contribution = value * weight
        total += contribution
        breakdown.append({
            "signal":       signal,
            "value_key":    value_key,
            "raw_score":    round(value, 2),
            "weight":       round(weight, 2),
            "contribution": round(contribution, 3),
        })

    # Sort breakdown by absolute contribution descending (most influential first)
    breakdown.sort(key=lambda x: abs(x["contribution"]), reverse=True)

    total = round(max(-1.0, min(1.0, total)), 3)

    if total >= 0.6:
        label = "Strong Bullish"
    elif total >= 0.2:
        label = "Mild Bullish"
    elif total >= -0.2:
        label = "Neutral"
    elif total >= -0.6:
        label = "Mild Bearish"
    else:
        label = "Strong Bearish"

    return {
        "timeframe": timeframe,
        "total":     total,
        "label":     label,
        "breakdown": breakdown,
    }


def score_all(snapshot: AstroSnapshot) -> dict:
    """Returns scores for all three timeframes at once."""
    return {tf: score(snapshot, tf) for tf in TIMEFRAMES}


# ---------------------------------------------------------------------------
# Example usage
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    # Hypothetical snapshot for today (plug in real API data)
    now = AstroSnapshot(
        moon_phase="waxing_gibbous",
        moon_sign="taurus",
        sun_sign="pisces",
        mercury_status="direct",
        venus_status="retrograde",       # Venus retrograde as of early 2025
        mars_status="direct_neutral",
        jupiter_status="direct_favorable",
        saturn_status="direct_neutral",
        outer_planet_cycle="none",
        eclipse_proximity="none",
    )

    results = score_all(now)

    for tf, result in results.items():
        print(f"\n{'='*40}")
        print(f"  {tf.upper()} TERM: {result['label']} ({result['total']:+.3f})")
        print(f"{'='*40}")
        for b in result["breakdown"]:
            bar = "+" if b["contribution"] >= 0 else "-"
            print(f"  {bar} {b['signal']:<22} [{b['value_key']:<22}]  "
                  f"score={b['raw_score']:+.1f}  wt={b['weight']:.2f}  "
                  f"=> {b['contribution']:+.3f}")
