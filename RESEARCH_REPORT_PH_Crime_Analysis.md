# Detecting Socioeconomic Boundary Effects on Crime Incidence Using Persistent Homology: A Bifiltration Approach Applied to Vancouver, Canada

**Complete Technical Report — Code-Verified Implementation Details**

---

## 1. Research Objective

This research tests the Brantingham & Brantingham (1978) hypothesis that crime concentrates at sharp socioeconomic boundaries — geographic interfaces where contrasting urban environments meet. We deploy **Persistent Homology (PH)**, a tool from Topological Data Analysis (TDA), to rigorously identify and quantify these boundary structures in Vancouver, Canada, and correlate them with historical crime incident data (2020).

The key innovation is a **two-parameter (bifiltration) approach**:
- **ε₁ (spatial):** controls which city blocks can form edges based on physical proximity (meters).
- **ε₂ (attribute):** separates "sharp" (boundary) from "interior" edges based on socioeconomic contrast, derived automatically from topological persistence gaps.

---

## 2. Data Sources & Pre-Processing

### 2.1 Raw Data

| Dataset | Description | Key Fields |
|---------|-------------|------------|
| `crimes.json` | Crime incidents (2020) | Coordinates, `TYPE`, `HUNDRED_BLOCK`, `YEAR` |
| `properties.json` | Property tax assessment records | `property_value`, `building_age`, `ZONING_DISTRICT`, `STREET_NAME`, `block_id` |
| `blocks.json` | City block polygons (GeoJSON) | `block_id`, `neighbors`, `avg_value`, `avg_age`, `zoning_percentages`, `crime_count` |
| `sharp_street_segments.json` | Physical street network segments | `hblock`, `street_type`, `sharpness`, `crime_count`, `crime_types`, `block_a`, `block_b` |

### 2.2 Pre-Processing Pipeline

**a) Property Aggregation to Blocks:**
Individual properties are spatially joined to their enclosing block polygon. Per-block statistics (mean value, mean age) are computed.

**b) Outlier Filtering (SD-based):**
Within each block, property values and building ages beyond **1.3 standard deviations** from the block mean are removed before computing the block-level mean. This prevents a single outlier property from distorting block-level statistics.

```
filtered_mean(vals, sd_thresh=1.3):
    m = mean(vals)
    s = std(vals)
    filtered = [v for v in vals if |v - m| <= 1.3 * s]
    return mean(filtered)
```

*Justification:* 1.3 SD retains ~81% of a normal distribution, removing extreme outliers while preserving the bulk of the distribution. This is more conservative than the typical 2 SD threshold because urban property data is heavily right-skewed.

**c) Min-Max Normalization:**
All block-level values and ages are scaled to [0, 1]:

$$v_{\text{norm}} = \frac{v - v_{\min}}{v_{\max} - v_{\min}}, \quad a_{\text{norm}} = \frac{a - a_{\min}}{a_{\max} - a_{\min}}$$

where $v_{\min}, v_{\max}$ are the global extremes across all blocks (excluding zero-value blocks).

**d) Zoning Percentages:**
Each block carries a dictionary of zoning category percentages (e.g., `{"RS": 45, "RM": 30, "CD": 25}`). These are converted from [0, 100] to [0, 1] for distance computation.

**e) Crime-to-Edge Mapping (HUNDRED_BLOCK Join):**
Crimes are mapped to specific adjacency edges using the `HUNDRED_BLOCK` field (e.g., "32XX MAIN ST"). Street names are standardized via regex replacements (e.g., "STREET" → "ST", "AVENUE" → "AVE"). When multiple edges match a crime's hundred-block, the nearest edge (by Euclidean distance to edge midpoint) is selected.

---

## 3. Complete Algorithm Pipeline

### Stage 1: Spatial Graph Construction (ε₁ filtration)

Block centroids are computed as the geometric centroid (center of mass) of each polygon using Shapely. Coordinates are projected to an isotropic space for distance computation:

$$x_{\text{scaled}} = \text{lon} \times \frac{M_{\text{lon}}}{M_{\text{lat}}}, \quad y_{\text{scaled}} = \text{lat}$$

**Geographic constants (at 49°N Vancouver):**

| Constant | Value | Derivation |
|----------|-------|------------|
| `METERS_PER_DEG_LAT` | 111,000 m | Standard geographic constant |
| `METERS_PER_DEG_LON` | 111,000 × cos(49.2°) ≈ 72,800 m | Latitude-dependent correction |
| `LAT_CENTER` | 49.2° | Approximate center of Vancouver |

