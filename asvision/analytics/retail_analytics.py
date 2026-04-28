"""
Retail Analytics Engine  (no-OCR version)
==========================================
Computes all KPIs from the 3-stage pipeline (shelves, items, depth).

Active analytics (detection + depth based):
  1. Advanced Gap Detection
  2. Restock Volume Estimation
  3. Share of Shelf (SOS) — by class_id
  4. Per-shelf item density

Dormant analytics (require OCR — return empty for now):
  5. Planogram Compliance
  6. Orphaned Items
  7. Expiry Date Tracking (FEFO)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import SHELF_DEPTH_CM


class RetailAnalytics:
    """Compute retail KPIs from pipeline outputs."""

    def __init__(
        self,
        shelves: list[dict],
        items: list[dict],
        depth_map: np.ndarray | None,
        depth_cutoff: float = 0.65,
    ):
        self.shelves = shelves
        self.items = items
        self.depth_map = depth_map
        self.depth_cutoff = depth_cutoff

        # pre-compute
        self._gaps = self._detect_gaps()
        self._restock = self._estimate_restock()
        self._sos = self._calculate_sos()

    # ── KPI properties ──────────────────────────────────────────────────

    @property
    def total_items(self) -> int:
        return len(self.items)

    @property
    def missing_items(self) -> int:
        """Number of detected shelf gaps."""
        return len(self._gaps)

    @property
    def restock_count(self) -> int:
        return len(self._restock)

    @property
    def items_per_shelf(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for it in self.items:
            lbl = it.get("shelf_label", "Unassigned")
            counts[lbl] = counts.get(lbl, 0) + 1
        return counts

    @property
    def top_brand_sos(self) -> float:
        if not self._sos:
            return 0.0
        return max(self._sos.values()) * 100

    @property
    def sos_breakdown(self) -> dict[str, float]:
        return {k: v * 100 for k, v in self._sos.items()}

    # ── 1. Geometry-First Gap Detection ───────────────────────────────

    def _detect_gaps(self) -> list[dict]:
        """Find horizontal gaps between detected products on each shelf.

        This version is **geometry-first**: a gap is any horizontal span
        within a shelf that is NOT covered by any product bounding box.
        Depth is used only for severity grading, never as a hard filter.

        Steps per shelf
        ───────────────
        1. Gather items assigned to the shelf.
        2. Compute the *product band* (union of item y-ranges) — space
           above/below products is NOT a gap.
        3. Build a 1-D boolean occupancy strip across the shelf width,
           marking every pixel column that is covered by at least one
           product bbox.
        4. Find contiguous *unoccupied* runs wider than a minimum
           threshold (30 % of median product width, floor 15 px).
        5. Each qualifying run becomes a gap.  If a depth map is
           available, sample it for severity; otherwise default to MEDIUM.

        This approach handles overlapping / touching YOLO boxes correctly
        and works even when depth estimation is unavailable.
        """
        gaps: list[dict] = []

        dm_h = dm_w = 0
        if self.depth_map is not None:
            dm_h, dm_w = self.depth_map.shape[:2]

        for shelf in self.shelves:
            sx1, sy1, sx2, sy2 = (int(v) for v in shelf["bbox"])
            shelf_w = sx2 - sx1
            if shelf_w <= 0:
                continue

            # ── Gather items on this shelf ──────────────────────────────
            shelf_items = [
                it for it in self.items
                if it.get("shelf_label") == shelf["label"]
            ]

            if not shelf_items:
                # Entire shelf is empty → one big gap
                depth_val = self._sample_depth(sy1, sy2, sx1, sx2, dm_h, dm_w)
                sev = self._severity(depth_val)
                gaps.append(self._make_gap(
                    shelf["label"], sx1, sx2, sy1, sy2,
                    shelf_w, depth_val, sev,
                ))
                continue

            # ── Product band (vertical extent of items) ─────────────────
            band_y1 = max(min(int(it["bbox"][1]) for it in shelf_items), sy1)
            band_y2 = min(max(int(it["bbox"][3]) for it in shelf_items), sy2)
            if band_y2 <= band_y1:
                continue

            # ── 1-D occupancy strip ─────────────────────────────────────
            occupancy = np.zeros(shelf_w, dtype=bool)
            for item in shelf_items:
                ix1 = max(int(item["bbox"][0]) - sx1, 0)
                ix2 = min(int(item["bbox"][2]) - sx1, shelf_w)
                if ix2 > ix1:
                    occupancy[ix1:ix2] = True

            # ── Adaptive min-gap width ──────────────────────────────────
            item_widths = [it["bbox"][2] - it["bbox"][0] for it in shelf_items]
            median_w = float(np.median(item_widths)) if item_widths else 40.0
            min_gap_w = max(int(median_w * 0.30), 15)

            # ── Find contiguous empty runs ──────────────────────────────
            for start, length in self._find_runs(~occupancy):
                if length < min_gap_w:
                    continue
                gx1 = sx1 + start
                gx2 = sx1 + start + length
                depth_val = self._sample_depth(
                    band_y1, band_y2, gx1, gx2, dm_h, dm_w,
                )
                sev = self._severity(depth_val)
                gaps.append(self._make_gap(
                    shelf["label"], gx1, gx2, band_y1, band_y2,
                    length, depth_val, sev,
                ))

        return gaps

    # ── Gap detection helpers ───────────────────────────────────────────

    def _sample_depth(
        self, y1: int, y2: int, x1: int, x2: int,
        dm_h: int, dm_w: int,
    ) -> float:
        """Return median depth in a region, or -1.0 if depth unavailable."""
        if self.depth_map is None or dm_h == 0:
            return -1.0
        roi = self.depth_map[
            max(y1, 0):min(y2, dm_h),
            max(x1, 0):min(x2, dm_w),
        ]
        if roi.size == 0:
            return -1.0
        return float(np.median(roi))

    def _severity(self, depth_val: float) -> str:
        """Grade gap severity from depth value."""
        if depth_val < 0:
            return "DETECTED"           # no depth info, still a gap
        if depth_val >= 0.85:
            return "HIGH"
        if depth_val >= self.depth_cutoff:
            return "MEDIUM"
        return "LOW"                    # shallow gap (products pushed back a bit)

    @staticmethod
    def _find_runs(arr: np.ndarray) -> list[tuple[int, int]]:
        """Contiguous True runs → list of (start, length)."""
        runs: list[tuple[int, int]] = []
        i, n = 0, len(arr)
        while i < n:
            if arr[i]:
                s = i
                while i < n and arr[i]:
                    i += 1
                runs.append((s, i - s))
            else:
                i += 1
        return runs

    @staticmethod
    def _make_gap(
        shelf_label: str,
        gx1: int, gx2: int,
        gy1: int, gy2: int,
        width: int, depth: float,
        severity: str,
    ) -> dict:
        return {
            "shelf_label": shelf_label,
            "gap_x1": gx1, "gap_x2": gx2,
            "gap_y1": gy1, "gap_y2": gy2,
            "gap_width_px": width,
            "depth_value": round(depth, 3) if depth >= 0 else None,
            "severity": severity,
        }

    # ── 2. Restock Volume Estimation ────────────────────────────────────

    def _estimate_restock(self) -> list[dict]:
        """Items pushed far back (high depth) with estimated void in front."""
        restock: list[dict] = []
        if self.depth_map is None:
            return restock

        for item in self.items:
            d = item.get("depth_median")
            if d is None or d < self.depth_cutoff:
                continue
            bw = item["bbox"][2] - item["bbox"][0]
            item_w_cm = max(bw * 0.05, 1)
            void_cm = d * SHELF_DEPTH_CM
            est_qty = max(1, int(void_cm / item_w_cm))
            restock.append({
                "item_id": item.get("id", ""),
                "shelf_label": item.get("shelf_label", ""),
                "bbox": item["bbox"],
                "depth_value": round(d, 3),
                "void_depth_cm": round(void_cm, 1),
                "est_restock_qty": est_qty,
                "priority": "URGENT" if d > 0.85 else "MODERATE",
            })
        return restock

    # ── 3. Share of Shelf (SOS) ─────────────────────────────────────────

    def _calculate_sos(self) -> dict[str, float]:
        """SOS by class_id, labelled as Product."""
        total_w = sum(max(s["bbox"][2] - s["bbox"][0], 0) for s in self.shelves)
        if total_w == 0:
            return {}

        class_widths: dict[str, float] = {}
        for it in self.items:
            key = f"Product {it['class_id']}"
            bw = it["bbox"][2] - it["bbox"][0]
            class_widths[key] = class_widths.get(key, 0) + bw

        return {k: w / total_w for k, w in class_widths.items()}

    # ── Report generators ───────────────────────────────────────────────

    def restock_report(self) -> pd.DataFrame:
        rows: list[dict] = []

        for g in self._gaps:
            rows.append({
                "Type": "GAP",
                "Shelf": g["shelf_label"],
                "Location (px)": f'{g["gap_x1"]}–{g["gap_x2"]}',
                "Depth": g["depth_value"] if g["depth_value"] is not None else "\u2013",
                "Severity": g["severity"],
                "Est. Restock Qty": "–",
            })
        for r in self._restock:
            rows.append({
                "Type": "PUSHED_BACK",
                "Shelf": r["shelf_label"],
                "Location (px)": f'{int(r["bbox"][0])}–{int(r["bbox"][2])}',
                "Depth": r["depth_value"],
                "Severity": r["priority"],
                "Est. Restock Qty": r["est_restock_qty"],
            })
        if not rows:
            rows.append({
                "Type": "–", "Shelf": "–", "Location (px)": "–",
                "Depth": "–", "Severity": "None",
                "Est. Restock Qty": "All shelves fully stocked",
            })
        return pd.DataFrame(rows)

    def compliance_report(self) -> pd.DataFrame:
        """Placeholder — requires OCR to be enabled."""
        return pd.DataFrame([{
            "Alert Type": "–",
            "Shelf": "–",
            "Status": "OCR_DISABLED",
            "Detail": "Enable OCR (Stage 4) for planogram compliance, "
                      "orphaned-item, and expiry-date analytics.",
        }])

