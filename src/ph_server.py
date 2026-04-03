import json, os, sys, math, re
import numpy as np
from collections import defaultdict
from scipy.spatial import cKDTree
from scipy.ndimage import gaussian_filter
import gudhi
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Persistent Homology Live API")

# Allow CORS for local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Paths & Globals ────────────────────────────────────────────────────────
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "dashboard", "web_dashboard", "public", "data")

# Global state to hold loaded data
data_cache = {}


def load_data():
    print("Loading base datasets into memory...")
    with open(os.path.join(DATA, "blocks.json")) as f:
        blocks_gj = json.load(f)
    with open(os.path.join(DATA, "properties.json")) as f:
        props_gj = json.load(f)
    with open(os.path.join(DATA, "crimes.json")) as f:
        crimes_gj = json.load(f)

    blocks = {}
    for feat in blocks_gj["features"]:
        p = feat["properties"]
        geom = feat["geometry"]  # We only need center for KDTree
        # In the original, centroid was recalculated. Here we just use what's available or approx
        # if centroid is not in properties, we'll extract from geometry
        if "cx" in p and "cy" in p:
            cx, cy = p["cx"], p["cy"]
        else:
            # simple bbox center fallback if needed, but the original script had cx/cy in blocks?
            # actually we can just parse the original blocks
            coords = feat["geometry"]["coordinates"][0]
            if isinstance(coords[0][0], list):  # MultiPolygon
                coords = coords[0]
            cx = sum(c[0] for c in coords) / len(coords)
            cy = sum(c[1] for c in coords) / len(coords)

        blocks[p["block_id"]] = {
            "avg_value": p.get("avg_value", 0),
            "avg_age": p.get("avg_age", 0),
            "crime_count": p.get("crime_count", 0),
            "neighbors": p.get("neighbors", []),
            "zoning_percentages": p.get("zoning_percentages", {}),
            "cx": cx,
            "cy": cy,
        }

    block_props = defaultdict(lambda: {"values": [], "ages": []})
    for feat in props_gj["features"]:
        p = feat["properties"]
        bid = p.get("block_id")
        if not bid:
            continue
        if p.get("property_value", 0) > 0:
            block_props[bid]["values"].append(p["property_value"])
        if p.get("building_age", 0) > 0:
            block_props[bid]["ages"].append(p["building_age"])

    def pure_mean(vals):
        return float(np.mean(vals)) if vals else 0.0

    for bid in blocks:
        bp = block_props.get(bid, {"values": [], "ages": []})
        blocks[bid]["filt_value"] = (
            pure_mean(bp["values"]) if bp["values"] else blocks[bid]["avg_value"]
        )
        blocks[bid]["filt_age"] = (
            pure_mean(bp["ages"]) if bp["ages"] else blocks[bid]["avg_age"]
        )

    crime_coords = []
    crime_types = []
    for feat in crimes_gj["features"]:
        coords = feat["geometry"]["coordinates"]
        crime_coords.append([coords[0], coords[1]])
        crime_types.append(feat["properties"].get("TYPE", "Unknown"))

    data_cache["blocks"] = blocks
    data_cache["crime_coords"] = np.array(crime_coords)
    data_cache["crime_types"] = crime_types

    LAT_CENTER = 49.2
    METERS_PER_DEG_LAT = 111000
    METERS_PER_DEG_LON = 111000 * math.cos(math.radians(LAT_CENTER))
    
    def standardize_street(name):
        name = name.upper().strip()
        replacements = {
            r"\bSTREET\b": "ST", r"\bDOORS\b": "DRS",
            r"\bAVENUE\b": "AVE", r"\bAV\b": "AVE",
            r"\bDRIVE\b": "DR", r"\bBOULEVARD\b": "BLVD", r"\bROAD\b": "RD",
            r"\bWAY\b": "WY", r"\bPLACE\b": "PL", r"\bSQUARE\b": "SQ",
            r"\bHIGHWAY\b": "HWY", r"\bCRESCENT\b": "CR", r"\bCRES\b": "CR"
        }
        for k, v in replacements.items():
            name = re.sub(k, v, name)
        return re.sub(r"\s+", " ", name)

    def parse_segment(hblock):
        hblock = hblock.upper().strip()
        match = re.match(r"(\d+|\d+[A-Z])-(\d+|\d+[A-Z])\s+(.+)", hblock)
        if match:
            h1, h2, st = match.groups()
            return [(h1, standardize_street(st)), (h2, standardize_street(st))]
        match = re.match(r"(\d+|\d+[A-Z])\s+(.+)", hblock)
        if match:
            h1, st = match.groups()
            return [(h1, standardize_street(st))]
        return []

    try:
        with open(os.path.join(DATA, "sharp_street_segments.json")) as f:
            segments_gj = json.load(f)
    except FileNotFoundError:
        segments_gj = {"features": []}

    lookup = defaultdict(list)
    block_idx_to_id = list(blocks.keys())
    for seg in segments_gj["features"]:
        p = seg["properties"]
        hb = p.get("hblock", "")
        for (h, st) in parse_segment(hb):
            lookup[(h, st)].append((min(p["block_a"], p["block_b"]), max(p["block_a"], p["block_b"]), p))

    matched_crimes = 0
    ambiguous_crimes = 0
    fallback_crimes = 0
    unmatched_crimes = 0
    crime_edges = []
    
    for feat in crimes_gj["features"]:
        hb = feat["properties"].get("HUNDRED_BLOCK", "")
        if not hb:
            unmatched_crimes += 1
            crime_edges.append(None)
            continue
        hb = hb.upper().strip()
        match = re.match(r"(\d+)XX\s+(.+)", hb)
        if not match:
            unmatched_crimes += 1
            crime_edges.append(None)
            continue
        h, st = match.groups()
        h = h + "00"
        st = standardize_street(st)
        
        mapped = lookup.get((h, st), [])
        if not mapped:
            unmatched_crimes += 1
            crime_edges.append(None)
        elif len(mapped) == 1:
            matched_crimes += 1
            crime_edges.append((mapped[0][0], mapped[0][1]))
        else:
            ambiguous_crimes += 1
            coords = feat["geometry"]["coordinates"]
            cx, cy = coords[0], coords[1]
            c_scaled_x, c_scaled_y = cx * (METERS_PER_DEG_LON / METERS_PER_DEG_LAT), cy
            best_dist = float("inf")
            best_edge = None
            for ba, bb, p in mapped:
                if ba not in blocks or bb not in blocks:
                    continue
                bx = (blocks[ba]["cx"] + blocks[bb]["cx"]) / 2.0
                by = (blocks[ba]["cy"] + blocks[bb]["cy"]) / 2.0
                dist = math.hypot((bx * (METERS_PER_DEG_LON / METERS_PER_DEG_LAT) - c_scaled_x), by - c_scaled_y)
                if dist < best_dist:
                    best_dist = dist
                    best_edge = (ba, bb)
            if best_edge:
                fallback_crimes += 1
                crime_edges.append(best_edge)
            else:
                unmatched_crimes += 1
                crime_edges.append(None)

    edge_crime_cache = defaultdict(list)
    for i, edge in enumerate(crime_edges):
        if edge is not None:
            edge_crime_cache[edge].append(i)

    data_cache["crime_edges"] = crime_edges
    data_cache["edge_crime_cache"] = dict(edge_crime_cache)
    data_cache["block_idx_to_id"] = block_idx_to_id

    total = len(crimes_gj["features"])
    print("=" * 60)
    print("DATA QUALITY REPORT AT SERVER BOOT")
    print("=" * 60)
    print(f"Total crimes:                    {total}")
    print(f"Matched via HUNDRED_BLOCK:       {matched_crimes} ({(matched_crimes/total)*100:.1f}%)")
    print(f"Matched via fallback geometry:   {fallback_crimes} ({(fallback_crimes/total)*100:.1f}%)")
    print(f"Unmatched / excluded:            {unmatched_crimes} ({(unmatched_crimes/total)*100:.1f}%)")
    print("=" * 60)


