#!/usr/bin/env python3
"""Tests for confirming an acoustic direction against the LiDAR scan.

When the camera is off or absent there is no face to lock onto, but the LiDAR can still
say whether something person-sized is standing where the sound came from. That is a
weaker claim than face detection and these tests keep it honest: a wall is not a person,
and the point of the search is to confirm a direction, not to find the nearest object.
"""

import math
import os
import sys
import unittest

pkg_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
astro_base_inner = os.path.join(pkg_dir, "astro_base")
for p in (pkg_dir, astro_base_inner):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from astro_base.lidar_person_finder import find_person_like_clusters, confirm_direction
except ImportError:
    from lidar_person_finder import find_person_like_clusters, confirm_direction


def scan_with(objects, span_deg=360.0, step_deg=1.0, background=float("inf")):
    """Builds (range, bearing) samples: objects is [(centre_deg, width_m, distance_m)]."""
    points = []
    n = int(span_deg / step_deg)
    for i in range(n):
        bearing = -180.0 + i * step_deg
        r = background
        for centre, width_m, dist in objects:
            half_angle = math.degrees(math.atan2(width_m / 2.0, dist))
            if abs((bearing - centre + 180.0) % 360.0 - 180.0) <= half_angle:
                r = min(r, dist)
        points.append((r, bearing))
    return points


class TestPersonLikeClusters(unittest.TestCase):
    def test_a_person_sized_object_is_found(self):
        points = scan_with([(45.0, 0.45, 1.5)])
        clusters = find_person_like_clusters(points)

        self.assertEqual(len(clusters), 1, f"Bir kisi bekleniyordu, {len(clusters)} kume bulundu")
        self.assertAlmostEqual(clusters[0]["bearing_deg"], 45.0, delta=4.0)
        self.assertAlmostEqual(clusters[0]["distance_m"], 1.5, delta=0.2)

    def test_a_wall_is_not_a_person(self):
        """A wall fills a huge angular span. Accepting it is how the previous code turned
        the head toward furniture."""
        points = scan_with([(0.0, 6.0, 1.8)])
        self.assertEqual(
            find_person_like_clusters(points),
            [],
            "Duvar insan olarak kabul edildi.",
        )

    def test_a_thin_object_is_not_a_person(self):
        points = scan_with([(30.0, 0.03, 1.2)])
        self.assertEqual(
            find_person_like_clusters(points),
            [],
            "Ince bir cubuk (masa ayagi, kablo) insan sayilmamali.",
        )

    def test_objects_outside_the_social_zone_are_ignored(self):
        near = scan_with([(20.0, 0.45, 0.15)])
        far = scan_with([(20.0, 0.45, 6.0)])
        self.assertEqual(find_person_like_clusters(near), [], "Cok yakin nesne")
        self.assertEqual(find_person_like_clusters(far), [], "Cok uzak nesne")

    def test_two_people_are_kept_apart(self):
        points = scan_with([(-60.0, 0.45, 1.4), (70.0, 0.45, 1.9)])
        clusters = find_person_like_clusters(points)
        self.assertEqual(len(clusters), 2, f"Iki kisi bekleniyordu: {clusters}")

    def test_an_empty_scan_finds_nobody(self):
        self.assertEqual(find_person_like_clusters([]), [])
        self.assertEqual(find_person_like_clusters(scan_with([])), [])


class TestDirectionConfirmation(unittest.TestCase):
    """The job is confirming where the sound came from, not finding the closest thing."""

    def test_the_cluster_near_the_sound_wins_even_if_another_is_closer(self):
        # Someone talking at +70 deg, and a chair much closer at -60 deg.
        points = scan_with([(-60.0, 0.45, 0.6), (70.0, 0.45, 2.2)])
        confirmed = confirm_direction(points, acoustic_bearing_deg=70.0)

        self.assertIsNotNone(confirmed, "Akustik yonde insan boyutunda bir sey vardi")
        self.assertAlmostEqual(
            confirmed["bearing_deg"],
            70.0,
            delta=6.0,
            msg=f"En yakin nesneye ({confirmed['bearing_deg']:.1f} derece) donuldu; "
            "dogrulanmasi gereken sesin geldigi yondu.",
        )

    def test_nothing_near_the_sound_confirms_nothing(self):
        points = scan_with([(-120.0, 0.45, 1.2)])
        self.assertIsNone(
            confirm_direction(points, acoustic_bearing_deg=70.0),
            "Sesin geldigi yonde kimse yokken dogrulama uretilmemeli.",
        )

    def test_confirmation_stays_within_its_tolerance(self):
        points = scan_with([(70.0, 0.45, 1.5)])
        self.assertIsNotNone(
            confirm_direction(points, 70.0, tolerance_deg=10.0),
            "Tam o yondeki kume dogrulanmali.",
        )
        self.assertIsNone(
            confirm_direction(points, 20.0, tolerance_deg=10.0),
            "50 derece uzaktaki bir kume 10 derecelik toleransla dogrulama sayilmamali.",
        )

    def test_a_wrapped_bearing_still_matches(self):
        points = scan_with([(178.0, 0.45, 1.5)])
        confirmed = confirm_direction(points, acoustic_bearing_deg=-179.0, tolerance_deg=10.0)
        self.assertIsNotNone(
            confirmed,
            "Arkadaki kaynak +-180 dikisinde; sarma yapilmazsa esleme kaciyor.",
        )


if __name__ == "__main__":
    unittest.main()
