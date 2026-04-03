# Technical Analysis Report: Persistent Homology Crime Dashboard

## Executive Summary

This report provides an in-depth analysis of the persistent homology and machine learning approaches used in the `ph_dashboard.html` (Persistent Homology Dashboard) for analyzing crime patterns in relation to urban sharp boundaries. The analysis covers the mathematical foundations, library implementations, and identifies potential issues or "hallucinations" in the methodology.

---

## 1. Architecture Overview

The dashboard implements a **hybrid topological data analysis pipeline** with two main analytical tracks:

### Track A: PH on Rasterized Sharpness Field (Primary)
**File**: `src/ph_boundary_sharpness.py` → `ph_dashboard.js`

### Track B: PH on Crime Point Clouds (Secondary)
**File**: `src/persistent_homology_crime_analysis.py`, `src/boundary_crime_analysis.py`

### Track C: TDA on Property Feature Space (Legacy)
**File**: `src/property_crime_tda.py`, `src/analysis_tda.py`

---

## 2. Step-by-Step Analysis Pipeline

### Phase 1: Data Preprocessing

#### 2.1.1 Block-Level Property Aggregation
**Location**: `ph_boundary_sharpness.py` (lines 62-91)

```python
# Per-block property stats with outlier filtering
def filtered_mean(vals, sd_thresh=1.3):
    """Compute mean after removing outliers beyond sd_thresh SDs."""
    if len(vals) < 2:
        return np.mean(vals) if vals else 0.0
    m, s = np.mean(vals), np.std(vals)
    filt = [v for v in vals if abs(v - m) <= sd_thresh * s] if s > 0 else vals
    return float(np.mean(filt)) if filt else float(m)
```

**Libraries Used**:
- `numpy` - Statistical calculations (mean, std)
- `collections.defaultdict` - Grouping properties by block

**What it does**:
1. Groups property values and building ages by block ID
2. Applies 1.3-SD outlier filtering to each block's properties
3. Computes filtered means for property value and building age per block

**Critique**: 
- ✅ The 1.3-SD threshold is empirically reasonable for removing extreme outliers
- ⚠️ Using block-level aggregates loses intra-block heterogeneity information

---

#### 2.1.2 Normalization of Value/Age Contrasts
**Location**: `ph_boundary_sharpness.py` (lines 107-113)

```python
# Normalise value and age across all blocks for comparable weighting
all_vals = np.array([b['filt_value'] for b in blocks.values() if b['filt_value'] is not None], dtype=float)
all_ages = np.array([b['filt_age'] for b in blocks.values() if b['filt_age'] is not None], dtype=float)

val_std = float(np.std(all_vals[all_vals > 0])) if np.any(all_vals > 0) else 1.0
age_std = float(np.std(all_ages[all_ages > 0])) if np.any(all_ages > 0) else 1.0
```

**What it does**:
1. Computes global standard deviations for property values and building ages
2. These are used to standardize contrasts between adjacent blocks

**Formula**: For edge between blocks A and B:
```
dv = (value_A - value_B) / val_std  # Standardized value difference
da = (age_A - age_B) / age_std      # Standardized age difference
w = sqrt(dv² + da²)                  # Euclidean sharpness weight
```

---

### Phase 2: Adjacency Graph Construction

#### 2.2.1 Edge Weight Computation
**Location**: `ph_boundary_sharpness.py` (lines 115-151)

```python
for bid, info in blocks.items():
    for nb in info['neighbors']:
        # ... edge uniqueness check ...
        
        # Standardised attribute contrast
        v1 = blocks[bid]['filt_value'] or 0
        v2 = blocks[nb]['filt_value'] or 0
        a1 = blocks[bid]['filt_age'] or 0
        a2 = blocks[nb]['filt_age'] or 0
        dv = (v1 - v2) / val_std
        da = (a1 - a2) / age_std
        w = math.sqrt(dv ** 2 + da ** 2)
        
        # Shared boundary length via Shapely intersection
        try:
            shared = blocks[bid]['geom'].intersection(blocks[nb]['geom'])
            shared_len = shared.length if not shared.is_empty else 0.0
        except Exception:
            shared_len = 0.0
```