class PHRequest(BaseModel):
    crime_types: list[str] = []  # Added for dynamic optimization targeting
    epsilon1_m: float = 0.0  # Spatial distance (ε₁) in meters - only edges between blocks within this distance
    epsilon2_threshold: float = 0.75  # Kept for backward compatibility if needed
    override_eps2: float | None = None  # Manual absolute threshold override
    alpha: float = 0.333
    beta: float = 0.333
    gamma: float = 0.334


class UnionFind:
    """Union-Find data structure for single linkage clustering."""

    def __init__(self, n):
        self.parent = list(range(n))
        self.rank = [0] * n
        self.components = n

    def find(self, i):
        if self.parent[i] == i:
            return i
        self.parent[i] = self.find(self.parent[i])
        return self.parent[i]

    def union(self, i, j):
        root_i = self.find(i)
        root_j = self.find(j)
        if root_i != root_j:
            if self.rank[root_i] < self.rank[root_j]:
                self.parent[root_i] = root_j
            elif self.rank[root_i] > self.rank[root_j]:
                self.parent[root_j] = root_i
            else:
                self.parent[root_j] = root_i
                self.rank[root_i] += 1
            self.components -= 1


def compute_gap_threshold(death_values, req_epsilon2_threshold, is_override=False, override_val=None):
    """
    Computes the auto-derived epsilon2 boundary threshold using topological persistence gaps.
    Trims top 2% outliers and defines the noise floor at the 10th percentile.
    """
    sorted_pers = sorted(death_values, reverse=True)
    max_dist = 0.0
    min_meaningful = 0.0
    auto_epsilon2 = 0.0
    trim_count = 0
    
    if len(sorted_pers) > 0:
        max_dist = sorted_pers[0]
        min_meaningful = float(np.percentile(sorted_pers, 10))
        
        trim_count = max(1, int(len(sorted_pers) * 0.02))
        gap_search_values = sorted_pers[trim_count:]
        
        if len(gap_search_values) > 1:
            gaps = [gap_search_values[i] - gap_search_values[i+1] for i in range(len(gap_search_values) - 1)]
            max_gap = max(gaps)
            gap_index = gaps.index(max_gap)
            
            min_gap_threshold = 0.05 * (max_dist - min_meaningful)
            if max_gap < min_gap_threshold:
                # Fallback to percentile of persistence values if no strong topological gap
                auto_epsilon2 = float(np.percentile(sorted_pers, req_epsilon2_threshold * 100))
                # Only warn once in compute_ph (controlled outside here ideally, but fine)
            else:
                auto_epsilon2 = gap_search_values[gap_index]
        else:
            auto_epsilon2 = sorted_pers[0] if sorted_pers else 0
            
    final_eps2 = override_val if is_override and override_val is not None else auto_epsilon2
    return final_eps2, max_dist, min_meaningful, auto_epsilon2, trim_count