A **KD-Tree** (`scipy.spatial.cKDTree`) indexes all scaled centroids. Only block pairs within ε₁ meters are connected:

```python
tree = cKDTree(scaled_centroids)
radius_scaled = epsilon1_m / METERS_PER_DEG_LAT
pairs = tree.query_pairs(r=radius_scaled)
```

**At ε₁ = 0:** No edges (empty graph — only polygon-adjacent blocks would connect in the original static script).
**At ε₁ = 200m (default):** Blocks within ~200m can form edges, creating a denser graph than pure polygon adjacency.

### Stage 2: Attribute Distance Computation (Weighted Euclidean)

For each spatial edge (A, B), the **boundary sharpness weight** is computed as:

$$w(A, B) = \sqrt{\alpha \cdot \Delta v^2 + \beta \cdot \Delta a^2 + \gamma \cdot \|\Delta \mathbf{z}\|_2^2}$$

where:
- $\Delta v = |v_A^{\text{norm}} - v_B^{\text{norm}}|$ — normalized property value contrast
- $\Delta a = |a_A^{\text{norm}} - a_B^{\text{norm}}|$ — normalized building age contrast
- $\|\Delta \mathbf{z}\|_2 = \sqrt{\sum_{k} (z_{A,k} - z_{B,k})^2}$ — L2 norm of zoning fraction differences
- $\alpha, \beta, \gamma$ — user-specified weights constrained to $\alpha + \beta + \gamma = 1$

**Default weights:** $\alpha = \beta = \gamma = 1/3$ (equal weighting).

**Weight presets tested:**
| Configuration | α | β | γ | Rationale |
|---------------|---|---|---|-----------|
| Equal | 0.333 | 0.333 | 0.334 | Baseline: no prior on which attribute matters |
| Value Only | 1.0 | 0.0 | 0.0 | Tests pure property-value gradient |
| Age Only | 0.0 | 1.0 | 0.0 | Tests pure building-age gradient |
| Zone Only | 0.0 | 0.0 | 1.0 | Tests pure land-use transition |

### Stage 3: Single-Linkage Clustering via Union-Find (H₀ Persistence)

Edges are sorted by ascending attribute distance $w$. A **Union-Find** data structure tracks connected components:

```
Initialize: each block is its own component (n components)
For each edge (A, B) in order of increasing w:
    if find(A) ≠ find(B):
        Record persistence pair: (birth=0, death=w)
        union(A, B)
```

**Key property:** In single-linkage clustering, all components are born at filtration value 0. Therefore, **persistence = death value** for every H₀ feature.

Each persistence pair represents a merge event: two clusters of blocks that were separated by all edges with weight < death, but connected at weight = death. **High-persistence features** correspond to robust socioeconomic boundaries that require large attribute contrast to breach.

### Stage 4: Auto-Epsilon₂ Derivation (Topological Gap Threshold)

The ε₂ threshold that separates "boundary" from "interior" edges is derived automatically from the H₀ persistence distribution:

```
1. Collect all death values (finite merges only)
2. Sort descending
3. Trim top 2% as outliers (trim_count = max(1, ⌊0.02 × n⌋))
4. Define noise floor = 10th percentile of death values
5. Compute gaps: gap[i] = sorted[i] - sorted[i+1]
6. Find max gap
7. If max_gap ≥ 0.05 × (max_dist - noise_floor):
       ε₂ = sorted[gap_index]   (the value just before the largest gap)
   Else:
       ε₂ = 75th percentile of all death values (fallback)
```

**Constants used:**

| Constant | Value | Justification |
|----------|-------|---------------|
| Outlier trim | Top 2% | Removes extreme outlier merges that would distort gap detection |
| Noise floor | 10th percentile | Defines the baseline below which persistence is noise |
| Min gap threshold | 5% of (max - noise floor) | Prevents spurious small gaps from being treated as significant |
| Fallback percentile | 75th | Conservative default when no clear topological gap exists |

**Interpretation:** The largest gap in the sorted persistence distribution represents a natural break between "noise" (low-contrast, interior edges) and "signal" (high-contrast, boundary edges). This is the standard approach in persistent homology for identifying significant features.

### Stage 5: Edge Classification & Crime Assignment

- **Boundary edges:** $w \geq \varepsilon_2$ (sharp socioeconomic boundaries)
- **Interior edges:** $w < \varepsilon_2$ (gradual transitions)