**Libraries Used**:
- `shapely.geometry` - Polygon operations, intersection for shared boundary length
- `math` - Euclidean norm calculation

**What it does**:
1. Iterates through all block neighbor relationships
2. Computes standardized multivariate contrast (L2-norm of z-scored differences)
3. Calculates physical shared boundary length using Shapely intersection
4. Stores edge with: block IDs, sharpness weight, value delta, age delta, shared length, centroid coordinates

**Critique**:
- ✅ Multivariate approach captures both value and age boundaries
- ✅ Standardization ensures equal weighting across different scales
- ⚠️ Shared boundary length is computed but NOT used in the sharpness weight
- ⚠️ L2-norm assumes independence between value and age changes

---

### Phase 3: Rasterization for Cubical Persistent Homology

#### 2.3.1 Grid Setup
**Location**: `ph_boundary_sharpness.py` (lines 181-195)

```python
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
```

**What it does**:
- Creates a 2D grid covering the study area with ~100m resolution
- Grid dimensions typically result in 50-150 pixels per dimension

---

#### 2.3.2 Bresenham-style Edge Rasterization
**Location**: `ph_boundary_sharpness.py` (lines 197-214)

```python
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
```

**What it does**:
1. For each adjacency edge, samples points along the line between block centroids
2. Maps each sample point to grid coordinates
3. Stores the **maximum** sharpness weight at each grid cell (important: uses max, not sum)

**Libraries Used**:
- `numpy` - Grid array manipulation
- `scipy.ndimage.gaussian_filter` - Post-processing smoothing

---

#### 2.3.3 Gaussian Smoothing
**Location**: `ph_boundary_sharpness.py` (line 214)

```python
# Light Gaussian smooth for numerical stability (σ = 1 pixel)
grid_smooth = gaussian_filter(grid, sigma=1.0)
```

**What it does**:
- Applies σ=1 Gaussian blur to the sharpness field
- This ensures numerical stability for the cubical complex computation
- Creates a continuous field from discrete edge samples

**Critique**:
- ✅ Reasonable for connecting adjacent edges
- ⚠️ Slight blurring may shift boundary locations by ~1 pixel (~100m)

---

### Phase 4: Cubical Persistent Homology Computation

#### 2.4.1 GUDHI Cubical Complex Setup
**Location**: `ph_boundary_sharpness.py` (lines 228-241)

```python
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
```

**Libraries Used**:
- `gudhi.CubicalComplex` - Computes persistent homology on regular grids

**Mathematical Foundation**:
- **Cubical Complex**: A cell complex where cells are axis-aligned cubes (pixels in 2D)
- **Filtration**: The sharpness values define a filtration where pixels with value ≥ α are included at threshold α
- **Superlevel Set**: By negating the grid, we compute superlevel set persistence (high values appear first)

**Key Concept**:
```
Birth at threshold α: A topological feature appears when all pixels in its support have value ≥ α
Death at threshold β: The feature is destroyed/merged when the threshold drops below β
Persistence = death - birth (how long the feature persists across scales)
```

---

#### 2.4.2 Persistence Diagram Extraction
**Location**: `ph_boundary_sharpness.py` (lines 243-252)

```python
# Extract persistence diagrams
dgms = {0: [], 1: []}
for (dim, (birth, death)) in all_intervals:
    if dim in dgms and np.isfinite(death):
        dgms[dim].append([float(birth), float(death)])

# Convert back to superlevel (negate birth/death)
for dim in dgms:
    dgms[dim] = [[-d, -b] for b, d in dgms[dim] if b != d]
    dgms[dim].sort(key=lambda x: -(x[1] - x[0]))  # sort by persistence desc
```

**What it does**:
1. Extracts H0 (connected components) and H1 (loops/1-cycles) features
2. Filters out infinite deaths (the global feature that persists to end)
3. Converts back from negated space to original sharpness values
4. Sorts by persistence (most persistent features first)

**Interpretation**:
- **H0 Features**: Connected components of high-sharpness regions → represent distinct boundary clusters
- **H1 Features**: Loops/rings in the sharpness field → represent enclosed regions surrounded by sharp boundaries

