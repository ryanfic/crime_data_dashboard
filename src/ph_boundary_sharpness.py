"""
Persistent Homology Analysis of Sharp Urban Socioeconomic Boundaries
=====================================================================
Mathematical Framework
-----------------------
We construct a scalar sharpness field  f : ℝ² → ℝ  over the study area by:
  1. Computing a multivariate attribute-contrast weight  w(A,B) for each
     pair of adjacent city blocks A and B.
  2. Rasterising the weights onto a 2D grid, producing the scalar field f.
  3. Running superlevel-set cubical persistent homology on f:
         H_k of the superlevel filtration  {x : f(x) ≥ α}  as α decreases.
     •  H0 features (birth, death): connected *components* of high-sharpness
        boundary regions — each is a contiguous zone where f ≥ birth until it
        merges with another component at α = death.
     •  H1 features (birth, death): topological *loops* in the high-sharpness
        field — sharp boundaries that fully encircle an interior neighbourhood.

Boundary sharpness weight (Euclidean in 3-component feature space):
    w = √( Δv² + Δa² + Δz² )
  where Δv = min-max normalised property-value contrast,
        Δa = min-max normalised building-age contrast,
        Δz = L2 zoning-fraction distance between adjacent blocks.

Cubical PH is implemented via GUDHI CubicalComplex (GUDHI library ≥ 3.0).
Superlevel filtration is achieved by negating the field (standard technique).
Representative H1 cycles are extracted via largest-component iso-contours at
the midpoint threshold — the accepted approach for cubical PH visualization
(Robins 2000; Gyulassy et al. 2012).

Outputs (→ dashboard/web_dashboard/public/data/):
  ph_adjacency.json       – edges with sharpness weights
  ph_sharpness_grid.json  – rasterised sharpness field
  ph_persistence.json     – persistence diagrams, Betti curves, PH statistics
  ph_boundary_crimes.json – crime counts near sharp vs. interior boundaries

References:
  Edelsbrunner & Zomorodian (2002) Computing persistent homology.
  Zomorodian & Carlsson (2005) Computing persistent homology. Discrete Comput. Geom.
  GUDHI library: https://gudhi.inria.fr/
"""

import json, os, sys, math
import numpy as np
from collections import defaultdict
from scipy.spatial import cKDTree, ConvexHull
from scipy.ndimage import gaussian_filter
from shapely.geometry import shape, Point, LineString, MultiLineString
import gudhi

# ── Paths ────────────────────────────────────────────────────────────────────
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'dashboard', 'web_dashboard', 'public', 'data')
OUT  = DATA  # write output JSON alongside existing data files

# ── 1.  Load block + property + crime data ───────────────────────────────────
print("=" * 65)
print("  PERSISTENT HOMOLOGY – SHARP BOUNDARY ANALYSIS")
print("=" * 65)

print("\n[1/8] Loading blocks …")
with open(os.path.join(DATA, 'blocks.json')) as f:
    blocks_gj = json.load(f)
with open(os.path.join(DATA, 'properties.json')) as f:
    props_gj = json.load(f)
with open(os.path.join(DATA, 'crimes.json')) as f:
    crimes_gj = json.load(f)

# Parse blocks
blocks = {}
for feat in blocks_gj['features']:
    p = feat['properties']
    geom = shape(feat['geometry'])
    if not geom.is_valid:
        geom = geom.buffer(0)
    
    # Calculate mathematically accurate center of mass for properties
    c = geom.centroid
    
    blocks[p['block_id']] = {
        'geom': geom,
        'avg_value': p.get('avg_value', 0),
        'avg_age': p.get('avg_age', 0),
        'crime_count': p.get('crime_count', 0),
        'property_count': p.get('property_count', 0),
        'neighbors': p.get('neighbors', []),
        'zoning_percentages': p.get('zoning_percentages', {}),
        'cx': c.x, 'cy': c.y,
    }
print(f"  {len(blocks)} blocks loaded")