Crimes are assigned to edges via the HUNDRED_BLOCK join (see Section 2.2e). Each edge accumulates a crime count filtered by the selected crime type(s).

### Stage 6: Cubical Complex PH (Static Script — `ph_boundary_sharpness.py`)

The static analysis script additionally constructs a 2D scalar sharpness field and runs cubical PH:

**a) Rasterization:**
- Grid resolution: `res_lat = 0.0009°` (~100m), `res_lon = 0.0013°` (~100m)
- For each edge, paint the sharpness weight along a Bresenham-style line between centroids
- Each pixel takes the maximum weight of all edges passing through it

**b) Gaussian Smoothing:**
$$f_{\text{smooth}} = f * G_\sigma, \quad \sigma = 1.0 \text{ pixel}$$

*Justification:* σ = 1 pixel provides numerical stability for the cubical complex without significantly blurring boundary structure.

**c) Superlevel Filtration:**
The GUDHI `CubicalComplex` operates on sublevel filtrations, so the field is negated:

```python
neg_grid = -grid_smooth.copy()
cc = gudhi.CubicalComplex(
    dimensions=[ny, nx],
    top_dimensional_cells=neg_grid.flatten().tolist()
)
all_intervals = cc.persistence()
```

Birth/death values are negated back to recover superlevel semantics.

**d) H₁ Cycle Extraction:**
Top-20 most persistent H₁ features are extracted using midpoint threshold iso-contours:
- For each H₁ pair (birth, death), threshold = (birth + death) / 2
- Binary mask → connected components → largest component → convex hull → coordinate conversion

---

## 4. How Persistent Homology Is Used

### 4.1 What PH Identifies

**H₀ (Connected Components):**
Each H₀ feature represents a cluster of city blocks that share similar socioeconomic profiles. As the filtration parameter α increases, more edges are included, and clusters merge. The death value of each feature is the minimum sharpness weight required to merge that cluster with another — i.e., how much socioeconomic contrast must be traversed to connect them.

**H₁ (Topological Loops):**
H₁ features (from cubical PH) represent closed boundaries that fully encircle an interior zone — "gated" neighborhoods surrounded by sharp socioeconomic transitions on all sides.

### 4.2 Why PH Over Traditional Methods

1. **No arbitrary threshold:** The auto-ε₂ derivation from persistence gaps provides a mathematically principled cutoff, not an arbitrary percentile.
2. **Multi-scale analysis:** The bifiltration (ε₁, ε₂) captures structure at multiple spatial and attribute scales simultaneously.
3. **Stability:** PH is provably stable under small perturbations of the data (Stability Theorem, Cohen-Steiner et al. 2007).
4. **Topological features:** Loops (H₁) and connected components (H₀) capture qualitatively different boundary structures that scalar statistics cannot distinguish.

### 4.3 PH Summary Statistics Computed

| Statistic | Formula | Interpretation |
|-----------|---------|----------------|
| Betti curve β₀(α) | #{(b,d) ∈ Dgm₀ : b ≤ α < d} | Number of distinct clusters at threshold α |
| Persistence entropy H₀ | $-\sum_i \frac{p_i}{L} \ln \frac{p_i}{L}$ where $L = \sum p_i$ | Disorder/complexity of boundary structure |
| Landscape integral | $\int \lambda_1(t) \, dt$ | Total topological complexity |
| Euler characteristic | $\chi(\alpha) = \beta_0(\alpha) - \beta_1(\alpha)$ | Net topological complexity |
| Persistence landscape | $\lambda_k(t) = k\text{-th largest } \min(t-b, d-t)$ | Banach-space embedding of persistence |

---

## 5. Statistical Analysis

### 5.1 Pearson Correlation

$$r = \frac{\sum_i (x_i - \bar{x})(y_i - \bar{y})}{\sqrt{\sum_i (x_i - \bar{x})^2} \sqrt{\sum_i (y_i - \bar{y})^2}}$$

Computed between edge sharpness weights and per-edge crime counts.

### 5.2 Spearman Rank Correlation

Same formula applied to ranks of x and y values, providing a non-parametric measure robust to outliers.

### 5.3 Permutation Test (p-value)

```
observed_diff = mean(boundary_block_crimes) - mean(interior_block_crimes)
For i = 1 to 1000:
    Shuffle all block crime counts
    Split into boundary-sized and interior-sized groups
    If permuted_diff ≥ observed_diff: extreme_count += 1
p-value = extreme_count / 1000
```

**Constants:**
- `PERMUTATION_ITERATIONS = 1000` (yields standard error ≈ 0.016 at p = 0.05)
- `seed = 42 + persistence_percentile` (reproducible via `mulberry32` PRNG)