---

#### 2.4.3 Betti Curve Computation
**Location**: `ph_boundary_sharpness.py` (lines 258-267)

```python
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
```

**What it does**:
- Computes Betti numbers β₀(α) and β₁(α) as functions of filtration threshold α
- β₀(α) = number of connected components at threshold α
- β₁(α) = number of loops at threshold α

---

#### 2.4.4 H1 Cycle Extraction for Visualization
**Location**: `ph_boundary_sharpness.py` (lines 287-322)

```python
top_h1 = dgms[1][:20]  # top 20 most persistent H1 features
h1_representative_coords = []
for i, (birth, death) in enumerate(top_h1):
    # Find pixels at the birth threshold to approximate the loop location
    threshold = (birth + death) / 2
    mask = grid_smooth >= threshold
    ys, xs = np.where(mask)
    # ... convex hull computation for loop visualization ...
```

**What it does**:
1. Takes top 20 most persistent H1 features
2. For each, finds all pixels above the midpoint persistence threshold
3. Computes convex hull of these pixels to approximate the loop boundary
4. Exports loop coordinates for map visualization

**Libraries Used**:
- `scipy.spatial.ConvexHull` - Computes convex hull of high-sharpness pixels

---

### Phase 5: Crime Spatial Analysis

#### 2.5.1 Nearest Block Assignment
**Location**: `ph_boundary_sharpness.py` (lines 352-368)

```python
# Build block centroid KDTree for fast nearest-block lookup
block_ids_list = list(blocks.keys())
centroids = np.array([[blocks[bid]['cx'], blocks[bid]['cy']] for bid in block_ids_list])
ctree = cKDTree(centroids)

# Assign each crime to nearest block
_, nearest_idx = ctree.query(crime_coords)
crime_block_ids = [block_ids_list[i] for i in nearest_idx]
```

**Libraries Used**:
- `scipy.spatial.cKDTree` - Fast nearest-neighbor queries

**What it does**:
- Assigns each crime incident to its nearest block centroid
- This is used to classify crimes as "boundary" or "interior" zone crimes

---

#### 2.5.2 50m Buffer-Based Crime Counting
**Location**: `ph_boundary_sharpness.py` (lines 376-397)

```python
BUFFER_RADIUS_DEG = 50 / 111000  # ~50 m in degrees

# Build a tree of crime points for fast radius search
crime_tree = cKDTree(crime_coords)

edge_crime_counts = []
for e in sharp_edges:
    # Mid-point of the edge
    mx = (e['ax'] + e['bx']) / 2
    my = (e['ay'] + e['by']) / 2
    # Query crimes within buffer
    idx = crime_tree.query_ball_point([mx, my], BUFFER_RADIUS_DEG)
    edge_crime_counts.append({
        'a': e['a'], 'b': e['b'],
        'w': e['w'],
        'crime_count': len(idx),
        ...
    })
```

**What it does**:
1. For each sharp edge, computes midpoint coordinates
2. Queries crime points within 50m (Euclidean) radius of the midpoint
3. Counts crimes per edge

**Critique**:
- ✅ Computationally efficient with cKDTree
- ⚠️ **Euclidean distance in degrees is APPROXIMATE** (converts 50m → degrees using constant factor)
- ⚠️ **Uses midpoint only** - crimes near the edge but far from midpoint are not counted
- ⚠️ Does not account for street network distance

---

#### 2.5.3 Statistical Testing
**Location**: `ph_boundary_sharpness.py` (lines 410-446)

```python
# Permutation test (quick version, 200 iterations)
all_block_crimes = boundary_block_crimes + interior_block_crimes
n_bnd = len(boundary_block_crimes)
observed_diff = bnd_mean - int_mean
perm_diffs = []
rng = np.random.default_rng(42)
for _ in range(200):
    perm = rng.permutation(all_block_crimes)
    perm_bnd = float(np.mean(perm[:n_bnd]))
    perm_int = float(np.mean(perm[n_bnd:]))
    perm_diffs.append(perm_bnd - perm_int)

p_value = float(np.mean(np.array(perm_diffs) >= observed_diff))
```