# Per-block property-level stats (for SD filtering like the dashboard)
block_props = defaultdict(lambda: {'values': [], 'ages': []})
for feat in props_gj['features']:
    p = feat['properties']
    bid = p.get('block_id')
    if bid is None:
        continue
    if p.get('property_value', 0) > 0:
        block_props[bid]['values'].append(p['property_value'])
    if p.get('building_age', 0) > 0:
        block_props[bid]['ages'].append(p['building_age'])

def filtered_mean(vals, sd_thresh=1.3):
    """Compute mean after removing outliers beyond sd_thresh SDs."""
    if len(vals) < 2:
        return np.mean(vals) if vals else 0.0
    m, s = np.mean(vals), np.std(vals)
    filt = [v for v in vals if abs(v - m) <= sd_thresh * s] if s > 0 else vals
    return float(np.mean(filt)) if filt else float(m)

# Compute filtered means for each block
for bid in blocks:
    bp = block_props.get(bid, {'values': [], 'ages': []})
    if bp['values']:
        blocks[bid]['filt_value'] = filtered_mean(bp['values'])
    else:
        blocks[bid]['filt_value'] = blocks[bid]['avg_value']
    if bp['ages']:
        blocks[bid]['filt_age'] = filtered_mean(bp['ages'])
    else:
        blocks[bid]['filt_age'] = blocks[bid]['avg_age']

# Crime coordinates
crime_coords = []
crime_types = []
for feat in crimes_gj['features']:
    coords = feat['geometry']['coordinates']
    crime_coords.append([coords[0], coords[1]])
    crime_types.append(feat['properties'].get('TYPE', 'Unknown'))
crime_coords = np.array(crime_coords)
print(f"  {len(crime_coords)} crime incidents loaded")

# ── 2.  Adjacency graph + boundary sharpness weights ────────────────────────
print("\n[2/8] Building adjacency graph and sharpness weights …")

# Normalise value and age across all blocks using Min-Max [0, 1] scaling
all_vals = np.array([b['filt_value'] for b in blocks.values() if b['filt_value'] is not None and b['filt_value'] > 0], dtype=float)
all_ages = np.array([b['filt_age'] for b in blocks.values() if b['filt_age'] is not None and b['filt_age'] > 0], dtype=float)

val_min, val_max = (float(np.min(all_vals)), float(np.max(all_vals))) if len(all_vals) > 0 else (0.0, 1.0)
age_min, age_max = (float(np.min(all_ages)), float(np.max(all_ages))) if len(all_ages) > 0 else (0.0, 1.0)
val_span = max(val_max - val_min, 1e-9)
age_span = max(age_max - age_min, 1e-9)

edges = []
edge_set = set()
total_neighbors = sum(len(info['neighbors']) for info in blocks.values())
processed = 0

for bid, info in blocks.items():
    for nb in info['neighbors']:
        if nb not in blocks:
            continue
        key = (min(bid, nb), max(bid, nb))
        if key in edge_set:
            continue
        edge_set.add(key)

        # Min-Max Attribute Contrast [0, 1]
        v1_raw = blocks[bid]['filt_value'] or val_min
        v2_raw = blocks[nb]['filt_value'] or val_min
        a1_raw = blocks[bid]['filt_age'] or age_min
        a2_raw = blocks[nb]['filt_age'] or age_min
        
        v1 = (v1_raw - val_min) / val_span
        v2 = (v2_raw - val_min) / val_span
        a1 = (a1_raw - age_min) / age_span
        a2 = (a2_raw - age_min) / age_span
        
        dv = v1 - v2
        da = a1 - a2

        # Categorical zoning distance (L2 norm)
        zp1 = blocks[bid]['zoning_percentages']
        zp2 = blocks[nb]['zoning_percentages']
        all_zones = set(zp1.keys()).union(set(zp2.keys()))
        dz_sq = 0.0
        for z in all_zones:
            p1 = zp1.get(z, 0.0) / 100.0
            p2 = zp2.get(z, 0.0) / 100.0
            dz_sq += (p1 - p2) ** 2
        dz = math.sqrt(dz_sq)

        w = math.sqrt(dv ** 2 + da ** 2 + dz ** 2)

        # OPTIMIZED: Skip expensive polygon intersection - not used in weight calculation
        # shared_len was computed via intersection() but never used in analysis
        # Set to 0 for compatibility with existing data structure
        shared_len = 0.0

        edges.append({
            'a': bid, 'b': nb,
            'w': round(w, 6),
            'dv': round(abs(dv), 6),
            'da': round(abs(da), 6),
            'dz': round(dz, 6),
            'shared_len': round(shared_len, 8),
            'ax': blocks[bid]['cx'], 'ay': blocks[bid]['cy'],
            'bx': blocks[nb]['cx'], 'by': blocks[nb]['cy'],
        })
        
        processed += 1
        if processed % 1000 == 0:
            print(f"    Processed {processed}/{total_neighbors//2} edges...")

