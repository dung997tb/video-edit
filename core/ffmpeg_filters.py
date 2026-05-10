from __future__ import annotations


def atempo_chain(speed: float) -> list[str]:
    if speed <= 0:
        raise ValueError("speed factor must be > 0")
    if abs(speed - 1.0) < 1e-6:
        return ["atempo=1.0"]
    filters: list[str] = []
    remaining = speed
    while remaining > 2.0 + 1e-6:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5 - 1e-6:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.6f}".rstrip("0").rstrip("."))
    return filters
