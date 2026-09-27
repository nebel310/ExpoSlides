"""Детерминированные свободные прямоугольники с учётом защищённого дизайна."""

from __future__ import annotations

from exposlides.design_models import Box


def overlap(a: Box, b: Box) -> bool:
    return min(a.left + a.width, b.left + b.width) > max(a.left, b.left) and min(
        a.top + a.height, b.top + b.height
    ) > max(a.top, b.top)


def clip(box: Box, width: int, height: int) -> Box | None:
    left, top = max(0, box.left), max(0, box.top)
    right, bottom = min(width, box.left + box.width), min(height, box.top + box.height)
    if right <= left or bottom <= top:
        return None
    return Box(left=left, top=top, width=right - left, height=bottom - top)


def free_box(bounds: Box, obstacles: list[Box]) -> Box | None:
    """Максимальный свободный прямоугольник: перебор X и слияние занятых Y."""
    relevant = [box for box in obstacles if overlap(bounds, box)]
    if not relevant:
        return bounds.model_copy()
    right, bottom = bounds.left + bounds.width, bounds.top + bounds.height
    xs = sorted(
        {
            bounds.left,
            right,
            *[
                max(bounds.left, min(right, x))
                for box in relevant
                for x in (box.left, box.left + box.width)
            ],
        }
    )
    best = None
    best_score = (-1, 0)
    for index, left in enumerate(xs[:-1]):
        for edge in xs[index + 1 :]:
            occupied = sorted(
                (max(bounds.top, box.top), min(bottom, box.top + box.height))
                for box in relevant
                if box.left < edge and box.left + box.width > left
            )
            cursor = bounds.top
            gaps = []
            for start, end in occupied:
                if start > cursor:
                    gaps.append((cursor, start))
                cursor = max(cursor, end)
            if cursor < bottom:
                gaps.append((cursor, bottom))
            for top, end in gaps:
                area = (edge - left) * (end - top)
                score = (area, -abs(left + edge - 2 * bounds.left - bounds.width))
                if score > best_score:
                    best_score = score
                    best = Box(left=left, top=top, width=edge - left, height=end - top)
    return best