### 5.4 OLS Linear Regression

Simple ordinary least squares for trendline in scatter plots:
$$\hat{\beta} = \frac{\sum (x_i - \bar{x})(y_i - \bar{y})}{\sum (x_i - \bar{x})^2}, \quad \hat{\alpha} = \bar{y} - \hat{\beta}\bar{x}$$

### 5.5 Quintile Analysis (Brantingham Gradient Test)

All edges sorted by sharpness weight and divided into 5 equal groups (Q1–Q5). Mean crime count per quintile is computed. A monotonic increase from Q1 → Q5 directly supports the boundary-effect hypothesis.

---

## 6. Assumptions & Limitations

1. **Block homogeneity assumption:** Each block is represented by a single mean value/age. Intra-block variation is captured only through the SD filter.
2. **Euclidean attribute distance:** The sharpness weight uses Euclidean distance in feature space, implicitly assuming features are independent and equally scaled (after normalization).
3. **Isotropic geographic distance:** Longitude is scaled by cos(49.2°) to approximate isotropic distance, which is accurate within Vancouver's latitudinal extent.
4. **50m buffer for crime proximity:** `ACTIVE_BOUNDARY_BUFFER_M = 50` meters is used in the dashboard for point-to-edge matching. The server uses HUNDRED_BLOCK join instead. The 50m threshold approximates one city block width.
5. **Single year of data:** Only 2020 crime data is used, which may not capture temporal trends.
6. **Crime type conflation:** Break & Enter (Residential + Commercial) are combined by default. Results may differ for other crime types.
7. **Zoning as proxy:** Zoning percentages proxy land-use mix but do not capture actual commercial activity or foot traffic.
8. **Equal default weights:** The α = β = γ = 1/3 default is a neutral prior; the simplex optimization explores sensitivity to this choice.

---

## 7. Complete Library Inventory

### 7.1 Python (Backend)

| Library | Version Context | Usage |
|---------|----------------|-------|
| `numpy` | Scientific computing | Array operations, percentiles, min-max normalization, linalg.norm |
| `scipy.spatial.cKDTree` | Spatial indexing | KD-Tree for ε₁ proximity queries |
| `scipy.spatial.ConvexHull` | Geometry | H₁ cycle boundary extraction |
| `scipy.ndimage.gaussian_filter` | Image processing | σ=1 smoothing of rasterized grid |
| `scipy.ndimage.label` | Image processing | Connected component labeling for H₁ cycles |
| `gudhi.CubicalComplex` | TDA | Cubical persistent homology computation |
| `shapely.geometry` | Computational geometry | Point, shape(), polygon operations, centroid computation |
| `shapely.ops` | Geometry operations | unary_union (used in block generation) |
| `geopandas` | Spatial data | GeoDataFrame operations (utilities) |
| `pyproj.Transformer` | Coordinate systems | UTM Zone 10N ↔ WGS84 conversion |
| `fastapi` | Web framework | HTTP API server for live recomputation |
| `fastapi.middleware.cors` | CORS | Cross-origin support for dashboard |
| `pydantic.BaseModel` | Validation | Request schema validation |
| `json` | Serialization | GeoJSON parsing/export |
| `re` | Text processing | Street name standardization regex |
| `collections.defaultdict` | Data structures | Edge-crime aggregation |
| `math` | Mathematics | sqrt, cos, radians, hypot |
| `os`, `sys` | System | File paths |

### 7.2 JavaScript (Frontend Dashboard)

| Library | Version | Usage |
|---------|---------|-------|
| Leaflet.js | 1.9.4 | Interactive map rendering |
| Leaflet.heat | 0.2.0 | KDE heatmap overlay |
| Plotly.js | 2.27.0 | Statistical charts (scatter, box, bar, ternary) |
| HTML5 Canvas API | Native | Custom PH visualizations (persistence diagram, Betti curves, barcodes, landscapes, persistence images, Euler curves) |

### 7.3 Tile Providers

| Provider | Usage |
|----------|-------|
| CartoDB Dark | Default dark basemap |
| CartoDB Light | Light mode basemap |
| OpenStreetMap | Standard reference basemap |

---

## 8. Dashboard Visualizations

### 8.1 Map Layers
1. **Boundary Sharpness** — Abstract PH edges connecting block centroids (colored by crime count)
2. **Crime KDE Heatmap** — Kernel density estimate of all crime points
3. **Spatial Blocks** — Block polygon boundaries (red = boundary block, gray = interior)
4. **Block Centroids** — Circle markers at block centers with popup details
5. **Sharp Boundary Streets** — Physical street segments collocated with PH boundaries

