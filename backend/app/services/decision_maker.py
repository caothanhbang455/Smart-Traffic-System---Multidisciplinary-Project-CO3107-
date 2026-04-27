# backend/app/services/decision_maker.py

"""
DecisionMaker
=============
Determines how long each traffic light phase should remain green.

The system operates on two fixed alternating phases:

    Phase NS  →  north and south lanes move together
    Phase EW  →  east and west lanes move together

Both phases always alternate. The decision maker only controls duration –
it does not choose which phase runs next.

Pipeline
--------
    TrafficDetector → TrafficState → DecisionMaker → MQTT publish

Priority formula
----------------
    normalized    = min(weighted_vehicle_score / max_weighted_score, 1.0)
    priority      = α × normalized + β × density_ratio
    raw_duration  = base_time + k × priority
    adjusted      = raw_duration × environment_factor
    smoothed      = λ × adjusted + (1 - λ) × previous_duration
    final         = clamp(smoothed, min_green, max_green)

Parameter choices
-----------------
    α = 0.6  :                      vehicle count contributes 60% of priority – most direct 
                                    signal of congestion.

    β = 0.4  :                      edge density contributes 40% – compensates for occluded
                                    motorcycles missed by YOLO, captured by Canny estimator.

    base_time = 15s  :              minimum green even with zero traffic.

    k = 40   :                      priority of 1.0 adds 40s → full congestion yields ~55s.

    max_weighted_score = 200 :      normalization ceiling. Scores above this are clipped to 1.0.

    λ = 0.4  :                      new reading contributes 40%, history 60%. Prevents rapid
                                    oscillation from noisy image input.

    max_change = 10s :              duration cannot shift more than 10s per cycle.
                                    Avoids sudden timing changes that confuse drivers.
"""

from ..models.traffic_state import TrafficState


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_ALPHA              = 0.6
DEFAULT_BETA               = 0.4
DEFAULT_BASE_TIME          = 15.0   # seconds
DEFAULT_K                  = 40.0   # seconds per unit priority
DEFAULT_MIN_GREEN          = 15.0   # seconds
DEFAULT_MAX_GREEN          = 90.0   # seconds
DEFAULT_MAX_WEIGHTED_SCORE = 200.0  # normalization ceiling
DEFAULT_SMOOTHING_FACTOR   = 0.4
DEFAULT_MAX_CHANGE         = 10.0   # seconds per cycle


# ---------------------------------------------------------------------------
# DecisionMaker
# ---------------------------------------------------------------------------