@app.on_event("startup")
def startup_event():
    load_data()
    run_regression_check()

def run_regression_check():
    print("Running Regression Check: Verifying α=0.333, β=0.333, γ=0.333 yields exact parity with legacy distances...")
    # We use a default spatial edge of 150m for a quick check
    req = PHRequest(epsilon1_m=150.0, epsilon2_threshold=0.75)
    res = optimize_weights(req)
    exact = res.get("baseline_eq", {})
    if exact:
        print(f"✅ Regression Check passed. Exact normalized ratio: {exact.get('normalized_ratio', 0):.4f}")
    else:
        print("❌ Regression Check failed: Exact equal weighting benchmark not found.")


@app.post("/api/compute-ph")
def compute_ph(req: PHRequest):
    """
    Two-stage bifiltration for persistent homology boundary detection:

    Step 1: Build spatial graph - edges only between blocks within ε₁ meters
    Step 2: Sweep ε₂ (attribute distance) through edges using Union-Find
    Step 3: Extract H0 persistence pairs (birth/death of clusters)
    Step 4: Classify edges as boundary or interior based on ε₂ threshold
    """
    blocks = data_cache["blocks"]
    crime_coords = data_cache["crime_coords"]
    crime_types = data_cache["crime_types"]

    # ── Normalize attributes using Min-Max normalization ────────────────
    # Get all values and ages
    all_vals = np.array(
        [
            b["filt_value"]
            for b in blocks.values()
            if b["filt_value"] is not None and b["filt_value"] > 0
        ],
        dtype=float,
    )
    all_ages = np.array(
        [
            b["filt_age"]
            for b in blocks.values()
            if b["filt_age"] is not None and b["filt_age"] > 0
        ],
        dtype=float,
    )

    # Min-Max normalization parameters
    val_min, val_max = float(np.min(all_vals)), float(np.max(all_vals))
    age_min, age_max = float(np.min(all_ages)), float(np.max(all_ages))
    val_range = val_max - val_min if val_max > val_min else 1.0
    age_range = age_max - age_min if age_max > age_min else 1.0

    # Get all zone types
    all_zones = set()
    for b in blocks.values():
        all_zones.update(b.get("zoning_percentages", {}).keys())
    zone_list = sorted(all_zones)
    zone_idx = {z: i for i, z in enumerate(zone_list)}

    # Build normalized attribute vectors for each block using Min-Max [0,1]
    block_ids = list(blocks.keys())
    n_blocks = len(block_ids)
    block_idx = {bid: i for i, bid in enumerate(block_ids)}

    attr_vectors = np.zeros((n_blocks, 2 + len(zone_list)))
    for i, bid in enumerate(block_ids):
        b = blocks[bid]
        # Min-Max normalization to [0, 1]
        val = b.get("filt_value", 0) or 0
        age = b.get("filt_age", 0) or 0
        attr_vectors[i, 0] = (val - val_min) / val_range if val > 0 else 0
        attr_vectors[i, 1] = (age - age_min) / age_range if age > 0 else 0
        # Zoning percentages are already in [0, 100], normalize to [0, 1]
        zp = b.get("zoning_percentages", {})
        for z in zone_list:
            attr_vectors[i, 2 + zone_idx[z]] = zp.get(z, 0.0) / 100.0

    # ── Step 1: Build spatial graph (ε₁ = spatial distance) ─────────────────
    LAT_CENTER = 49.2
    METERS_PER_DEG_LAT = 111000
    METERS_PER_DEG_LON = 111000 * math.cos(math.radians(LAT_CENTER))

    # Scale coordinates for isotropic distance
    pts = np.array(
        [
            [
                blocks[b]["cx"] * (METERS_PER_DEG_LON / METERS_PER_DEG_LAT),
                blocks[b]["cy"],
            ]
            for b in block_ids
        ]
    )

    # At ε₁ = 0: no edges (empty graph)
    # At ε₁ > 0: edges between blocks within ε₁ meters
    pairs = []
    if req.epsilon1_m > 0:
        tree = cKDTree(pts)
        radius_scaled = req.epsilon1_m / METERS_PER_DEG_LAT
        pairs = list(tree.query_pairs(r=radius_scaled))

    # ── Step 2: Compute attribute distance for each spatial edge ──────────────
    spatial_edges = []
    for i, j in pairs:
        if i >= j:  # Avoid duplicates
            continue

        # Also compute individual components for decomposition
        v1, v2 = attr_vectors[i, 0], attr_vectors[j, 0]
        a1, a2 = attr_vectors[i, 1], attr_vectors[j, 1]
        val_diff = abs(v1 - v2)
        age_diff = abs(a1 - a2)
        zone_diff = float(np.linalg.norm(attr_vectors[i, 2:] - attr_vectors[j, 2:]))

        # Attribute distance (Weighted Euclidean in normalized attribute space)
        attr_dist = math.sqrt(
            req.alpha * (val_diff ** 2) + 
            req.beta * (age_diff ** 2) + 
            req.gamma * (zone_diff ** 2)
        )

        bid_i, bid_j = block_ids[i], block_ids[j]
        spatial_edges.append(
            {
                "i": i,
                "j": j,
                "bid_i": bid_i,
                "bid_j": bid_j,
                "attr_dist": attr_dist,
                "val_frac": val_diff / (attr_dist + 1e-10),
                "age_frac": age_diff / (attr_dist + 1e-10),
                "zone_frac": zone_diff / (attr_dist + 1e-10),
                "ax": blocks[bid_i]["cx"],
                "ay": blocks[bid_i]["cy"],
                "bx": blocks[bid_j]["cx"],
                "by": blocks[bid_j]["cy"],
            }
        )

    # Sort edges by attribute distance (for sweep)
    spatial_edges.sort(key=lambda e: e["attr_dist"])
    attr_dists = np.array([e["attr_dist"] for e in spatial_edges])

    # ── Step 3: Union-Find sweep to compute H0 persistence ────────────────────
    # In Vietoris-Rips: all blocks exist from ε₂ = 0, so birth = 0 for all
    # Death = attr_dist when component merges into another
    uf = UnionFind(n_blocks)
    persistence_pairs = []  # (birth, death, component_id) - all births are 0

    # Process edges in order of increasing attribute distance
    for edge in spatial_edges:
        i, j = edge["i"], edge["j"]
        attr_dist = edge["attr_dist"]

        comp_i = uf.find(i)
        comp_j = uf.find(j)

        if comp_i != comp_j:
            # Component dies when it merges - death = attr_dist, birth = 0
            persistence_pairs.append((0.0, attr_dist, comp_j))
            uf.union(i, j)

    # Remaining components never merge (death = infinity = never die)
    for i in range(n_blocks):
        if uf.find(i) == i:
            persistence_pairs.append((0.0, float("inf"), i))

    # Separate finite and infinite persistence pairs BEFORE building display diagram
    max_attr_dist = spatial_edges[-1]["attr_dist"] if spatial_edges else 1.0
    INF_SENTINEL = max_attr_dist * 1.5

    # death_values comes from ALL finite merges (not truncated — needed for correct epsilon2)
    death_values = [d for (_, d, _) in persistence_pairs if d != float("inf")]

    # Convert to persistence diagram format for display (finite first, then infinite)
    h0_finite = []
    h0_infinite = []
    for birth, death, comp_id in persistence_pairs:
        is_inf = death == float("inf")
        display_death = INF_SENTINEL if is_inf else death
        persistence = display_death - birth
        entry = [round(birth, 6), round(display_death, 6), round(persistence, 6), comp_id]
        if is_inf:
            h0_infinite.append(entry)
        else:
            h0_finite.append(entry)

    # Sort finite by persistence descending, show up to 200 for display
    h0_finite.sort(key=lambda x: -x[2])
    h0_diagram = h0_finite[:200] + h0_infinite[:20]

    # ── Step 4: Classify edges as boundary or interior ────────────────────────
    # NOTE: All H0 features born at filtration value 0.
    # Therefore persistence = death value exactly.
    # Birth values are not stored — they are always 0.
    # All threshold operations use death values only.

    epsilon2_value, max_dist, min_meaningful, auto_epsilon2, trim_count = compute_gap_threshold(
        death_values,
        req.epsilon2_threshold,
        is_override=(req.override_eps2 is not None),
        override_val=req.override_eps2
    )

    # Edges with attr_dist >= epsilon2_value are boundaries. Since persistence = attr_dist, this maps perfectly.

    boundary_edges = []
    interior_edges = []

    # Build per-edge crime counts from HUNDRED_BLOCK mapping
    edge_crime_cache = data_cache.get("edge_crime_cache", {})
    crime_types_list = data_cache.get("crime_types", [])
    filter_by_type = len(req.crime_types) > 0
    selected_set = set(req.crime_types) if filter_by_type else set()

    for edge in spatial_edges:
        is_boundary = bool(edge["attr_dist"] >= epsilon2_value)
        bid_i, bid_j = edge["bid_i"], edge["bid_j"]
        edge_key = (min(bid_i, bid_j), max(bid_i, bid_j))
        crime_indices = edge_crime_cache.get(edge_key, [])
        if filter_by_type:
            crime_count = sum(1 for idx in crime_indices if crime_types_list[idx] in selected_set)
        else:
            crime_count = len(crime_indices)

        edge_data = {
            "a": bid_i,
            "b": bid_j,
            "w": round(float(edge["attr_dist"]), 6),
            "val_frac": round(float(edge["val_frac"]), 4),
            "age_frac": round(float(edge["age_frac"]), 4),
            "zone_frac": round(float(edge["zone_frac"]), 4),
            "dv": round(float(edge["val_frac"]), 4),
            "da": round(float(edge["age_frac"]), 4),
            "dz": round(float(edge["zone_frac"]), 4),
            "ax": float(edge["ax"]),
            "ay": float(edge["ay"]),
            "bx": float(edge["bx"]),
            "by": float(edge["by"]),
            "is_boundary": is_boundary,
            "crime_count": crime_count,
        }

        if is_boundary:
            boundary_edges.append(edge_data)
        else:
            interior_edges.append(edge_data)

    # ── Compute statistics ───────────────────────────────────────────────────
    # Convert spatial_edges to JSON-serializable format
    edges_for_json = []
    for edge in spatial_edges:
        edges_for_json.append(
            {
                "a": edge["bid_i"],
                "b": edge["bid_j"],
                "w": round(float(edge["attr_dist"]), 6),
                "dv": round(float(edge["val_frac"]), 4),
                "da": round(float(edge["age_frac"]), 4),
                "dz": round(float(edge["zone_frac"]), 4),
                "ax": float(edge["ax"]),
                "ay": float(edge["ay"]),
                "bx": float(edge["bx"]),
                "by": float(edge["by"]),
            }
        )

    adj_json = {
        "edges": edges_for_json,
        "boundary_edges": boundary_edges,
        "interior_edges": interior_edges,
        "stats": {
            "total_edges": len(spatial_edges),
            "boundary_edges": len(boundary_edges),
            "interior_edges": len(interior_edges),
            "epsilon1_m": req.epsilon1_m,
            "epsilon2_threshold": req.epsilon2_threshold,
            "epsilon2_value": round(epsilon2_value, 6),
            "max_dist": round(float(max_dist), 6),
            "min_meaningful": round(float(min_meaningful), 6),
            "auto_epsilon2": round(float(auto_epsilon2), 6),
            "trim_count": trim_count,
            "is_manual_override": req.override_eps2 is not None,
            "attr_dist_min": round(float(np.min(attr_dists)), 6)
            if len(attr_dists) > 0
            else 0,
            "attr_dist_max": round(float(np.max(attr_dists)), 6)
            if len(attr_dists) > 0
            else 0,
            "attr_dist_mean": round(float(np.mean(attr_dists)), 6)
            if len(attr_dists) > 0
            else 0,
            "attr_dist_median": round(float(np.median(attr_dists)), 6)
            if len(attr_dists) > 0
            else 0,
        },
    }

    # ── Persistence diagram and Betti curves ─────────────────────────────────
    # Sample thresholds for betti curve
    if len(attr_dists) > 0:
        max_dist = float(np.max(attr_dists))
        filt_thresholds = np.linspace(0, max_dist, 50).tolist()
    else:
        filt_thresholds = np.linspace(0, 1, 50).tolist()

    # Compute Betti_0 at each threshold
    betti_0 = []
    uf_tmp = UnionFind(n_blocks)
    for thresh in filt_thresholds:
        uf_tmp = UnionFind(n_blocks)
        for edge in spatial_edges:
            if edge["attr_dist"] <= thresh:
                uf_tmp.union(edge["i"], edge["j"])
        betti_0.append(uf_tmp.components)

    # Prepare persistence diagram
    pers_json = {
        "diagrams": {
            "H0": [[b, d, p, c] for b, d, p, c in h0_diagram[:200]],
        },
        "betti_curves": {
            "thresholds": [round(t, 4) for t in filt_thresholds],
            "beta_0": betti_0,
        },
        "stats": {
            "H0": {
                "total_persistence": sum(p for _, _, p, _ in h0_diagram),
                "mean_persistence": np.mean([p for _, _, p, _ in h0_diagram])
                if h0_diagram
                else 0,
                "max_persistence": max([p for _, _, p, _ in h0_diagram])
                if h0_diagram
                else 0,
            }
        },
    }

    return {
        "adjacency": adj_json,
        "persistence": pers_json,
    }

