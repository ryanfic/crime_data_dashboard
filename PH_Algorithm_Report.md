# Persistent Homology Analysis of Urban Socioeconomic Boundaries

This report details the exact methodology, algorithm, mathematical formulations, and engineering architecture for the live Persistent Homology (PH) pipeline applied to Vancouver, Canada, based strictly on the current active code implementation.

## 1. Libraries Used

The pipeline is built on a specific suite of Python libraries optimized for spatial mathematics and topological data analysis:

- **Mathematical and Scientific Computing:**
  - `numpy`: Used for high-performance matrix operations, multidimensional array computing, percentile extraction, and weighted Euclidean distance computations across block attribute vectors.
  - `scipy` (`scipy.spatial.cKDTree`): Provides heavily optimized KD-Tree spatial indexing for geographical proximity radius searches, enabling fast construction of the underlying topological network.
  - `math`: Standard statistical functions, trigonometry (for calculating latitude/longitude Earth curvature adjustments).
  - `scipy.ndimage`: Specifically `gaussian_filter`, used for light smoothing (sigma=1.0) of rasterized sharpness fields for numerical stability (in offline scripts).
- **Topological Data Analysis:**
  - `gudhi`: The core library for persistent homology. Used to generate persistence diagrams, Betti curves, handle Union-Find linkages, and compute superlevel-set cubical persistent homology over scalar fields.
- **Server and API Infrastructure:**
  - `fastapi` & `pydantic`: Implements the high-performance live parameter tuning API server, parsing client requests for dynamic $\varepsilon_1$ (spatial) and $\varepsilon_2$ (attribute) thresholds.
- **Data Engineering:**
  - `json`: Standard parsing for GeoJSON inputs and exporting topological adjacency arrays.
  - `re` & `collections.defaultdict`: Regex processing for matching Vancouver Police Department hundred-block string anomalies (e.g., "100XX WEST GEORGIA ST") to physical street segments.

## 2. Algorithm Steps (Current Code Implementation)

The system utilizes a two-stage bifiltration approach to construct a network of urban homogeneity and detect sharp socio-economic boundaries.

### Step 1: Attribute Normalization and Vectorization
For every city block, property values, building ages, and zoning percentages are mapped into a unified scale. 
- The scalar values (Property Value and Age) undergo Min-Max normalization into the range $[0, 1]$. Outliers beyond 1.3 standard deviations are filtered during pure mean baseline computation prior to normalization.
- Zoning categorical data (percentages from 0-100) are also scaled to $[0, 1]$.
- Each block becomes a feature vector in a high-dimensional space: $(norm\_val, norm\_age, norm\_zone_1, \dots, norm\_zone_N)$.

### Step 2: Spatial Filtration ($\varepsilon_1$ Sweep)
A base geometric graph is constructed using a geographic KDTree. Edges are permitted *only* between blocks where the adjusted spatial distance between geographic centroids is less than or equal to the spatial threshold ($\varepsilon_1$ in meters). 

### Step 3: Attribute Filtration ($\varepsilon_2$ Sweep)
For all valid spatial edges, a weighted attribute distance is calculated. It evaluates the disparity between two adjacent blocks across the 3 normalized dimensions (Value, Age, Zoning).

### Step 4: Union-Find Persistence Computation
Zero-dimensional Persistent Homology ($H_0$) is computed using a Union-Find algorithm over the attribute distances.
- Every block begins as its own connected component (birth $= 0$).
- Sweeping through edges in order of *increasing* attribute distance, components are merged.
- When a merge occurs, a component "dies", and the attribute distance of that merge is recorded. Since all births are $0$, the persistence (lifetime) of the feature is exactly equal to its death value.

### Step 5: Topological Gap Thresholding (Auto-$\varepsilon_2$ Derivation)
To mathematically define what constitutes a "sharp" boundary vs. a gentle transition:
1. The finite death/persistence values are sorted.
2. The top 2% of extreme outliers are discarded to avoid spurious artifacts overshadowing neighborhood structures.
3. The lowest 10% of values are designated as a topological "noise floor."
4. The algorithm calculates the differences (gaps) between adjacent sorted persistence values.
5. The maximum gap (if it exceeds a 5% baseline noise sensitivity relative to the range) is selected as the mathematically defensible $\varepsilon_2$ threshold. If the gap is too small, the system defers to a predefined percentile threshold.

### Step 6: Edge Classification and Crime Spatial Join
- **Boundary Classification:** Any spatial edge whose attribute distance meets or exceeds the auto-derived $\varepsilon_2$ threshold is classified as a "Boundary Edge". All others are "Interior Edges".
- **Crime Joining:** Vancouver Police Department data are matched to these boundary and interior street segments using text parsing of the `HUNDRED_BLOCK` address, with a spatial KDTree calculation acting as a coordinate fallback for ambiguous or unmatched locations. 
- **Ratio Calculation:** Crimes on boundary segments are summed, normalized by the count of boundary segments, and compared against interior segments to form the Boundary-to-Interior Crime Ratio, quantifying the socioeconomic boundary effect.