### 8.2 Analysis Panels (Right-Side Modals)
1. **PH Diagrams** — H₀ persistence distribution histogram with gap-based and ε₂ threshold lines
2. **Betti Curves** — β₀(α) line chart showing component count vs. filtration parameter
3. **Barcodes** — Horizontal bar chart of H₀ features sorted by persistence
4. **Crime Stats** — Boundary vs. interior crime breakdown with block counts
5. **Crime Correlation** — Three views: scatter (block sharpness vs. crimes), box plot (boundary vs. interior segment crime distributions), quintile bar chart
6. **Edge Crimes** — Per-segment scatter plot with Pearson r, Spearman ρ, and regression line
7. **Simplex Grid** — Ternary plot of weight sensitivity sweep (66 configurations), benchmark table, and boundary vs. interior crime rate comparison

### 8.3 Crime Count Color Scale (Streets & Edges)

| Count | Color | Label |
|-------|-------|-------|
| 0 | #cbd5e1 (slate) | No crimes recorded |
| 1–2 | #4ade80 (green) | Low |
| 3–6 | #facc15 (amber) | Moderate |
| 7–14 | #f97316 (orange) | High |
| 15+ | #ef4444 (red) | Very high |

---

## 9. Key Results

*(From dashboard live computation with default parameters: ε₁ = 200m, α = β = γ = 1/3, Break & Enter crime type)*

### 9.1 Topological Findings
- The H₀ persistence distribution shows a clear gap separating noise (low-contrast merges) from signal (sharp boundary merges)
- Auto-derived ε₂ identifies a meaningful structural threshold
- Betti curve β₀(α) shows a rapid drop at the ε₂ threshold, confirming coherent boundary structure

### 9.2 Crime-Boundary Correlation
- **Boundary blocks** constitute a minority of total blocks but contain a disproportionate share of crimes
- **Permutation test** p-value confirms statistical significance of the boundary-interior crime difference
- **Pearson correlation** between edge sharpness and crime count is positive
- **Quintile analysis** shows monotonically increasing mean crime count from Q1 (lowest sharpness) to Q5 (highest sharpness), directly supporting the Brantingham gradient hypothesis

### 9.3 Weight Sensitivity (Simplex Optimization)
- The boundary effect is **robust across weight configurations**: the boundary/interior crime ratio exceeds 1.0 for most (α, β, γ) combinations
- The robustness region (≥75% of max target ratio) covers a significant portion of the simplex
- This confirms the finding is not an artifact of the specific weight choice

---

## 10. Reproducibility

### Running the Analysis

**Backend server:**
```bash
cd src/
python ph_server.py  # Starts FastAPI on localhost:8001
```

**Dashboard:**
Open `dashboard/web_dashboard/ph_dashboard.html` in a browser with the server running.

**Static analysis (generates JSON files):**
```bash
python src/ph_boundary_sharpness.py
```

### Parameter Space

| Parameter | Range | Default | Effect |
|-----------|-------|---------|--------|
| ε₁ | 0–500m | 200m | Spatial connectivity radius |
| ε₂ | Auto-derived | Gap threshold | Boundary/interior classification |
| α | 0–1 | 0.333 | Property value weight |
| β | 0–1 | 0.333 | Building age weight |
| γ | 0–1 | 0.334 | Zoning weight |
| Crime type | Radio selection | Break & Enter | Crime category filter |

---

## 11. References

- Brantingham, P.L. & Brantingham, P.J. (1978). A theoretical model of crime hot spot generation. *Studies on Crime and Crime Prevention.*
- Cohen-Steiner, D., Edelsbrunner, H., & Harer, J. (2007). Stability of Persistence Diagrams. *Discrete & Computational Geometry.*
- Edelsbrunner, H. & Zomorodian, A. (2002). Computing Persistent Homology. *Discrete & Computational Geometry.*
- Gyulassy, A., et al. (2012). Efficient computation of Morse-Smale complexes for three-dimensional scalar functions. *IEEE TVCG.*
- Robins, V. (2000). Computational Topology at Multiple Resolutions. *PhD Thesis, University of Colorado.*
- GUDHI Library: https://gudhi.inria.fr/
- Zomorodian, A. & Carlsson, G. (2005). Computing Persistent Homology. *Discrete & Computational Geometry.*