w_vals = np.array([e['w'] for e in edges])
w_median = float(np.median(w_vals))
w_p75 = float(np.percentile(w_vals, 75))
w_p90 = float(np.percentile(w_vals, 90))

sharp_edges = [e for e in edges if e['w'] >= w_p75]
sharp_block_ids = set()
for e in sharp_edges:
    sharp_block_ids.add(e['a'])
    sharp_block_ids.add(e['b'])

print(f"  {len(edges)} total edges, {len(sharp_edges)} sharp (≥ p75 = {w_p75:.4f})")
print(f"  {len(sharp_block_ids)} blocks adjacent to a sharp boundary")

# Export adjacency JSON
adj_json = {
    'edges': edges,
    'stats': {
        'total_edges': len(edges),
        'sharp_edges': len(sharp_edges),
        'w_median': round(w_median, 6),
        'w_p75': round(w_p75, 6),
        'w_p90': round(w_p90, 6),
    }
}
with open(os.path.join(OUT, 'ph_adjacency.json'), 'w') as f:
    json.dump(adj_json, f)
print("  → ph_adjacency.json saved")

# ── 3.  Rasterise boundary sharpness into 2D grid ───────────────────────────
print("\n[3/8] Rasterising boundary sharpness field …")

# Bounding box (all block centroids)
all_cx = [b['cx'] for b in blocks.values()]
all_cy = [b['cy'] for b in blocks.values()]
lon_min, lon_max = min(all_cx) - 0.002, max(all_cx) + 0.002
lat_min, lat_max = min(all_cy) - 0.002, max(all_cy) + 0.002

# ~100 m pixels  (1° lat ≈ 111 km, 1° lon ≈ ~78 km at 49°N)
res_lat = 0.0009   # ~100 m
res_lon = 0.0013   # ~100 m
ny = int(np.ceil((lat_max - lat_min) / res_lat))
nx = int(np.ceil((lon_max - lon_min) / res_lon))
print(f"  Grid size: {nx} x {ny} ({nx*ny} pixels)")

grid = np.zeros((ny, nx), dtype=np.float64)

# For each edge, paint the sharpness value along the line between centroids
for e in edges:
    # Bresenham-style rasterisation
    x0, y0 = e['ax'], e['ay']
    x1, y1 = e['bx'], e['by']
    n_steps = max(2, int(max(abs(x1 - x0) / res_lon, abs(y1 - y0) / res_lat) * 1.5))
    for t in np.linspace(0, 1, n_steps):
        px = x0 + t * (x1 - x0)
        py = y0 + t * (y1 - y0)
        col = int((px - lon_min) / res_lon)
        row = int((py - lat_min) / res_lat)
        if 0 <= row < ny and 0 <= col < nx:
            grid[row, col] = max(grid[row, col], e['w'])

# Light Gaussian smooth for numerical stability (σ = 1 pixel)
grid_smooth = gaussian_filter(grid, sigma=1.0)

# Export rasterised grid
grid_json = {
    'nx': nx, 'ny': ny,
    'lon_min': lon_min, 'lon_max': lon_max,
    'lat_min': lat_min, 'lat_max': lat_max,
    'res_lon': res_lon, 'res_lat': res_lat,
    'values': grid_smooth.tolist(),
}
with open(os.path.join(OUT, 'ph_sharpness_grid.json'), 'w') as f:
    json.dump(grid_json, f)
