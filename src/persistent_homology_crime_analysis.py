"""
Persistent Homology Analysis of Crime Patterns
==============================================

This script demonstrates how Persistent Homology (PH) can be used to understand
patterns in crime data, particularly break and enter incidents in Vancouver.

What is Persistent Homology?
---------------------------
Persistent homology is a technique from topological data analysis (TDA) that studies
the "shape" of data by analyzing how topological features (connected components, loops,
cavities) emerge and disappear as we build a filtration from the data.

Key Concepts:
1. POINTS: In our case, each crime incident is represented as a point in 2D space (X, Y coordinates)
2. FILTRATION: We gradually increase a "radius" around each point, connecting nearby points
3. COMPLEXES: As radius grows, points connect, forming clusters (0-dimensional features),
   then loops appear (1-dimensional features), and holes (2-dimensional features)
4. PERSISTENCE: We track when features are born (appear) and die (disappear) as radius increases
5. BARCODE: A visualization showing the "lifetime" of each topological feature

Why is PH useful for crime analysis?
-----------------------------------
- It reveals spatial clustering patterns without assuming any particular shape
- It identifies the density structure and nested clusters in crime hotspots
- It's robust to noise and outliers in the data
- It provides quantitative measures of cluster persistence (some clusters are very stable)

Interpretation:
- Long bars in the barcode = stable features (robust clusters of crimes)
- Short bars = noise or small isolated incidents
- H0 (0-dimensional homology) = connected components (clusters)
- H1 (1-dimensional homology) = loops/cavities in the crime distribution
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from ripser import ripser
from sklearn.preprocessing import StandardScaler
import seaborn as sns

# =============================================================================
# STEP 1: Load and Prepare Crime Data
# =============================================================================
print("Loading crime data...")
crime_df = pd.read_csv('../outputs/processed/cleaned_break_enter_data.csv')

# Extract X, Y coordinates - these represent the spatial locations of crimes
crime_coords = crime_df[['X', 'Y']].dropna().values
print(f"Loaded {len(crime_coords)} crime incidents")
print(f"Spatial range - X: [{crime_coords[:, 0].min():.0f}, {crime_coords[:, 0].max():.0f}]")
print(f"              Y: [{crime_coords[:, 1].min():.0f}, {crime_coords[:, 1].max():.0f}]")

# =============================================================================
# STEP 2: Standardize the Data
# =============================================================================
# Persistent homology is scale-sensitive, so we standardize coordinates
# This ensures equal weighting of X and Y dimensions
scaler = StandardScaler()
crime_coords_normalized = scaler.fit_transform(crime_coords)

print("\nData standardized for PH analysis")

# =============================================================================
# STEP 3: Compute Persistent Homology
# =============================================================================
print("\nComputing persistent homology using Vietoris-Rips complex...")
"""
The Vietoris-Rips complex is constructed as follows:
- Start with each point as its own component (connected components, H0)
- Gradually increase radius epsilon
- When two points are within distance epsilon, connect them with an edge
- When 3 points are mutually within distance epsilon, fill the triangle
- Continue until all points form one connected component