**What it does**:
- Tests if mean crime count differs significantly between boundary-adjacent and interior blocks
- Permutation test with 200 iterations
- Null hypothesis: boundary and interior block assignments are random

**Libraries Used**:
- `numpy.random.default_rng` - Random permutation generation

---

## 3. Frontend Analysis (`ph_dashboard.js`)

### 3.1 Crime-to-Edge Spatial Join (Client-Side)
**Location**: `ph_dashboard.js` (lines 164-257)

```javascript
const cellSize = ACTIVE_BOUNDARY_BUFFER_M;
const radiusSq = ACTIVE_BOUNDARY_BUFFER_M ** 2;
const edgeGrid = new Map();

// Spatial indexing: put edges into grid cells
const edgeMeta = edges.map((edge, index) => {
    // ... compute midpoint, project to meters ...
    const key = cellKey(px, py, cellSize);
    if (!edgeGrid.has(key)) edgeGrid.set(key, []);
    edgeGrid.get(key).push(index);
    // ...
});

// For each crime, check nearby grid cells for edge proximity
crimeFeatures.forEach((feature, crimeIndex) => {
    // ... project crime to meters ...
    const baseCellX = Math.floor(px / cellSize);
    const baseCellY = Math.floor(py / cellSize);
    
    // Check 3x3 neighborhood of grid cells
    for (let dx = -1; dx <= 1; dx += 1) {
        for (let dy = -1; dy <= 1; dy += 1) {
            const candidates = edgeGrid.get(`${baseCellX + dx},${baseCellY + dy}`);
            // ... distance check against edge midpoints ...
        }
    }
});
```

**What it does**:
1. Creates a spatial grid index for edge midpoints (50m cells)
2. For each crime, checks grid cells in 3×3 neighborhood
3. Computes Euclidean distance (in projected meters) to edge midpoints
4. Classifies crime as "boundary" if within 50m of any active sharp edge

**Libraries Used**:
- Vanilla JavaScript (no external geometry libraries)
- Custom grid-based spatial index

**Projection**:
```javascript
const METERS_PER_DEG_LAT = 111000;
function projectPoint(lon, lat, metersPerDegLon) {
    return [lon * metersPerDegLon, lat * METERS_PER_DEG_LAT];
}
```

This is a **simple equirectangular projection** that approximates:
- 1° latitude ≈ 111 km everywhere
- 1° longitude ≈ 111 km × cos(latitude)

---

### 3.2 Permutation P-Value Computation (Client-Side)
**Location**: `ph_dashboard.js` (lines 259-290)

```javascript
function computePermutationPValue(boundaryValues, interiorValues, seed) {
    const nBoundary = boundaryValues.length;
    const allValues = boundaryValues.concat(interiorValues);
    const shuffled = allValues.slice();
    const totalSum = allValues.reduce((sum, value) => sum + value, 0);
    const observedDiff = mean(boundaryValues) - mean(interiorValues);
    const rng = mulberry32(seed);
    let extremeCount = 0;

    for (let i = 0; i < PERMUTATION_ITERATIONS; i += 1) {
        // Fisher-Yates shuffle
        for (let j = shuffled.length - 1; j > 0; j -= 1) {
            const k = Math.floor(rng() * (j + 1));
            [shuffled[j], shuffled[k]] = [shuffled[k], shuffled[j]];
        }
        // ... compute permuted difference ...
    }
    return Number((extremeCount / PERMUTATION_ITERATIONS).toFixed(4));
}
```

**Libraries Used**:
- Custom `mulberry32` PRNG (deterministic random for reproducibility)

---

### 3.3 Persistence Diagram Visualization
**Location**: `ph_dashboard.js` (lines 706-798)