class DecisionMaker :

    def __init__(self,
                 alpha              : float = DEFAULT_ALPHA,
                 beta               : float = DEFAULT_BETA,
                 base_time          : float = DEFAULT_BASE_TIME,
                 k                  : float = DEFAULT_K,
                 min_green          : float = DEFAULT_MIN_GREEN,
                 max_green          : float = DEFAULT_MAX_GREEN,
                 max_weighted_score : float = DEFAULT_MAX_WEIGHTED_SCORE,
                 smoothing_factor   : float = DEFAULT_SMOOTHING_FACTOR,
                 max_change         : float = DEFAULT_MAX_CHANGE) :
        """
        Parameters
        ----------
        alpha              : priority weight for normalized vehicle score
        beta               : priority weight for density ratio
                             (alpha + beta should equal 1.0)
        base_time          : minimum base green duration in seconds
        k                  : scaling factor – maps priority [0,1] to additional seconds
        min_green          : hard floor on final green duration (seconds)
        max_green          : hard ceiling on final green duration (seconds)
        max_weighted_score : normalization ceiling for weighted vehicle score
        smoothing_factor   : exponential smoothing coefficient λ
        max_change         : maximum allowed duration change per cycle (seconds)
        """

        self.alpha              = alpha
        self.beta               = beta
        self.base_time          = base_time
        self.k                  = k
        self.min_green          = min_green
        self.max_green          = max_green
        self.max_weighted_score = max_weighted_score
        self.smoothing_factor   = smoothing_factor
        self.max_change         = max_change

        # Per-phase smoothing state – persists across requests via singleton.
        # Both start at base_time so the first cycle is stable.
        self._previous_duration = {
            "NS" : base_time,
            "EW" : base_time,
        }


    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _normalize(self, weighted_score : float) -> float :
        """Normalize weighted vehicle score to [0, 1]."""
        return min(weighted_score / self.max_weighted_score, 1.0)


    def _compute_priority(self, weighted_score : float, density : float) -> float :
        """
        Compute priority score for a phase.

            priority = α × normalize(weighted_score) + β × density
        """
        return self.alpha * self._normalize(weighted_score) + self.beta * density


    def _aggregate_phase(self, traffic_state : TrafficState, phase : str) -> tuple[float, float] :
        """
        Aggregate both directions of a phase into (weighted_score, density).

        Weighted score is summed – total vehicles in both directions matter.
        Density is averaged – it is a ratio, not a count.
        """
        if phase == "NS" :
            weighted_score = (traffic_state.north.weighted_vehicle_score +
                              traffic_state.south.weighted_vehicle_score)
            density = (traffic_state.north.density_ratio +
                       traffic_state.south.density_ratio) / 2
        else :
            weighted_score = (traffic_state.east.weighted_vehicle_score +
                              traffic_state.west.weighted_vehicle_score)
            density = (traffic_state.east.density_ratio +
                       traffic_state.west.density_ratio) / 2

        return weighted_score, density


    def _environment_factor(self, temperature : float, light : float) -> float :
        """
        Compute environmental adjustment multiplier.

        High temperature and bright sunlight correlate with higher traffic
        volume. A small multiplier extends green time under these conditions.

            temperature > 35°C  →  +10%
            light > 900 lux     →  +5%

        These are heuristic values requiring real-world calibration.
        """
        factor = 1.0
        if temperature > 35 :
            factor += 0.10
        if light > 900 :
            factor += 0.05
        return factor


    def _apply_smoothing(self, new_duration : float, previous : float) -> float :
        """
        Exponential smoothing to prevent abrupt duration changes.

            smoothed = λ × new + (1 - λ) × previous
        """
        return self.smoothing_factor * new_duration + (1 - self.smoothing_factor) * previous


    def _apply_change_limit(self, duration : float, previous : float) -> float :
        """
        Cap the maximum shift between consecutive cycles.

        Ensures no single cycle changes duration by more than max_change
        seconds, making timing predictable for drivers.
        """
        delta = duration - previous
        if delta > self.max_change :
            return previous + self.max_change
        elif delta < -self.max_change :
            return previous - self.max_change
        return duration


    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def decide(self, traffic_state : TrafficState, current_phase : str) -> dict :
        """
        Determine the green duration for the current phase.

        Pipeline
        --------
        1. Aggregate both directions of the phase into (score, density).
        2. Compute priority score.
        3. Compute raw duration = base_time + k × priority.
        4. Adjust for environmental conditions (temperature, light).
        5. Apply exponential smoothing against the previous duration.
        6. Clamp the change to max_change seconds.
        7. Hard clamp to [min_green, max_green].
        8. Save duration for next cycle's smoothing.

        Parameters
        ----------
        traffic_state : TrafficState with metrics for all 4 directions
                        and environmental sensor readings.
        current_phase : "NS" or "EW"

        Returns
        -------
        dict with keys:
            phase          : str   – the phase decided
            green_duration : float – recommended green duration in seconds
        """

        print("\n==============================")
        print(f"DECISION ENGINE  –  Phase {current_phase}")
        print("==============================")

        # -- Step 1 & 2: aggregate + priority -------------------------------
        weighted_score, density = self._aggregate_phase(traffic_state, current_phase)
        priority = self._compute_priority(weighted_score, density)

        print(f"\n[Phase Aggregation]")
        print(f"  weighted_score   : {weighted_score}")
        print(f"  density          : {density:.4f}")
        print(f"  normalized_score : {self._normalize(weighted_score):.4f}")
        print(f"  priority         : {priority:.4f}")

        # -- Step 3: raw duration -------------------------------------------
        raw_duration = self.base_time + self.k * priority

        print(f"\n[Raw Duration]")
        print(f"  base_time + k × priority = {self.base_time} + {self.k * priority:.2f} = {raw_duration:.2f}s")

        # -- Step 4: environment adjustment ---------------------------------
        env_factor = self._environment_factor(
            traffic_state.temperature,
            traffic_state.light_intensity
        )
        adjusted = raw_duration * env_factor

        print(f"\n[Environment]")
        print(f"  temperature : {traffic_state.temperature}°C")
        print(f"  light       : {traffic_state.light_intensity} lux")
        print(f"  factor      : {env_factor:.2f}")
        print(f"  adjusted    : {adjusted:.2f}s")

        # -- Step 5 & 6: smoothing + change limit ---------------------------
        previous = self._previous_duration[current_phase]
        smoothed = self._apply_smoothing(adjusted, previous)
        limited  = self._apply_change_limit(smoothed, previous)

        print(f"\n[Smoothing + Change Limit]")
        print(f"  previous  : {previous:.2f}s")
        print(f"  smoothed  : {smoothed:.2f}s")
        print(f"  limited   : {limited:.2f}s")

        # -- Step 7: hard clamp ---------------------------------------------
        final = max(self.min_green, min(self.max_green, limited))

        print(f"\n[Final]")
        print(f"  clamped to [{self.min_green}, {self.max_green}]")
        print(f"  green_duration : {final:.2f}s")
        print("==============================\n")

        # -- Step 8: save for next cycle ------------------------------------
        self._previous_duration[current_phase] = final

        return {
            "phase"          : current_phase,
            "green_duration" : round(final, 2),
        }