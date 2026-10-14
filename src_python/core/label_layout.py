"""Peak-label layout without overlapping labels or crossing leader lines.

All geometry is in display units with x to the right and y *away from the
curve* (callers mirror y for labels below transmittance bands). Labels are
vertical text: ``width`` is the horizontal footprint (line height) and
``height`` the text length.

Guarantees for one spectrum:
* label boxes never overlap and stay inside [x_low, x_high];
* labels keep the left-to-right order of their peaks, and every displaced
  label of a cluster bends in one shared horizontal band above that cluster,
  so leaders never cross each other, a label, or the curve.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class LabelRequest:
    peak_x: float          # display x of the peak
    peak_y: float          # display y of the curve at the peak
    width: float           # horizontal footprint of the (rotated) text
    height: float          # extent of the text away from the curve
    importance: float = 0.0


@dataclass
class LabelPlacement:
    x: float               # centre of the label footprint
    base: float            # edge of the label nearest to the curve
    leader: list = field(default_factory=list)   # [(x, y), ...] polyline


@dataclass
class LayoutStyle:
    gap: float = 3.0        # curve → start of leader
    stub: float = 6.0       # minimum vertical leader before a bend
    bend_min: float = 6.0   # height of the slanted part of a leader
    bend_max: float = 22.0
    spacing: float = 1.5    # free space between neighbouring labels
    label_gap: float = 1.5  # leader end → label


def _spread(targets, widths, spacing, low, high):
    """Order-preserving least-squares 1-D packing within [low, high].

    Pool-adjacent-violators gives the packing closest to the targets; bound
    and spacing constraints are then enforced explicitly. Returns centres and
    a block id per label (neighbours that touch share a block).
    """
    blocks = []   # [first index, last index, offsets, centre]
    for i, target in enumerate(targets):
        blocks.append([i, i, [0.0], float(target)])
        while len(blocks) > 1:
            left, right = blocks[-2], blocks[-1]
            left_edge = left[3] + left[2][-1] + widths[left[1]] / 2
            right_edge = right[3] + right[2][0] - widths[right[0]] / 2
            if left_edge + spacing <= right_edge:
                break
            shift = left[2][-1] + (widths[left[1]] + widths[right[0]]) / 2 + spacing
            offsets = left[2] + [shift + value for value in right[2]]
            members = range(left[0], right[1] + 1)
            centre = float(np.mean([targets[m] - offsets[k] for k, m in enumerate(members)]))
            blocks[-2:] = [[left[0], right[1], offsets, centre]]
    centres = [0.0] * len(targets)
    for start, end, offsets, centre in blocks:
        for k, member in enumerate(range(start, end + 1)):
            centres[member] = centre + offsets[k]
    n = len(centres)

    def need(i):  # minimum centre distance between label i and i + 1
        return (widths[i] + widths[i + 1]) / 2 + spacing

    for i in range(n):           # left bound and left neighbours
        floor = low + widths[i] / 2 if i == 0 else centres[i - 1] + need(i - 1)
        centres[i] = max(centres[i], floor if i else max(floor, centres[i]))
    for i in reversed(range(n)):  # right bound and right neighbours
        ceiling = high - widths[i] / 2 if i == n - 1 else centres[i + 1] - need(i)
        centres[i] = min(centres[i], ceiling)
    for i in range(1, n):        # if everything cannot fit, keep order at least
        centres[i] = max(centres[i], centres[i - 1] + need(i - 1))
    block_of, block = [0] * n, 0
    for i in range(1, n):
        if centres[i] - centres[i - 1] > need(i - 1) + 1e-6:
            block += 1
        block_of[i] = block
    return centres, block_of


def _curve_max(curve_x, curve_y, low, high, fallback):
    a, b = np.searchsorted(curve_x, [low, high])
    a = max(0, a - 1)
    b = min(len(curve_x), b + 1)
    window = curve_y[a:b]
    return float(np.max(window)) if len(window) else fallback


def layout_labels(requests, curve_x, curve_y, x_low, x_high, style=None):
    """Place labels for one spectrum; returns LabelPlacement per request.

    ``curve_x`` must be ascending (display x), ``curve_y`` the curve in the
    same units (larger = farther from where labels hang).
    """
    style = style or LayoutStyle()
    if not requests:
        return []
    curve_x = np.asarray(curve_x, dtype=float)
    curve_y = np.asarray(curve_y, dtype=float)
    order = sorted(range(len(requests)), key=lambda i: requests[i].peak_x)
    reqs = [requests[i] for i in order]
    widths = [r.width for r in reqs]
    centres, block_of = _spread([r.peak_x for r in reqs], widths, style.spacing, x_low, x_high)

    # Clusters start as single labels and merge only when their spans (peak to
    # label footprint) overlap: then a leader could pass under another label,
    # so their leaders must bend in one shared band. Labels that merely touch
    # stay independent and hang next to their own bands.
    cluster = list(range(len(reqs)))
    changed = True
    while changed:
        changed = False
        spans = {}
        for i, c in enumerate(cluster):
            lo = min(reqs[i].peak_x, centres[i] - widths[i] / 2)
            hi = max(reqs[i].peak_x, centres[i] + widths[i] / 2)
            span = spans.setdefault(c, [lo, hi])
            span[0], span[1] = min(span[0], lo), max(span[1], hi)
        ids = sorted(spans, key=lambda c: spans[c][0])
        for a, b in zip(ids, ids[1:]):
            if spans[a][1] > spans[b][0]:
                cluster = [a if c == b else c for c in cluster]
                changed = True
                break

    placements = [None] * len(reqs)
    for c in sorted(set(cluster)):
        members = [i for i, value in enumerate(cluster) if value == c]
        displaced = max(abs(centres[i] - reqs[i].peak_x) for i in members)
        if len(members) == 1 and displaced < 0.5:
            i = members[0]
            r = reqs[i]
            top = _curve_max(curve_x, curve_y, centres[i] - widths[i] / 2, centres[i] + widths[i] / 2, r.peak_y)
            start = r.peak_y + style.gap
            base = max(top + style.gap, start + style.stub) + style.label_gap
            placements[i] = LabelPlacement(centres[i], base, [(r.peak_x, start), (r.peak_x, base - style.label_gap)])
            continue
        lo = min(min(reqs[i].peak_x, centres[i] - widths[i] / 2) for i in members)
        hi = max(max(reqs[i].peak_x, centres[i] + widths[i] / 2) for i in members)
        top = _curve_max(curve_x, curve_y, lo, hi, max(reqs[i].peak_y for i in members))
        band_low = top + style.gap + style.stub
        bend = min(style.bend_max, max(style.bend_min, 0.35 * displaced))
        band_high = band_low + bend
        base = band_high + style.label_gap
        for i in members:
            r = reqs[i]
            start = r.peak_y + style.gap
            placements[i] = LabelPlacement(
                centres[i], base,
                [(r.peak_x, start), (r.peak_x, band_low), (centres[i], band_high), (centres[i], base - style.label_gap)],
            )
    result = [None] * len(requests)
    for position, original in enumerate(order):
        result[original] = placements[position]
    return result


def fits(placements, requests, x_low, x_high) -> bool:
    """True when every label box lies inside the horizontal bounds."""
    return all(
        p.x - r.width / 2 >= x_low - 1e-6 and p.x + r.width / 2 <= x_high + 1e-6
        for p, r in zip(placements, requests)
    )


def layout_with_thinning(requests, curve_x, curve_y, x_low, x_high, style=None, max_shift=2.5):
    """Layout that leaves the weakest bands of over-crowded regions unlabelled.

    A label pushed more than ``max_shift`` label widths from its band means the
    region is too dense; the least important label near it is dropped and the
    layout repeated. Returns {request index: LabelPlacement} for kept labels.
    """
    active = list(range(len(requests)))
    while active:
        chosen = [requests[i] for i in active]
        placements = layout_labels(chosen, curve_x, curve_y, x_low, x_high, style)
        shifts = [abs(p.x - r.peak_x) / max(r.width, 1e-9) for p, r in zip(placements, chosen)]
        worst = int(np.argmax(shifts))
        if fits(placements, chosen, x_low, x_high) and shifts[worst] <= max_shift:
            return dict(zip(active, placements))
        centre = chosen[worst].peak_x
        reach = 6 * chosen[worst].width
        near = [i for i in active if abs(requests[i].peak_x - centre) <= reach] or active
        active.remove(min(near, key=lambda i: requests[i].importance))
    return {}
