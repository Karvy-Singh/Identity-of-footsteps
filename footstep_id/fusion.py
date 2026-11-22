"""Late fusion of named probability vectors; untrained/missing sensors are skipped."""
from collections import Counter, deque
import numpy as np
from .config import LABELS, MODEL_WEIGHTS, SMOOTHING_SIZE


def fuse(probabilities, weights=None):
    """Input: {sensor: {class: probability}}. Model scores need not be calibrated equally."""
    weights = MODEL_WEIGHTS if weights is None else weights
    total = np.zeros(len(LABELS), dtype=float)
    weight_sum = 0.
    used = []
    for sensor, class_scores in probabilities.items():
        weight = float(weights.get(sensor, 1.))
        if weight <= 0:
            continue
        vector = np.array([class_scores.get(label, 0.) for label in LABELS], dtype=float)
        if not np.all(np.isfinite(vector)):
            continue
        total += weight * vector
        weight_sum += weight
        used.append(sensor)
    if weight_sum == 0:
        return None
    total /= weight_sum
    return {"label": LABELS[int(np.argmax(total))],
            "score": float(np.max(total)),
            "scores": dict(zip(LABELS, map(float, total))),
            "used_models": used}


class RollingVote:
    def __init__(self, size=SMOOTHING_SIZE):
        self.items = deque(maxlen=size)

    def update(self, fused):
        if fused is None:
            return "Uncertain"
        self.items.append(fused)
        votes = Counter(item["label"] for item in self.items)
        best_count = max(votes.values())
        tied = [k for k, count in votes.items() if count == best_count]
        if len(tied) == 1:
            return tied[0]
        return max(tied, key=lambda k: np.mean([x["scores"][k] for x in self.items]))
