#!/usr/bin/env python3
"""Is there somebody standing where the sound came from?

The camera answers that far better, but it is not always on, and the head still has to
decide. A 2D LiDAR can offer a weaker second opinion: it sees one horizontal slice of the
room, so it cannot recognise anyone, but it can say whether something roughly person-wide
is standing in a given direction.

Be clear about the limit. A slice at one height cannot tell a standing person from a
similarly wide table leg, and it never sees a face. Used on its own it is not a person
detector. Used to confirm a direction the microphones already chose, it is worth having:
the question is only "is there something person-sized over there", and the sound has
already answered "somebody is talking over there".

This replaces picking the nearest point in range and calling it a person, which turned
the head toward walls and furniture, and which answered the wrong question entirely --
the nearest object is not the one that spoke.

No ROS here, so the geometry can be exercised directly.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

# A horizontal slice through a standing person catches a leg, both legs, or the torso,
# depending on how high the scanner sits. Anything much narrower is furniture trim or a
# cable; anything much wider is a wall or a sofa.
DEFAULT_MIN_WIDTH_M = 0.12
DEFAULT_MAX_WIDTH_M = 0.75

# The social zone: closer than this is the robot's own body or something it is touching,
# further and the direction is too coarse to be worth confirming.
DEFAULT_MIN_DIST_M = 0.4
DEFAULT_MAX_DIST_M = 2.8

# Two readings belong to the same object while they stay this close in depth. A person
# standing in front of a wall shows up as a step of tens of centimetres.
DEFAULT_GAP_M = 0.18

DEFAULT_TOLERANCE_DEG = 35.0


def _wrap_deg(angle: float) -> float:
    return (angle + 180.0) % 360.0 - 180.0


def find_person_like_clusters(
    points: Sequence[Tuple[float, float]],
    min_width_m: float = DEFAULT_MIN_WIDTH_M,
    max_width_m: float = DEFAULT_MAX_WIDTH_M,
    min_dist_m: float = DEFAULT_MIN_DIST_M,
    max_dist_m: float = DEFAULT_MAX_DIST_M,
    gap_m: float = DEFAULT_GAP_M,
) -> List[Dict[str, float]]:
    """Groups a scan into objects and keeps the ones that could be a person.

    `points` is (range_m, bearing_deg), in scan order. Returns a dict per surviving
    cluster with its bearing, distance and physical width.
    """
    usable = [
        (r, b)
        for r, b in points
        if not (math.isnan(r) or math.isinf(r)) and min_dist_m <= r <= max_dist_m
    ]
    if not usable:
        return []

    clusters: List[List[Tuple[float, float]]] = []
    current: List[Tuple[float, float]] = [usable[0]]
    for prev, point in zip(usable, usable[1:]):
        contiguous = abs(point[0] - prev[0]) <= gap_m and abs(_wrap_deg(point[1] - prev[1])) <= 5.0
        if contiguous:
            current.append(point)
        else:
            clusters.append(current)
            current = [point]
    clusters.append(current)

    # The scan is a ring: a cluster straddling the seam arrives as two pieces.
    if len(clusters) > 1:
        first, last = clusters[0], clusters[-1]
        if (
            abs(last[-1][0] - first[0][0]) <= gap_m
            and abs(_wrap_deg(first[0][1] - last[-1][1])) <= 5.0
        ):
            clusters[0] = last + first
            clusters.pop()

    found: List[Dict[str, float]] = []
    for cluster in clusters:
        ranges = [r for r, _ in cluster]
        distance = sum(ranges) / len(ranges)

        bearings = [b for _, b in cluster]
        span_deg = abs(_wrap_deg(bearings[-1] - bearings[0]))
        # One lonely reading has no span of its own; give it the beam it occupies so a
        # single stray return is not silently promoted to a person.
        if len(cluster) == 1:
            span_deg = 0.0
        width_m = 2.0 * distance * math.tan(math.radians(span_deg) / 2.0)
        if not (min_width_m <= width_m <= max_width_m):
            continue

        sin_sum = sum(math.sin(math.radians(b)) for b in bearings)
        cos_sum = sum(math.cos(math.radians(b)) for b in bearings)
        found.append(
            {
                "bearing_deg": _wrap_deg(math.degrees(math.atan2(sin_sum, cos_sum))),
                "distance_m": distance,
                "width_m": width_m,
            }
        )

    return found


def confirm_direction(
    points: Sequence[Tuple[float, float]],
    acoustic_bearing_deg: float,
    tolerance_deg: float = DEFAULT_TOLERANCE_DEG,
    **cluster_kwargs,
) -> Optional[Dict[str, float]]:
    """The person-sized cluster closest to where the sound came from, if there is one.

    Closest in ANGLE, not in distance. The chair by the robot's knee is nearer than the
    person across the room, and the chair did not speak.
    """
    candidates = find_person_like_clusters(points, **cluster_kwargs)
    if not candidates:
        return None

    best = min(
        candidates,
        key=lambda c: abs(_wrap_deg(c["bearing_deg"] - acoustic_bearing_deg)),
    )
    if abs(_wrap_deg(best["bearing_deg"] - acoustic_bearing_deg)) > tolerance_deg:
        return None
    return best
