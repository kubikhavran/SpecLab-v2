"""Geometric guarantees of the peak-label layout on random dense spectra."""

import numpy as np
import pytest

from core.label_layout import LabelRequest, fits, layout_labels


def _segments_cross(p1, p2, q1, q2):
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    d1, d2 = orient(q1, q2, p1), orient(q1, q2, p2)
    d3, d4 = orient(p1, p2, q1), orient(p1, p2, q2)
    return (d1 * d2 < -1e-9) and (d3 * d4 < -1e-9)


def _segment_hits_box(a, b, box):
    x0, x1, y0, y1 = box
    for t in np.linspace(0, 1, 60):
        x, y = a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
        if x0 + 1e-6 < x < x1 - 1e-6 and y0 + 1e-6 < y < y1 - 1e-6:
            return True
    return False


def _random_case(seed, peaks=25, width=900.0):
    rng = np.random.default_rng(seed)
    x = np.linspace(0, width, 2000)
    centres = np.sort(rng.uniform(20, width - 20, peaks))
    if seed % 2:   # dense clusters
        centres = np.sort(np.r_[centres[: peaks // 2], rng.normal(width / 2, 15, peaks - peaks // 2)])
    heights = rng.uniform(20, 300, len(centres))
    y = sum(h * np.exp(-0.5 * ((x - c) / rng.uniform(2, 12)) ** 2) for c, h in zip(centres, heights))
    requests = [LabelRequest(float(c), float(np.interp(c, x, y)), 11.0, 26.0, float(h))
                for c, h in zip(centres, heights)]
    return x, y, requests


@pytest.mark.parametrize("seed", range(12))
def test_no_overlaps_or_crossings(seed):
    x, y, requests = _random_case(seed)
    placements = layout_labels(requests, x, y, 0.0, 900.0)
    boxes = [(p.x - r.width / 2, p.x + r.width / 2, p.base, p.base + r.height)
             for p, r in zip(placements, requests)]
    assert fits(placements, requests, 0.0, 900.0)
    for i, a in enumerate(boxes):
        # Labels sit above the curve across their footprint.
        lo, hi = np.searchsorted(x, [a[0], a[1]])
        assert a[2] >= np.max(y[max(lo - 1, 0):hi + 1]) - 1e-6
        for b in boxes[i + 1:]:
            assert a[1] <= b[0] + 1e-6 or b[1] <= a[0] + 1e-6 or a[3] <= b[2] or b[3] <= a[2]
    leaders = [list(zip(p.leader, p.leader[1:])) for p in placements]
    for i, segments in enumerate(leaders):
        for a, b in segments:
            for j, box in enumerate(boxes):
                if j != i:
                    assert not _segment_hits_box(a, b, box)
            for other in leaders[i + 1:]:
                for c, d in other:
                    assert not _segments_cross(a, b, c, d)
            # Leaders stay above the curve.
            for t in np.linspace(0, 1, 25):
                px, py = a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
                assert py >= np.interp(px, x, y) - 1e-6


def test_isolated_peak_gets_short_straight_leader():
    x = np.linspace(0, 100, 501)
    y = 100 * np.exp(-0.5 * ((x - 50) / 2) ** 2)
    placement, = layout_labels([LabelRequest(50.0, 100.0, 10, 20)], x, y, 0, 100)
    assert placement.x == 50.0 and len(placement.leader) == 2
    assert placement.leader[0][0] == placement.leader[1][0] == 50.0


def test_overfull_axis_is_reported():
    x = np.linspace(0, 50, 101)
    requests = [LabelRequest(float(c), 0.0, 10, 20) for c in range(0, 50, 2)]
    placements = layout_labels(requests, x, np.zeros_like(x), 0, 50)
    assert not fits(placements, requests, 0, 50)