---

## 3. How Persistent Homology Was Used

Persistent Homology (PH) serves as the primary mathematical engine to avoid arbitrary percentile cutoffs when defining where "neighborhoods" end.

Instead of declaring a boundary based on a flat, universal variance threshold, $H_0$ persistence observes how demographic clusters merge as the tolerance for attribute variance (the $\varepsilon_2$ parameter) increases. Each city block starts as an isolated component. As we relax the strictness of similarity (sweeping $\varepsilon_2$ upwards), adjacent blocks merge into larger regional components. 

The distance required to cause two dissimilar regions to merge represents the **death** of a topological feature. A large jump (gap) in these death values corresponds to a systemic discontinuity in the urban fabric—a natural boundary that separates distinctly different socio-economic zones. By deriving the threshold dynamically from the largest gap in the $H_0$ persistence diagram, the algorithm relies on the intrinsic topological shape of the data to identify boundaries, ensuring they are mathematically defensible and sensitive to organic urban transitions rather than imposed linearly.

---

## 4. Mathematical Formulas Used

**1. Isotropic Geographic Scaling at 49.2°N:**
Because a degree of longitude is physically shorter than a degree of latitude in Vancouver, $x$-coordinates must be adjusted relative to $y$-coordinates prior to using the KD-Tree (which assumes an isotropic, Euclidean space).
$$MetersPerDegLat \approx 111,000$$
$$MetersPerDegLon = 111,000 \times \cos(49.2^{\circ})$$
$$Scaled\_Longitude = Longitude \times \left( \frac{MetersPerDegLon}{MetersPerDegLat} \right)$$

This allows Euclidean distance queries to yield an accurate approximation of surface meters without the overhead of Haversine formulas.

**2. Min-Max Attribute Normalization:**
$$X_{norm} = \frac{X - X_{min}}{X_{max} - X_{min}}$$
Applied independently to Property Value and Age.

**3. Weighted Euclidean Attribute Distance:**
For two valid adjacent blocks $i$ and $j$, the attribute metric distance evaluating dissimilarity across dimensions $V$ (Value), $A$ (Age), and $Z$ (Zoning percentage vectors) is defined as:
$$d_{attr} = \sqrt{\alpha (\Delta V)^2 + \beta (\Delta A)^2 + \gamma ||\Delta Z||_2^2}$$

**4. 0-Dimensional Topological Persistence:**
For a superlevel/sublevel Vietoris-Rips filtration where all discrete block entities exist at initiation:
$$Birth_i = 0$$
$$Persistence_i = Death_i - Birth_i = d_{attr}^{merge}$$

---

## 5. Assumptions and Constants Required

### Explicit Constants
- **Latitude Center ($49.2^{\circ}$):** The defined central latitude for calculating Metro Vancouver projection ratios.
- **Outlier Trimming ($2\%$):** The top 2% of persistence values are trimmed during gap analysis. This avoids situations where a massive, singular localized anomaly (e.g., an ultra-luxury tower directly adjacent to social housing) creates an infinite-seeming gap that overshadows the generalized broader neighborhood structure.
- **Noise Floor ($10^{th}$ Percentile):** Any persistence feature below the 10th percentile is categorically ignored as local noise rather than meaningful structural variation.
- **Minimum Gap Threshold ($5\%$):** The algorithm requires the topological gap to exceed `0.05 * (max_dist - min_meaningful)`.
- **Default Parameter Weights:** $\alpha = 0.333, \beta = 0.333, \gamma = 0.334$. Establishing mathematically balanced Euclidean dimensions prior to any gradient optimization.

### Structural Assumptions
1. **Centroid Geometric Representation:** It is assumed that 2D polygonal block centroids adequately represent the geometry and proximity of the entire block for 150m spatial proximity ($\varepsilon_1$) Kd-Tree queries.
2. **Local Flatness (Elliptical geometry vs. Haversine):** At the municipal scale of Vancouver, it is assumed that applying the scalar $\cos(49.2^{\circ})$ adjustment to geographical coordinates produces negligible distortion for proximity-grouping logic compared to heavy true-globe geometry processing.
3. **Vietoris-Rips Mapping:** The analysis assumes that standard 0-dimensional Vietoris-Rips topological evolution (where all components are born at zero distance) perfectly mirrors the organic clustering behavior of socio-economic neighborhood formation over geographic space.
4. **Sharpness as Phase Transition:** A fundamental assumption is that sudden, disproportionately large gaps in attribute-merging distances directly encode non-linear socio-economic phase-transitions (physical fault lines in the community fabric), and it is at these precise phase changes that behavioral phenomena such as localized property crime are uniquely influenced.