print("  → ph_sharpness_grid.json saved")

# ── 4.  Cubical Persistent Homology via GUDHI ───────────────────────────────
print("\n[4/8] Computing cubical persistent homology (GUDHI) …")

# Superlevel set filtration: negate the field so sublevel = superlevel
neg_grid = -grid_smooth.copy()
# Replace zeros with a high value (background should die immediately)
neg_grid[grid_smooth == 0] = 0.0  # background gets birth at 0

# GUDHI CubicalComplex
cc = gudhi.CubicalComplex(
    dimensions=[ny, nx],
    top_dimensional_cells=neg_grid.flatten().tolist()
)
all_intervals = cc.persistence()

# Extract persistence diagrams
dgms = {0: [], 1: []}
for (dim, (birth, death)) in all_intervals:
    if dim in dgms and np.isfinite(death):
        dgms[dim].append([float(birth), float(death)])

# Convert back to superlevel (negate birth/death)
for dim in dgms:
    dgms[dim] = [[-d, -b] for b, d in dgms[dim] if b != d]
    dgms[dim].sort(key=lambda x: -(x[1] - x[0]))  # sort by persistence desc

print(f"  H0 features: {len(dgms[0])}")
print(f"  H1 features: {len(dgms[1])}")

# Extract representative H1 cycles from persistence diagram
print("\n[4b/8] Extracting representative H1 cycles …")
h1_representative_coords = []