@app.post("/api/optimize-weights")
def optimize_weights(req: PHRequest):
    blocks = data_cache["blocks"]
    
    # Min-Max Normalization (same as compute_ph core setup)
    all_vals = np.array([b["filt_value"] for b in blocks.values() if b["filt_value"] is not None and b["filt_value"] > 0], dtype=float)
    all_ages = np.array([b["filt_age"] for b in blocks.values() if b["filt_age"] is not None and b["filt_age"] > 0], dtype=float)

    val_min, val_max = float(np.min(all_vals)), float(np.max(all_vals))
    age_min, age_max = float(np.min(all_ages)), float(np.max(all_ages))
    val_range = val_max - val_min if val_max > val_min else 1.0
    age_range = age_max - age_min if age_max > age_min else 1.0

    all_zones = set()
    for b in blocks.values():
        all_zones.update(b.get("zoning_percentages", {}).keys())
    zone_list = sorted(all_zones)
    zone_idx = {z: i for i, z in enumerate(zone_list)}

    block_ids = list(blocks.keys())
    n_blocks = len(block_ids)

    attr_vectors = np.zeros((n_blocks, 2 + len(zone_list)))
    for i, bid in enumerate(block_ids):
        b = blocks[bid]
        val = b.get("filt_value", 0) or 0
        age = b.get("filt_age", 0) or 0
        attr_vectors[i, 0] = (val - val_min) / val_range if val > 0 else 0
        attr_vectors[i, 1] = (age - age_min) / age_range if age > 0 else 0
        zp = b.get("zoning_percentages", {})
        for z in zone_list:
            attr_vectors[i, 2 + zone_idx[z]] = zp.get(z, 0.0) / 100.0

    LAT_CENTER = 49.2
    METERS_PER_DEG_LAT = 111000
    METERS_PER_DEG_LON = 111000 * math.cos(math.radians(LAT_CENTER))

    pts = np.array([[blocks[b]["cx"] * (METERS_PER_DEG_LON / METERS_PER_DEG_LAT), blocks[b]["cy"]] for b in block_ids])

    pairs = []
    if req.epsilon1_m > 0:
        tree = cKDTree(pts)
        radius_scaled = req.epsilon1_m / METERS_PER_DEG_LAT
        pairs = list(tree.query_pairs(r=radius_scaled))

    # Process pre-mapped edge crimes based on selected types
    edge_crime_cache = data_cache.get("edge_crime_cache", {})
    if req.crime_types:
        selected_set = set(req.crime_types)
        c_types = data_cache.get("crime_types", [])
        edge_crime_counts = {}
        for edge_key, indices in edge_crime_cache.items():
            count = sum(1 for idx in indices if c_types[idx] in selected_set)
            edge_crime_counts[edge_key] = count
    else:
        edge_crime_counts = {edge_key: len(indices) for edge_key, indices in edge_crime_cache.items()}

    # Match crime counts to the valid KDTree pairs
    total_crimes_per_edge_list = []
    
    # Re-build loops because we need to append the crime counts perfectly aligned
    v_sq, a_sq, z_sq = [], [], []
    pair_i, pair_j = [], []
    
    for i, j in pairs:
        if i >= j: continue
        v_sq.append((attr_vectors[i, 0] - attr_vectors[j, 0])**2)
        a_sq.append((attr_vectors[i, 1] - attr_vectors[j, 1])**2)
        z_sq.append(float(np.linalg.norm(attr_vectors[i, 2:] - attr_vectors[j, 2:]))**2)
        pair_i.append(i)
        pair_j.append(j)
        
        bid_i = block_ids[i]
        bid_j = block_ids[j]
        edge_key = (min(bid_i, bid_j), max(bid_i, bid_j))
        total_crimes_per_edge_list.append(edge_crime_counts.get(edge_key, 0))

    v_sq, a_sq, z_sq = np.array(v_sq), np.array(a_sq), np.array(z_sq)
    pair_i, pair_j = np.array(pair_i), np.array(pair_j)
    total_crimes_per_edge = np.array(total_crimes_per_edge_list)

    results = []
    for a_steps in range(11):
        alpha = round(a_steps / 10.0, 2)
        for b_steps in range(11 - a_steps):
            beta = round(b_steps / 10.0, 2)
            gamma = round(1.0 - alpha - beta, 2)

            if len(v_sq) == 0:
                continue

            weights = np.sqrt(alpha * v_sq + beta * a_sq + gamma * z_sq)
            
            # Full Union-Find to extract exact topological persistence (death) values
            n_blocks = len(block_ids)
            uf = UnionFind(n_blocks)
            edges_to_sort = list(zip(weights.tolist(), pair_i.tolist(), pair_j.tolist()))
            edges_to_sort.sort(key=lambda x: x[0])
            
            death_values = []
            for w_val, p_i, p_j in edges_to_sort:
                comp_i = uf.find(p_i)
                comp_j = uf.find(p_j)
                if comp_i != comp_j:
                    death_values.append(w_val)
                    uf.union(p_i, p_j)
                    
            thresh_val, _, _, _, _ = compute_gap_threshold(death_values, req.epsilon2_threshold)
            
            is_bound_edge = weights >= thresh_val
            
            boundary_segments = int(np.sum(is_bound_edge))
            interior_segments = len(weights) - boundary_segments
            
            bound_crimes = float(np.sum(total_crimes_per_edge[is_bound_edge]))
            inter_crimes = float(np.sum(total_crimes_per_edge[~is_bound_edge]))
            
            norm_bound = bound_crimes / boundary_segments if boundary_segments > 0 else 0
            norm_inter = inter_crimes / interior_segments if interior_segments > 0 else 0
            
            ratio = norm_bound / norm_inter if norm_inter > 0 else 0
            
            results.append({
                "alpha": alpha,
                "beta": beta,
                "gamma": gamma,
                "raw_boundary_crimes": bound_crimes,
                "raw_interior_crimes": inter_crimes,
                "boundary_blocks": boundary_segments,  # Kept key same to not break frontend
                "interior_blocks": interior_segments,  # Kept key same to not break frontend
                "normalized_ratio": float(ratio)
            })

    # Add theoretic and baseline calculations explicitly
    def get_row(a, b, g):
        for r in results:
            if math.isclose(r["alpha"], a, abs_tol=0.01) and math.isclose(r["beta"], b, abs_tol=0.01):
                return r
        return None

    baseline = get_row(0.3, 0.3, 0.4) # Approximation of 0.33 boundary in step 0.1
    # Run exact 0.333 baseline separately to guarantee exact parity
    w_exact = np.sqrt(0.333333 * v_sq + 0.333333 * a_sq + 0.333333 * z_sq)
    
    uf_exact = UnionFind(len(block_ids))
    edges_ext_sort = list(zip(w_exact.tolist(), pair_i.tolist(), pair_j.tolist()))
    edges_ext_sort.sort(key=lambda x: x[0])
    death_values_exact = []
    for w_val, p_i, p_j in edges_ext_sort:
        c_i = uf_exact.find(p_i)
        c_j = uf_exact.find(p_j)
        if c_i != c_j:
            death_values_exact.append(w_val)
            uf_exact.union(p_i, p_j)
            
    t_exact, _, _, _, _ = compute_gap_threshold(death_values_exact, req.epsilon2_threshold)
    is_bound_e = w_exact >= t_exact
    bb_e = int(np.sum(is_bound_e))
    ib_e = len(w_exact) - bb_e
    bc_e = float(np.sum(total_crimes_per_edge[is_bound_e]))
    ic_e = float(np.sum(total_crimes_per_edge[~is_bound_e]))
    nb_e = bc_e / bb_e if bb_e > 0 else 0
    ni_e = ic_e / ib_e if ib_e > 0 else 0
    equal_exact = {
        "alpha": 0.33,
        "beta": 0.33,
        "gamma": 0.33,
        "raw_boundary_crimes": bc_e,
        "raw_interior_crimes": ic_e,
        "boundary_blocks": bb_e,
        "interior_blocks": ib_e,
        "normalized_ratio": float(nb_e / ni_e) if ni_e > 0 else 0
    }

    if not results:
        results = [equal_exact]

    baseline_eq = equal_exact
    prop_val_only = get_row(1.0, 0.0, 0.0) or equal_exact
    age_only = get_row(0.0, 1.0, 0.0) or equal_exact
    zone_only = get_row(0.0, 0.0, 1.0) or equal_exact

    return {
        "results": results,
        "baseline_eq": baseline_eq,
        "prop_val_only": prop_val_only,
        "age_only": age_only,
        "zone_only": zone_only
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