```javascript
function drawPersistenceDiagram(ctx, w, h) {
    // ... setup axes ...
    
    // Draw diagonal reference line (birth = death)
    ctx.strokeStyle = '#475569';
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(pad.l, h - pad.b);
    ctx.lineTo(pad.l + plotW, h - pad.b - plotH);
    ctx.stroke();
    
    // Plot H0 points (connected components)
    ctx.fillStyle = 'rgba(167, 139, 250, 0.65)';
    h0Filtered.forEach(([birth, death]) => {
        const x = pad.l + (birth / maxVal) * plotW;
        const y = h - pad.b - (death / maxVal) * plotH;
        ctx.beginPath();
        ctx.arc(x, y, 3, 0, Math.PI * 2);
        ctx.fill();
    });
    
    // Plot H1 points (loops) - larger markers
    ctx.fillStyle = 'rgba(244, 114, 182, 0.75)';
    h1Filtered.forEach(([birth, death]) => {
        const x = pad.l + (birth / maxVal) * plotW;
        const y = h - pad.b - (death / maxVal) * plotH;
        ctx.beginPath();
        ctx.arc(x, y, 4, 0, Math.PI * 2);
        ctx.fill();
    });
}
```

**What it does**:
- Renders persistence diagram using HTML5 Canvas
- H0 (0-dimensional features) = small purple dots
- H1 (1-dimensional features) = larger pink dots
- Dashed diagonal line represents zero persistence (birth = death)
- Points far above the diagonal are highly persistent

---

### 3.4 Betti Curve Visualization
**Location**: `ph_dashboard.js` (lines 800-887)

```javascript
function drawBettiCurves(ctx, w, h) {
    // ... setup ...
    
    const beta0 = thresholds.map(alpha => h0Filtered.filter(([birth, death]) => birth <= alpha < death).length);
    const beta1 = thresholds.map(alpha => h1Filtered.filter(([birth, death]) => birth <= alpha < death).length);
    
    // Draw curves
    ctx.strokeStyle = '#a78bfa';  // H0 - purple
    ctx.beginPath();
    thresholds.forEach((threshold, index) => {
        const x = pad.l + (threshold / maxX) * plotW;
        const y = h - pad.b - (beta0[index] / maxY) * plotH;
        if (index === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    });
    ctx.stroke();
    
    ctx.strokeStyle = '#f472b6';  // H1 - pink
    // ... similar for beta1 ...
}
```

---

## 4. Libraries Summary

| Library | Version (implied) | Purpose |
|---------|-------------------|---------|
| **GUDHI** | Latest | Cubical persistent homology computation |
| **NumPy** | Latest | Array operations, statistics, linear algebra |
| **SciPy** | Latest | `cKDTree` (spatial queries), `ConvexHull`, `gaussian_filter` |
| **Shapely** | Latest | Polygon geometry operations, intersections |
| **Ripser** (Track B) | Latest | Vietoris-Rips persistent homology on point clouds |
| **Persim** (Track B) | Latest | Persistence diagram comparison (Wasserstein distance) |
| **Leaflet** (Frontend) | 1.9.4 | Interactive map visualization |
| **Leaflet.heat** (Frontend) | 0.2.0 | Crime heatmap overlay |

---

## 5. Issues and Hallucinations Identified

### 🔴 Critical Issues

#### Issue 1: Missing Representative Cycles from GUDHI
**Location**: `ph_boundary_sharpness.py` (lines 287-322)

**Problem**: The H1 cycles displayed on the map are **NOT actual representative cycles** from the persistent homology computation. They are approximated using convex hulls of high-sharpness pixels.

```python
# This is NOT a valid representative cycle from PH!
mask = grid_smooth >= threshold
ys, xs = np.where(mask)
# ... convex hull computation ...
```

**Why this is wrong**:
- GUDHI's `CubicalComplex.persistence()` does NOT return representative cycles by default
- To get actual representative cycles, you need: `cc.persistence_intervals_in_dimension(1)` + `cc.cofaces_of_persistence_pairs()`
- The convex hull approach may show completely different geometry from actual PH cycles

**Impact**: The "H1 Cycles" shown on the map are **geometric approximations, not topological features**, potentially misleading users about what persistent homology actually found.

---

#### Issue 2: The "Persistence" vs "Sharpness" Threshold Confusion
**Location**: `ph_dashboard.js` (lines 48-63, UI labels)

**Problem**: The dashboard has TWO independent thresholds:
1. **Sharpness Threshold** (p0-p100): Filters which adjacency edges are "active"
2. **Persistence Threshold** (p0-p100): Filters which PH features are shown in diagrams