try:
    from scipy import ndimage
    
    # Get top 20 most persistent H1 features from diagram
    top_h1 = dgms[1][:20]
    
    for i, (birth, death) in enumerate(top_h1):
        persistence = death - birth
        
        # Use a threshold between birth and death to capture the cycle region
        # Using midpoint tends to work well for cubical complexes
        threshold = (birth + death) / 2
        
        mask = grid_smooth >= threshold
        ys, xs = np.where(mask)
        
        if len(ys) < 10:  # Skip if region is too small
            continue
        
        # Label connected components
        labeled, num_features = ndimage.label(mask)
        
        # Find the largest component (most likely to be the cycle)
        largest_label = 1
        largest_size = 0
        for label_id in range(1, num_features + 1):
            size = np.sum(labeled == label_id)
            if size > largest_size:
                largest_size = size
                largest_label = label_id
        
        if largest_size < 10:
            continue
        
        # Get pixels in the largest component
        component_mask = labeled == largest_label
        ys, xs = np.where(component_mask)
        
        # Compute centroid
        center_lon = lon_min + np.mean(xs) * res_lon
        center_lat = lat_min + np.mean(ys) * res_lat
        
        # Compute exact contours of the cycle region (preserving holes)
        if len(ys) >= 3:
            try:
                from skimage import measure
                # Pad the mask to ensure closed contours at borders
                padded_mask = np.pad(component_mask, 1, mode='constant')
                # Threshold at 0.5 since mask is boolean
                contours = measure.find_contours(padded_mask, 0.5)
                
                if len(contours) > 0:
                    contours.sort(key=len, reverse=True)
                    hull_coords = []
                    
                    # Extract up to 2 contours (outer boundary + main inner hole)
                    for contour in contours[:2]:
                        if len(contour) < 5: 
                            continue
                        ring = []
                        for pt in contour:
                            # un-pad indices
                            y_idx, x_idx = pt[0] - 1, pt[1] - 1
                            lon = round(lon_min + x_idx * res_lon, 6)
                            lat = round(lat_min + y_idx * res_lat, 6)
                            ring.append([lon, lat])
                        
                        # Close the ring
                        if ring and ring[0] != ring[-1]:
                            ring.append(ring[0])
                            
                        if ring:
                            hull_coords.append(ring)
                    
                    if not hull_coords:
                        continue
                    
                    # Find cells closest to birth and death thresholds
                    birth_flat_idx = np.argmin(np.abs(grid_smooth - birth))
                    birth_row = int(birth_flat_idx // nx)
                    birth_col = int(birth_flat_idx % nx)
                    
                    death_flat_idx = np.argmin(np.abs(grid_smooth - death))
                    death_row = int(death_flat_idx // nx)
                    death_col = int(death_flat_idx % nx)
                    
                    h1_representative_coords.append({
                        'rank': i + 1,
                        'birth': round(birth, 6),
                        'death': round(death, 6),
                        'persistence': round(persistence, 6),
                        'center': [round(center_lon, 6), round(center_lat, 6)],
                        'loop_coords': hull_coords,
                        'birth_cell': [birth_col, birth_row],
                        'death_cell': [death_col, death_row],
                        'num_pixels': int(largest_size),
                    })
            except Exception:
                continue
    
    print(f"  Extracted {len(h1_representative_coords)} H1 cycles")
    
except Exception as e:
    print(f"  Warning: Could not extract cycles: {e}")
    import traceback
    traceback.print_exc()
    h1_representative_coords = []

# Compute Betti curves
max_filt = float(np.max(grid_smooth)) if np.max(grid_smooth) > 0 else 1.0
n_samples = 100
filt_thresholds = np.linspace(0, max_filt, n_samples).tolist()
betti_0 = []
betti_1 = []
for alpha in filt_thresholds:
    b0 = sum(1 for (b, d) in dgms[0] if b <= alpha < d)
    b1 = sum(1 for (b, d) in dgms[1] if b <= alpha < d)
    betti_0.append(b0)
    betti_1.append(b1)

# Compute PH-derived features for statistical modeling
print("\n[4c/8] Computing PH features for regression analysis …")

# 1. Total persistence (sum of all lifetimes)
total_pers_h0 = sum(d - b for b, d in dgms[0])
total_pers_h1 = sum(d - b for b, d in dgms[1])

# 2. Betti curve integrals (area under Betti curves)
import numpy as np
betti_0_integral = np.trapezoid(betti_0, filt_thresholds) if len(betti_0) == len(filt_thresholds) else 0
betti_1_integral = np.trapezoid(betti_1, filt_thresholds) if len(betti_1) == len(filt_thresholds) else 0

# 3. Persistence entropy (measure of complexity)
def persistence_entropy(dgm):
    """Compute persistence entropy: -sum(p_i * log(p_i)) where p_i = persistence_i / total_persistence"""
    persistences = [d - b for b, d in dgm if d > b]
    total = sum(persistences)
    if total == 0:
        return 0
    probs = [p / total for p in persistences]
    return -sum(p * math.log(p) if p > 0 else 0 for p in probs)

entropy_h0 = persistence_entropy(dgms[0])
entropy_h1 = persistence_entropy(dgms[1])

# 4. Persistence statistics
def pers_stats(dgm):
    if not dgm:
        return {'count': 0, 'total': 0, 'mean': 0, 'max': 0, 'median': 0}
    pers = [d - b for b, d in dgm]
    return {
        'count': len(pers),
        'total': round(sum(pers), 6),
        'mean': round(float(np.mean(pers)), 6),
        'max': round(float(np.max(pers)), 6),
        'median': round(float(np.median(pers)), 6),
    }

# 5. Create PH features summary for regression
ph_features = {
    'total_persistence_H0': round(total_pers_h0, 6),
    'total_persistence_H1': round(total_pers_h1, 6),
    'betti_0_integral': round(betti_0_integral, 6),
    'betti_1_integral': round(betti_1_integral, 6),
    'entropy_H0': round(entropy_h0, 6),
    'entropy_H1': round(entropy_h1, 6),
    'max_persistence_H0': pers_stats(dgms[0])['max'],
    'max_persistence_H1': pers_stats(dgms[1])['max'],
    'mean_persistence_H0': pers_stats(dgms[0])['mean'],
    'mean_persistence_H1': pers_stats(dgms[1])['mean'],
    'num_features_H0': len(dgms[0]),
    'num_features_H1': len(dgms[1]),
}

pers_json = {
    'method': 'GUDHI cubical complexes (superlevel set filtration)',
    'grid_shape': [ny, nx],
    'diagrams': {
        'H0': [[round(b, 6), round(d, 6)] for b, d in dgms[0][:500]],
        'H1': [[round(b, 6), round(d, 6)] for b, d in dgms[1][:500]],
    },
    'betti_curves': {
        'thresholds': [round(t, 6) for t in filt_thresholds],
        'beta_0': betti_0,
        'beta_1': betti_1,
    },
    'stats': {
        'H0': pers_stats(dgms[0]),
        'H1': pers_stats(dgms[1]),
        'total_persistence_H0': round(total_pers_h0, 6),
        'total_persistence_H1': round(total_pers_h1, 6),
    },
    'h1_cycles': h1_representative_coords,
    'ph_features': ph_features,
}
with open(os.path.join(OUT, 'ph_persistence.json'), 'w') as f:
    json.dump(pers_json, f)
print("  → ph_persistence.json saved")
print(f"  → {len(h1_representative_coords)} representative H1 cycles extracted")

# ── 5.  Crime spatial join to boundary zones ─────────────────────────────────
print("\n[5/8] Spatial join: crimes → boundary zones …")

# Geographic constants for Vancouver (49°N)
_M_LAT = 111000.0
_M_LON = 111000.0 * math.cos(math.radians(49.2))  # ≈ 72,800 m/°
_LON_SCALE = _M_LON / _M_LAT                       # ≈ 0.6559

# Build block centroid KDTree using geographically-scaled coordinates.
# Scaling longitude by (_M_LON/_M_LAT) makes Euclidean distance in the
# scaled space proportional to true on-ground distance, correcting for
# the fact that at 49°N, 1° longitude ≈ 72,800 m ≠ 1° latitude ≈ 111,000 m.
block_ids_list = list(blocks.keys())
centroids_raw = np.array([[blocks[bid]['cx'], blocks[bid]['cy']] for bid in block_ids_list])
centroids_scaled = centroids_raw.copy()
centroids_scaled[:, 0] *= _LON_SCALE

crime_coords_nn_scaled = crime_coords.copy()
crime_coords_nn_scaled[:, 0] *= _LON_SCALE

ctree = cKDTree(centroids_scaled)

# Each crime assigned to nearest block (geographically-corrected space)
_, nearest_idx = ctree.query(crime_coords_nn_scaled)
crime_block_ids = [block_ids_list[i] for i in nearest_idx]

# Classify crimes as boundary (adjacent to sharp edge) or interior
boundary_crimes_idx = []
interior_crimes_idx = []
for i, bid in enumerate(crime_block_ids):
    if bid in sharp_block_ids:
        boundary_crimes_idx.append(i)
    else:
        interior_crimes_idx.append(i)

bnd_count = len(boundary_crimes_idx)
int_count = len(interior_crimes_idx)
total = bnd_count + int_count
print(f"  Geographic correction applied: lon scaled by {_LON_SCALE:.4f} (49°N correction)")
print(f"  Boundary-zone crimes: {bnd_count} ({100*bnd_count/total:.1f}%)")
print(f"  Interior-zone crimes: {int_count} ({100*int_count/total:.1f}%)")

# ── 6.  Buffer-based boundary-near crime counts ─────────────────────────────
print("\n[6/8] Computing boundary-near crime counts (50m buffer) …")

# FIXED: Proper distance calculation for Vancouver latitude (~49°N)
LAT_CENTER = 49.2  # degrees N for Metro Vancouver
METERS_PER_DEG_LAT = 111000  # constant
METERS_PER_DEG_LON = 111000 * math.cos(math.radians(LAT_CENTER))  # ≈ 72,800m at 49°N

# Convert 50m buffer to degrees (different for lat vs lon)
BUFFER_RADIUS_M = 50
BUFFER_RADIUS_DEG_LAT = BUFFER_RADIUS_M / METERS_PER_DEG_LAT
BUFFER_RADIUS_DEG_LON = BUFFER_RADIUS_M / METERS_PER_DEG_LON

print(f"  Distance conversion at {LAT_CENTER}°N:")
print(f"    1° latitude ≈ {METERS_PER_DEG_LAT:,.0f} m")
print(f"    1° longitude ≈ {METERS_PER_DEG_LON:,.0f} m")
print(f"    Buffer: {BUFFER_RADIUS_M}m = {BUFFER_RADIUS_DEG_LAT:.6f}° lat × {BUFFER_RADIUS_DEG_LON:.6f}° lon")

# Build a tree of crime points for fast radius search
# FIXED: Use elliptical distance metric for proper geographic distances
from scipy.spatial import cKDTree

class EllipticalDistance:
    """Elliptical distance metric for geographic coordinates at Vancouver latitude"""
    def __init__(self, lat_center=49.2):
        self.m_per_deg_lat = 111000
        self.m_per_deg_lon = 111000 * math.cos(math.radians(lat_center))
    
    def to_meters(self, dlat, dlon):
        """Convert degree differences to meters"""
        return math.sqrt((dlat * self.m_per_deg_lat)**2 + (dlon * self.m_per_deg_lon)**2)

dist_conv = EllipticalDistance(LAT_CENTER)

# For cKDTree, we need to scale coordinates so Euclidean distance approximates meters
# Scale longitude to match latitude scale
crime_coords_scaled = crime_coords.copy()
crime_coords_scaled[:, 0] *= (dist_conv.m_per_deg_lon / dist_conv.m_per_deg_lat)

crime_tree = cKDTree(crime_coords_scaled)

edge_crime_counts = []
for e in sharp_edges:
    # Mid-point of the edge
    mx = (e['ax'] + e['bx']) / 2
    my = (e['ay'] + e['by']) / 2
    
    # Scale the query point to match tree coordinates
    mx_scaled = mx * (dist_conv.m_per_deg_lon / dist_conv.m_per_deg_lat)
    my_scaled = my  # latitude unchanged
    
    # Query crimes within buffer (radius in "scaled degrees" that correspond to meters)
    # At latitude 49°N, 1° lon ≈ 0.655° lat in meters
    buffer_radius_scaled = BUFFER_RADIUS_M / dist_conv.m_per_deg_lat
    
    idx = crime_tree.query_ball_point([mx_scaled, my], buffer_radius_scaled)
    edge_crime_counts.append({
        'a': e['a'], 'b': e['b'],
        'w': e['w'],
        'crime_count': len(idx),
        'mid_lon': round(mx, 6),
        'mid_lat': round(my, 6),
    })

# Crime counts by type near sharp boundaries
boundary_crime_types = defaultdict(int)
for i in boundary_crimes_idx:
    boundary_crime_types[crime_types[i]] += 1
interior_crime_types = defaultdict(int)
for i in interior_crimes_idx:
    interior_crime_types[crime_types[i]] += 1

# ── 7.  Statistical summaries ────────────────────────────────────────────────
print("\n[7/8] Computing statistical summaries …")

# Correlation: edge sharpness vs nearby crime count
sharp_w = np.array([e['w'] for e in edge_crime_counts])
sharp_c = np.array([e['crime_count'] for e in edge_crime_counts])
if len(sharp_w) > 2 and np.std(sharp_w) > 0 and np.std(sharp_c) > 0:
    corr = float(np.corrcoef(sharp_w, sharp_c)[0, 1])
else:
    corr = 0.0
print(f"  Sharpness–crime correlation: {corr:.4f}")

# Compute block-level statistics for boundary vs interior
boundary_block_crimes = []
interior_block_crimes = []
for bid, info in blocks.items():
    if bid in sharp_block_ids:
        boundary_block_crimes.append(info['crime_count'])
    else:
        interior_block_crimes.append(info['crime_count'])

bnd_mean = float(np.mean(boundary_block_crimes)) if boundary_block_crimes else 0
int_mean = float(np.mean(interior_block_crimes)) if interior_block_crimes else 0

# FIXED: Permutation test with proper power (10000 iterations) and confidence intervals
print("  Running permutation test (10000 iterations) …")
all_block_crimes = boundary_block_crimes + interior_block_crimes
n_bnd = len(boundary_block_crimes)
observed_diff = bnd_mean - int_mean
perm_diffs = []
rng = np.random.default_rng(42)
N_PERM = 10000

for i in range(N_PERM):
    if (i + 1) % 1000 == 0:
        print(f"    {i + 1}/{N_PERM} permutations completed")
    perm = rng.permutation(all_block_crimes)
    perm_bnd = float(np.mean(perm[:n_bnd]))
    perm_int = float(np.mean(perm[n_bnd:]))
    perm_diffs.append(perm_bnd - perm_int)

perm_diffs = np.array(perm_diffs)
p_value = float(np.mean(perm_diffs >= observed_diff))

# Compute 95% confidence interval for p-value using normal approximation
# Var(p_hat) = p(1-p)/N, so CI = p ± 1.96 * sqrt(p(1-p)/N)
p_var = p_value * (1 - p_value) / N_PERM
p_se = math.sqrt(p_var)
p_ci_lower = max(0, p_value - 1.96 * p_se)
p_ci_upper = min(1, p_value + 1.96 * p_se)

print(f"  Observed mean diff (boundary - interior): {observed_diff:.4f}")
print(f"  Permutation p-value: {p_value:.4f} (95% CI: {p_ci_lower:.4f} - {p_ci_upper:.4f})")
print(f"    Monte Carlo SE: ±{p_se:.4f}")

# ── 8.  Export boundary-crimes JSON ──────────────────────────────────────────
print("\n[8/8] Exporting JSON …")

boundary_crimes_json = {
    'summary': {
        'total_crimes': total,
        'boundary_crimes': bnd_count,
        'interior_crimes': int_count,
        'boundary_pct': round(100 * bnd_count / total, 1),
        'interior_pct': round(100 * int_count / total, 1),
        'boundary_mean_crimes_per_block': round(bnd_mean, 4),
        'interior_mean_crimes_per_block': round(int_mean, 4),
        'mean_diff': round(observed_diff, 4),
        'permutation_p_value': round(p_value, 4),
        'permutation_p_value_ci_95': [round(p_ci_lower, 4), round(p_ci_upper, 4)],  # NEW
        'permutation_iterations': N_PERM,  # NEW
        'permutation_se': round(p_se, 4),  # NEW
        'sharpness_crime_correlation': round(corr, 4),
        'sharp_edge_count': len(sharp_edges),
        'sharp_block_count': len(sharp_block_ids),
        'total_blocks': len(blocks),
        'buffer_radius_m': 50,
        'lat_center': LAT_CENTER,  # NEW
        'meters_per_deg_lat': METERS_PER_DEG_LAT,  # NEW
        'meters_per_deg_lon': round(METERS_PER_DEG_LON, 1),  # NEW
    },
    'boundary_crime_types': dict(boundary_crime_types),
    'interior_crime_types': dict(interior_crime_types),
    'edge_crime_counts': edge_crime_counts[:500],  # cap for JSON size
    'sharp_block_ids': list(sharp_block_ids),
}

with open(os.path.join(OUT, 'ph_boundary_crimes.json'), 'w') as f:
    json.dump(boundary_crimes_json, f)
print("  → ph_boundary_crimes.json saved")

# Summary
print(f"\n{'=' * 65}")
print("  PIPELINE COMPLETE")
print(f"{'=' * 65}")
print(f"  Output files in: {OUT}")
print(f"    ph_adjacency.json       – {len(edges)} edges")
print(f"    ph_sharpness_grid.json  – {nx}×{ny} raster")
print(f"    ph_persistence.json     – H0:{len(dgms[0])}, H1:{len(dgms[1])} features")
print(f"    ph_boundary_crimes.json – {bnd_count} boundary / {int_count} interior crimes")
print(f"{'=' * 65}")