The ripser algorithm is highly efficient and computes this for all epsilon values
at once, tracking when topological features are "born" and "die".
"""

result = ripser(crime_coords_normalized, maxdim=1)

# Extract persistence pairs for both H0 and H1
h0_pairs = result['dgms'][0]  # 0-dimensional features (connected components/clusters)
h1_pairs = result['dgms'][1]  # 1-dimensional features (loops/voids)

# Calculate persistence values (lifetime of each feature)
h0_persistence = h0_pairs[:, 1] - h0_pairs[:, 0]
h1_persistence = h1_pairs[:, 1] - h1_pairs[:, 0]

print(f"H0 (Clusters): {len(h0_pairs)} features detected")
print(f"  - Finite features: {np.sum(np.isfinite(h0_pairs[:, 1]))}")
print(f"  - Max persistence (stability): {np.max(h0_persistence[np.isfinite(h0_persistence)]):.4f}")
print(f"  - Mean persistence: {np.mean(h0_persistence[np.isfinite(h0_persistence)]):.4f}")

print(f"\nH1 (Loops/Voids): {len(h1_pairs)} features detected")
if len(h1_pairs) > 0 and np.any(np.isfinite(h1_persistence)):
    print(f"  - Persistent loops: {np.sum(h1_persistence > np.percentile(h1_persistence[np.isfinite(h1_persistence)], 75))}")
    print(f"  - Max persistence: {np.max(h1_persistence[np.isfinite(h1_persistence)]):.4f}")

# =============================================================================
# STEP 4: Analyze and Extract Insights
# =============================================================================

# Filter out infinite features (will be handled separately)
h0_finite = h0_pairs[np.isfinite(h0_pairs[:, 1])]
h1_finite = h1_pairs[np.isfinite(h1_pairs[:, 1])]

# Find the most persistent (significant) clusters
h0_persistence_finite = h0_finite[:, 1] - h0_finite[:, 0]
top_10_h0_indices = np.argsort(h0_persistence_finite)[-10:][::-1]

print("\n" + "="*70)
print("TOP 10 MOST PERSISTENT CRIME CLUSTERS (Significant Hotspots)")
print("="*70)
print(f"{'Rank':<5} {'Birth':<12} {'Death':<12} {'Persistence':<12} {'Interpretation'}")
print("-"*70)
for i, idx in enumerate(top_10_h0_indices, 1):
    birth = h0_finite[idx, 0]
    death = h0_finite[idx, 1]
    persistence = death - birth
    print(f"{i:<5} {birth:<12.4f} {death:<12.4f} {persistence:<12.4f} Stable cluster")

# Analyze H1 features if present
if len(h1_finite) > 0:
    h1_persistence_finite = h1_finite[:, 1] - h1_finite[:, 0]
    significant_h1 = h1_finite[h1_persistence_finite > np.percentile(h1_persistence_finite, 90)]
    
    print("\n" + "="*70)
    print("SIGNIFICANT LOOPS/VOIDS IN CRIME DISTRIBUTION")
    print("="*70)
    print(f"Number of significant loops: {len(significant_h1)}")
    print("These represent regions with non-trivial topological structure.")
    print("Such structures might indicate multiple crime hotspots surrounding a safer zone.")

# =============================================================================
# STEP 5: Visualize Persistence Barcodes
# =============================================================================
print("\nGenerating persistence barcode visualizations...")

fig, axes = plt.subplots(2, 2, figsize=(14, 10))

# -------- Plot 1: H0 Persistence Barcode (All features) --------
ax1 = axes[0, 0]
# Sort by birth time for clarity
h0_sorted_indices = np.argsort(h0_pairs[:, 0])
h0_sorted = h0_pairs[h0_sorted_indices]

# Plot births and deaths as horizontal lines
for i, (birth, death) in enumerate(h0_sorted):
    if np.isinf(death):
        # Infinite features (one connected component remains)
        ax1.barh(i, 1000, left=birth, height=0.8, color='blue', alpha=0.6)
    else:
        # Finite features
        ax1.barh(i, death - birth, left=birth, height=0.8, color='orange', alpha=0.6)

ax1.set_xlabel('Filtration Value (radius)', fontsize=10, fontweight='bold')
ax1.set_ylabel('Feature Index', fontsize=10, fontweight='bold')
ax1.set_title('H0 Barcode: Crime Cluster Formation and Merging\n(Orange=finite, Blue=survives to end)', 
              fontsize=11, fontweight='bold')
ax1.grid(True, alpha=0.3)

# -------- Plot 2: H1 Persistence Barcode --------
ax2 = axes[0, 1]
if len(h1_pairs) > 0:
    h1_sorted_indices = np.argsort(h1_pairs[:, 0])
    h1_sorted = h1_pairs[h1_sorted_indices]
    
    for i, (birth, death) in enumerate(h1_sorted):
        if np.isinf(death):
            ax2.barh(i, 1000, left=birth, height=0.8, color='green', alpha=0.6)
        else:
            ax2.barh(i, death - birth, left=birth, height=0.8, color='red', alpha=0.6)
    
    ax2.set_xlabel('Filtration Value (radius)', fontsize=10, fontweight='bold')
    ax2.set_ylabel('Feature Index', fontsize=10, fontweight='bold')
    ax2.set_title('H1 Barcode: Loops and Voids in Crime Distribution\n(Red=finite loops, Green=persisting)', 
                  fontsize=11, fontweight='bold')
    ax2.grid(True, alpha=0.3)
    ax2.set_xlim(left=0)
else:
    ax2.text(0.5, 0.5, 'No H1 features detected', ha='center', va='center')
    ax2.set_title('H1 Barcode: No significant voids detected')

# -------- Plot 3: Persistence Diagram (Birth-Death Plot) --------
ax3 = axes[1, 0]

# Only plot finite H0 features
h0_finite_persistence = h0_finite[:, 1] - h0_finite[:, 0]
ax3.scatter(h0_finite[:, 0], h0_finite_persistence, alpha=0.6, s=50, 
            label='H0 (Clusters)', color='orange')

# Plot H1 features if present
if len(h1_finite) > 0:
    h1_finite_persistence = h1_finite[:, 1] - h1_finite[:, 0]
    ax3.scatter(h1_finite[:, 0], h1_finite_persistence, alpha=0.6, s=50, 
                label='H1 (Loops)', color='red')

ax3.set_xlabel('Birth (filtration value)', fontsize=10, fontweight='bold')
ax3.set_ylabel('Persistence (death - birth)', fontsize=10, fontweight='bold')
ax3.set_title('Persistence Diagram\n(Higher = more significant features)', 
              fontsize=11, fontweight='bold')
ax3.legend()
ax3.grid(True, alpha=0.3)

# -------- Plot 4: Distribution of Persistence Values --------
ax4 = axes[1, 1]
ax4.hist(h0_persistence_finite, bins=50, alpha=0.7, label='H0 (Clusters)', 
         color='orange', edgecolor='black')
if len(h1_finite) > 0:
    ax4.hist(h1_persistence_finite, bins=30, alpha=0.7, label='H1 (Loops)', 
             color='red', edgecolor='black')
ax4.set_xlabel('Persistence Value', fontsize=10, fontweight='bold')
ax4.set_ylabel('Frequency', fontsize=10, fontweight='bold')
ax4.set_title('Distribution of Feature Lifetimes\n(Right-skewed = few long-lasting features)', 
              fontsize=11, fontweight='bold')
ax4.legend()
ax4.grid(True, alpha=0.3, axis='y')

plt.tight_layout()
plt.savefig('../outputs/images/persistent_homology_barcode.png', dpi=300, bbox_inches='tight')
print("✓ Saved '../outputs/images/persistent_homology_barcode.png'")

# =============================================================================
# STEP 6: Spatial Visualization of Crime Data and Clusters
# =============================================================================
fig, ax = plt.subplots(figsize=(12, 10))

# Plot all crime incidents
scatter = ax.scatter(crime_coords[:, 0], crime_coords[:, 1], 
                     alpha=0.4, s=20, c='lightblue', edgecolors='navy', linewidth=0.5,
                     label='Crime incidents')

ax.set_xlabel('X Coordinate (UTM)', fontsize=11, fontweight='bold')
ax.set_ylabel('Y Coordinate (UTM)', fontsize=11, fontweight='bold')
ax.set_title('Spatial Distribution of Break and Enter Incidents in Vancouver\n' +
             '(Persistent homology reveals the underlying topological structure)', 
             fontsize=12, fontweight='bold')
ax.legend(fontsize=10)
ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig('../outputs/images/crime_spatial_distribution.png', dpi=300, bbox_inches='tight')
print("✓ Saved '../outputs/images/crime_spatial_distribution.png'")

plt.show()

# =============================================================================
# STEP 7: Key Findings and Interpretation
# =============================================================================
print("\n" + "="*70)
print("PERSISTENT HOMOLOGY ANALYSIS: KEY FINDINGS")
print("="*70)

print("\n1. CLUSTER STRUCTURE (H0 Features):")
print(f"   - Total clusters detected: {len(h0_pairs)}")
print(f"   - This represents how the crime locations form hierarchical clusters")
print(f"   - Most clusters are small (short persistence) - these are noise")
print(f"   - Few clusters have high persistence - these are TRUE hotspots")

print("\n2. TOPOLOGICAL STRUCTURE (H1 Features):")
if len(h1_finite) > 0:
    print(f"   - Loops detected: {len(h1_finite)}")
    print(f"   - These indicate non-convex cluster shapes or multiple hotspots")
    print(f"   - Long-lived loops suggest stable topological patterns")
else:
    print(f"   - No significant loops detected")
    print(f"   - Crime hotspots appear convex and well-separated")

print("\n3. NOISE VS. SIGNAL:")
persistence_threshold = np.percentile(h0_persistence_finite, 90)
signal_clusters = np.sum(h0_persistence_finite > persistence_threshold)
print(f"   - Noise clusters (bottom 10%): {len(h0_persistence_finite) - signal_clusters}")
print(f"   - Signal clusters (top 10%): {signal_clusters}")
print(f"   - Persistence threshold: {persistence_threshold:.4f}")

print("\n4. SCALE OF HOTSPOTS:")
avg_persistence = np.mean(h0_persistence_finite)
print(f"   - Average cluster size (persistence): {avg_persistence:.4f}")
print(f"   - This represents the typical spatial scale of crime clusters")

print("\n" + "="*70)
print("ADVANTAGES OF PERSISTENT HOMOLOGY FOR CRIME ANALYSIS:")
print("="*70)
print("✓ Doesn't assume any particular shape for crime clusters")
print("✓ Identifies hierarchical structure in crime patterns")
print("✓ Robust to noise and outliers")
print("✓ Quantifies stability/significance of clusters")
print("✓ Reveals multi-scale structure (from individual hotspots to city-wide patterns)")
print("✓ Can be used for anomaly detection and forecasting")

print("\n" + "="*70)
print("Analysis complete! Check the generated PNG files for visualizations.")
print("="*70)