**The confusion**: Users might think these are connected, but they operate on completely different data:
- Sharpness threshold → filters `ph_adjacency.json` edges
- Persistence threshold → filters `ph_persistence.json` diagram points

**Impact**: The crime statistics (boundary vs interior) are computed based on sharpness threshold ONLY. The persistence threshold only affects visualizations, not the actual analysis.

---

#### Issue 3: Euclidean Approximation in Degrees
**Location**: `ph_boundary_sharpness.py` (line 379)

```python
BUFFER_RADIUS_DEG = 50 / 111000  # ~50 m in degrees
```

**Problem**: This assumes 1° = 111,000m everywhere, which is only true for latitude. At Vancouver's latitude (~49°N):
- 1° latitude ≈ 111,000 m
- 1° longitude ≈ 111,000 × cos(49°) ≈ 72,800 m

**Impact**: The 50m buffer is **elliptical**, not circular. Longitudinal distances are underestimated by ~34%.

---

### 🟡 Moderate Issues

#### Issue 4: No Uncertainty Quantification in Persistence Diagrams
**Location**: `ph_dashboard.js` (lines 706-798)

**Problem**: The persistence diagram shows points without any confidence intervals or stability information. Persistence diagrams can be unstable under small perturbations.

**Suggested improvement**: Add stability diagrams or confidence bands using bootstrap sampling.

---

#### Issue 5: Inconsistent Permutation Test Iterations
**Location**: 
- `ph_boundary_sharpness.py` (line 432): 200 iterations
- `boundary_crime_analysis.py` (line 205): 200 iterations (subsampled to N=500)

**Problem**: 200 iterations is low for reliable p-value estimation. Standard practice is 1,000-10,000 iterations.

**Impact**: P-values may have high variance (Monte Carlo error ~ 1/√200 ≈ 7%).

---

#### Issue 6: Hardcoded Thresholds Without Cross-Validation
**Location**: `ph_boundary_sharpness.py` (lines 154-155)

```python
w_p75 = float(np.percentile(w_vals, 75))
w_p90 = float(np.percentile(w_vals, 90))
```

**Problem**: The 75th percentile threshold for "sharp" edges is arbitrary and not validated against actual crime patterns.

---

### 🟢 Minor Issues

#### Issue 7: Tooltip Misrepresents H1 Cycles
**Location**: `ph_dashboard.js` (line 496-503)

```javascript
polygon.bindTooltip(
    `<div style="font-family:Outfit; text-align:center;">
        <b style="color:${color};">H1 Cycle #${cycle.rank}</b><br>
        Birth: ${cycle.birth.toFixed(3)} | Death: ${cycle.death.toFixed(3)}<br>
        <span style="font-size:0.85rem;">Persistence: <b>${cycle.persistence.toFixed(3)}</b></span>
    </div>`,
    { sticky: true }
);
```

**Problem**: The tooltip presents the convex hull approximation as if it were the actual H1 representative cycle, which is misleading.

---

#### Issue 8: Color Scale for Sharpness is Arbitrary
**Location**: `ph_dashboard.js` (lines 66-78)

```javascript
function sharpnessColor(weight, maxWeight) {
    const safeMax = maxWeight || 1;
    const t = Math.min(1, weight / safeMax);
    const r = Math.round(30 + t * 209);
    const g = Math.round(41 + t * 30);
    const b = Math.round(90 + (1 - t) * 72);
    return `rgb(${r},${g},${b})`;
}
```

**Problem**: The color interpolation is not perceptually uniform and lacks a legend with quantiles.

---

## 6. Recommended Improvements

### High Priority

1. **Implement True Representative Cycle Extraction**
   ```python
   # Add to ph_boundary_sharpness.py after computing persistence
   persistence_pairs = cc.persistence_intervals_in_dimension(1)
   cofaces = cc.cofaces_of_persistence_pairs()
   # Extract actual boundary cycles from cofaces
   ```

2. **Fix Distance Calculation**
   ```python
   # Use proper haversine distance or project to UTM
   from sklearn.metrics.pairwise import haversine_distances
   # Or use pyproj for accurate distance calculations
   ```

