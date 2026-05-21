"""Anomaly detection primitives.

Three layers, in increasing cost:

1. Statistical (rolling z-score + EWMA + IQR)        — O(1) per reading.
2. IsolationForest, per-machine trained on warmup buffer.
3. LLM-assisted severity scoring (TrueFoundry gateway, FAST tier).

The first layer flags a candidate; the second layer corroborates; the
third layer produces a human-readable label + severity.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Deque

import numpy as np
from sklearn.ensemble import IsolationForest

from forgemind_common import TelemetryReading

WINDOW = 240          # 4 minutes at 1Hz
WARMUP = 60           # need at least 1 minute to score
Z_THRESHOLD = 3.5
EWMA_ALPHA = 0.2
METRICS: tuple[str, ...] = (
    "temperature_c",
    "vibration_mm_s",
    "pressure_bar",
    "rpm",
    "power_kw",
)


@dataclass
class MetricStats:
    window: Deque[float] = field(default_factory=lambda: deque(maxlen=WINDOW))
    ewma: float = 0.0
    ewma_var: float = 0.0
    initialized: bool = False

    def update(self, value: float) -> None:
        self.window.append(value)
        if not self.initialized:
            self.ewma = value
            self.ewma_var = 0.0
            self.initialized = True
        else:
            prev = self.ewma
            self.ewma = EWMA_ALPHA * value + (1 - EWMA_ALPHA) * prev
            diff = value - prev
            self.ewma_var = (1 - EWMA_ALPHA) * (self.ewma_var + EWMA_ALPHA * diff * diff)

    def z_score(self, value: float) -> float:
        if len(self.window) < WARMUP:
            return 0.0
        arr = np.fromiter(self.window, dtype=float)
        mu = float(arr.mean())
        sigma = float(arr.std(ddof=1)) or 1e-6
        return (value - mu) / sigma

    def iqr_score(self, value: float) -> float:
        if len(self.window) < WARMUP:
            return 0.0
        arr = np.fromiter(self.window, dtype=float)
        q1, q3 = np.percentile(arr, [25, 75])
        iqr = (q3 - q1) or 1e-6
        return float(abs(value - (q1 + q3) / 2) / iqr)


@dataclass
class MachineState:
    machine_id: str
    metrics: dict[str, MetricStats] = field(default_factory=dict)
    iforest: IsolationForest | None = None
    iforest_trained_at: int = 0
    sample_count: int = 0
    feature_buffer: Deque[list[float]] = field(default_factory=lambda: deque(maxlen=WINDOW * 3))

    def ensure_metric(self, name: str) -> MetricStats:
        m = self.metrics.get(name)
        if m is None:
            m = MetricStats()
            self.metrics[name] = m
        return m


@dataclass
class Anomaly:
    metric: str
    value: float
    z_score: float
    iqr_score: float
    iforest_score: float | None
    score: float           # combined 0..1
    confidence: float      # 0..1


class AnomalyEngine:
    """Maintains per-machine rolling state and yields Anomalies."""

    def __init__(self) -> None:
        self._state: dict[str, MachineState] = {}

    def _state_for(self, machine_id: str) -> MachineState:
        st = self._state.get(machine_id)
        if st is None:
            st = MachineState(machine_id=machine_id)
            self._state[machine_id] = st
        return st

    def feed(self, reading: TelemetryReading) -> list[Anomaly]:
        st = self._state_for(reading.machine_id)
        st.sample_count += 1

        # Update per-metric rolling stats.
        feats: list[float] = []
        for name in METRICS:
            value = float(getattr(reading, name))
            m = st.ensure_metric(name)
            m.update(value)
            feats.append(value)
        st.feature_buffer.append(feats)

        # Periodically retrain IsolationForest once we have enough samples.
        if (
            len(st.feature_buffer) >= WARMUP * 2
            and st.sample_count - st.iforest_trained_at >= WINDOW
        ):
            try:
                X = np.array(st.feature_buffer, dtype=float)
                model = IsolationForest(
                    n_estimators=80,
                    contamination=0.02,
                    random_state=42,
                )
                model.fit(X)
                st.iforest = model
                st.iforest_trained_at = st.sample_count
            except Exception:  # noqa: BLE001
                st.iforest = None

        # Score each metric.
        anomalies: list[Anomaly] = []
        iforest_score: float | None = None
        if st.iforest is not None:
            # decision_function: higher = more normal; flip + scale to 0..1.
            raw = float(st.iforest.decision_function(np.array([feats]))[0])
            iforest_score = float(1.0 / (1.0 + math.exp(raw * 4.0)))

        for i, name in enumerate(METRICS):
            value = feats[i]
            stats = st.metrics[name]
            z = stats.z_score(value)
            iqr = stats.iqr_score(value)
            if abs(z) < Z_THRESHOLD and iqr < 3.0 and (iforest_score is None or iforest_score < 0.7):
                continue

            # Combine signals.
            z_norm = min(1.0, abs(z) / 6.0)
            iqr_norm = min(1.0, iqr / 6.0)
            if_norm = iforest_score or 0.0
            combined = max(z_norm, iqr_norm, if_norm)
            confidence = min(1.0, 0.4 + 0.2 * (z_norm + iqr_norm + if_norm))

            anomalies.append(
                Anomaly(
                    metric=name,
                    value=value,
                    z_score=float(z),
                    iqr_score=float(iqr),
                    iforest_score=iforest_score,
                    score=float(combined),
                    confidence=float(confidence),
                )
            )
        return anomalies