3. **Increase Permutation Test Power**
   ```python
   N_PERM = 10000  # Instead of 200
   ```

### Medium Priority

4. **Add Stability Analysis**
   - Implement bottleneck distance confidence intervals
   - Add bootstrap resampling for persistence diagram variance

5. **Cross-Validate Sharpness Threshold**
   - Use grid search to find optimal threshold that maximizes crime prediction
   - Implement train/test split validation

6. **Network-Aware Crime Counting**
   - Replace Euclidean buffer with street network distance
   - Use OSMnx or similar for network analysis

### Low Priority

7. **Improve Visualizations**
   - Add proper colorbar legends
   - Implement interactive persistence diagram (hover for feature details)
   - Add time-filtering for temporal analysis

8. **Documentation**
   - Add mathematical notation to UI tooltips
   - Include interpretation guide for PH concepts

---

## 7. Correctness Assessment for Crime-Boundary Relation Analysis

### Is the Analysis Correct?

**The pipeline correctly implements:**
1. ✅ Block-level property aggregation with outlier filtering
2. ✅ Standardized multivariate contrast for boundary sharpness
3. ✅ Cubical persistent homology on rasterized sharpness field
4. ✅ Spatial join of crimes to nearest blocks
5. ✅ Basic statistical testing (permutation test)

**The pipeline has limitations:**
1. ⚠️ Representative cycles are approximations, not actual PH features
2. ⚠️ Distance calculations use approximate Euclidean projection
3. ⚠️ Crime counting uses midpoint-only approach (may miss crimes near edge but far from midpoint)
4. ⚠️ No network-constrained spatial analysis

### Does Persistent Homology Help Identify Crime-Sharp Boundary Relations?

**Direct relation**: The current implementation uses PH primarily for **visualization and exploration**, not for **statistical inference** about the crime-boundary relationship.

**What PH actually contributes**:
- Identifies clusters of sharp boundaries (H0 features)
- Finds enclosed regions surrounded by sharp boundaries (H1 features)
- Provides multi-scale analysis via filtration

**What PH does NOT do (currently)**:
- Statistical testing of whether crimes are attracted to boundaries
- Causal inference about boundary effects
- Predictive modeling

**Recommendation**: The dashboard should clarify that PH is used for **boundary characterization**, while the crime-boundary relation is analyzed via **spatial statistics** (buffer analysis, permutation tests), not PH itself.

---

## 8. Summary Table

| Component | Implementation | Correct? | Issues |
|-----------|----------------|----------|--------|
| Block aggregation | Mean with 1.3-SD filter | ✅ Yes | Minor: loses intra-block variance |
| Edge weight | L2-norm of z-scores | ✅ Yes | Shared length not used in weight |
| Rasterization | Max-value Bresenham | ✅ Yes | Gaussian blur shifts boundaries |
| PH computation | GUDHI CubicalComplex | ✅ Yes | Representative cycles not extracted correctly |
| Crime counting | 50m Euclidean buffer | ⚠️ Approximate | Elliptical distortion, midpoint-only |
| Statistical test | Permutation (200 iter) | ✅ Yes | Low power, high variance |
| Visualization | Canvas rendering | ✅ Yes | H1 cycles are convex hull approximations |

---

## 9. Conclusion

The `ph_dashboard.html` implements a **sound but imperfect** persistent homology pipeline for analyzing sharp urban boundaries and their relation to crime. The core mathematical approach (cubical PH on rasterized sharpness field) is correct, but several implementation details could be improved:

1. **Critical**: Fix representative cycle extraction or remove the misleading H1 cycle visualization
2. **High**: Improve distance calculations and crime-to-boundary spatial join
3. **Medium**: Increase statistical power and add uncertainty quantification
4. **Low**: Enhance visualizations and user documentation

The dashboard successfully demonstrates the application of topological data analysis to urban geography, but users should be aware of the approximations and limitations described in this report.

---

*Report generated: 2026-03-20*
*Analyzed files: ph_boundary_sharpness.py, ph_dashboard.js, ph_dashboard.html, boundary_crime_analysis.py, persistent_homology_crime_analysis.py*
