"""
Property Similarity Analysis Module

Core module for creating similarity-based blocks from property data.
This is the PRIMARY analysis unit for the research, replacing traditional
administrative boundaries with data-driven blocks based on property characteristics.

Research: Vancouver Crime Pattern Analysis with Property Similarity
Author: Research Team
Date: February 2026
"""

import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import HDBSCAN # Updated to HDBSCAN
from typing import List, Tuple, Dict, Optional
import streamlit as st

from utils.geo_utils import create_convex_hull
from config import (
    DEFAULT_SIMILARITY_THRESHOLD,
    DEFAULT_MIN_CLUSTER_SIZE,
    SIMILARITY_COLORS
)


# =============================================================================
# FEATURE EXTRACTION
# =============================================================================

def extract_similarity_features(properties_df: pd.DataFrame,
                               selected_variables: List[str]) -> Tuple[pd.DataFrame, np.ndarray]:
    """
    Extract and normalize features for similarity analysis
    
    Args:
        properties_df: DataFrame with property data
        selected_variables: List of variable names to include:
            - 'property_value': Total property value
            - 'building_age': Age of building
            - 'property_type': Residential/Commercial/Industrial/Mixed
            - 'tax_levy': Tax amount (if available)
            - 'zoning': Zoning category
            - 'lot_size': Size of lot (if available)
    
    Returns:
        Tuple of (filtered_properties_df, feature_matrix)
        - filtered_properties_df: Properties with valid features
        - feature_matrix: Normalized feature matrix (n_properties × n_features)
    """
    print(f"\n🔬 Extracting features: {selected_variables}")
    
    # Start with copy of dataframe
    df = properties_df.copy()
    
    # Initialize feature list
    feature_columns = []
    
    # Property value
    if 'property_value' in selected_variables:
        if 'property_value' not in df.columns:
            print("   ⚠️ property_value not found in data")
        else:
            df = df[df['property_value'] > 0]
            feature_columns.append('property_value')
            print(f"   ✓ Property value: ${df['property_value'].min():,.0f} - ${df['property_value'].max():,.0f}")
    
    # Building age
    if 'building_age' in selected_variables:
        if 'building_age' not in df.columns:
            print("   ⚠️ building_age not found in data")
        else:
            df = df[df['building_age'].notna()]
            df = df[df['building_age'] >= 0]
            feature_columns.append('building_age')
            print(f"   ✓ Building age: {df['building_age'].min():.0f} - {df['building_age'].max():.0f} years")
    
    # Property type (categorical → one-hot encoding)
    if 'property_type' in selected_variables:
        if 'property_type' not in df.columns:
            print("   ⚠️ property_type not found in data")
        else:
            # One-hot encode property type
            type_dummies = pd.get_dummies(df['property_type'], prefix='type')
            df = pd.concat([df, type_dummies], axis=1)
            feature_columns.extend(type_dummies.columns.tolist())
            print(f"   ✓ Property types: {df['property_type'].value_counts().to_dict()}")
    
    # Tax levy
    if 'tax_levy' in selected_variables:
        if 'TAX_LEVY' in df.columns:
            df['tax_levy'] = pd.to_numeric(df['TAX_LEVY'], errors='coerce')
            df = df[df['tax_levy'].notna()]
            df = df[df['tax_levy'] > 0]
            feature_columns.append('tax_levy')
            print(f"   ✓ Tax levy included")
        else:
            print("   ⚠️ TAX_LEVY not found in data")
    
    # Zoning (categorical → one-hot encoding)
    if 'zoning' in selected_variables:
        if 'ZONING_CLASSIFICATION' in df.columns:
            # One-hot encode top N zoning categories (to avoid too many features)
            top_zones = df['ZONING_CLASSIFICATION'].value_counts().head(10).index
            df['zoning_category'] = df['ZONING_CLASSIFICATION'].apply(
                lambda x: x if x in top_zones else 'Other'
            )
            zone_dummies = pd.get_dummies(df['zoning_category'], prefix='zone')
            df = pd.concat([df, zone_dummies], axis=1)
            feature_columns.extend(zone_dummies.columns.tolist())
            print(f"   ✓ Zoning categories: {df['zoning_category'].value_counts().to_dict()}")
        else:
            print("   ⚠️ ZONING_CLASSIFICATION not found in data")
    
    # Filter to properties with all selected features
    df = df.dropna(subset=feature_columns)
    
    if len(df) == 0:
        print("   ❌ No properties with all selected features!")
        return df, np.array([])
    
    # Extract feature matrix
    feature_matrix = df[feature_columns].values
    
    # Normalize features (z-score standardization)
    scaler = StandardScaler()
    feature_matrix_normalized = scaler.fit_transform(feature_matrix)
    
    print(f"   ✅ Feature matrix: {len(df):,} properties × {len(feature_columns)} features")
    
    return df, feature_matrix_normalized


# =============================================================================
# CLUSTERING & BLOCK CREATION (HDBSCAN - Topological)
# =============================================================================

@st.cache_data(show_spinner="Computing topological similarity zones...")
def create_similarity_blocks(_properties_df: pd.DataFrame,
                            selected_variables: List[str],
                            similarity_threshold: float,
                            min_cluster_size: int = 10) -> Tuple[pd.DataFrame, Dict]:
    """
    Create similarity-based blocks using HDBSCAN (Hierarchical Density-Based Spatial Clustering).
    This uses topological persistence to find stable clusters.
    
    Args:
        _properties_df: DataFrame with property data
        selected_variables: Variables to use for similarity
        similarity_threshold: Controls how strict the clustering is (maps to cluster_selection_epsilon)
                              Higher threshold = Stricter = Smaller epsilon = More fragmented zones
        min_cluster_size: Minimum properties to form a zone
    
    Returns:
        Tuple of (properties_with_blocks, block_stats)
    """
    from sklearn.cluster import HDBSCAN
    
    properties_df = _properties_df.copy()
    
    print("\n" + "="*70)
    print("🏘️  CREATING TOPOLOGICAL ZONES (HDBSCAN)")
    print("="*70)
    
    # Extract features
    df_features, feature_matrix = extract_similarity_features(
        properties_df, selected_variables
    )
    
    if len(df_features) == 0:
        print("❌ Cannot create blocks - no valid properties")
        return properties_df, {}
    
    # Map Similarity Threshold (0.1 - 0.9) to Epsilon
    # Similarity 0.9 (High) -> Epsilon 0.1 (Small distance allowed)
    # Similarity 0.1 (Low)  -> Epsilon 1.0+ (Large distance allowed)
    # Formula: epsilon = (1 - similarity) * Scale Factor
    # We use a scale factor because normalized features have variance ~1
    
    # Heuristic: For normalized data (std=1), a distance of 0.5 is "very close", 
    # 2.0 is "far".
    # If High Similarity (0.9) -> epsilon should be small (e.g. 0.3)
    # If Low Similarity (0.1) -> epsilon should be large (e.g. 2.0 or None)
    
    epsilon = (1.0 - similarity_threshold) * 3.0
    if epsilon < 0.1: epsilon = 0.1 # Minimum epsilon to avoid overfitting
    
    print(f"\n🎯 Clustering with HDBSCAN:")
    print(f"   Similarity: {similarity_threshold:.0%}")
    print(f"   Epsilon (Max Distance): {epsilon:.3f}")
    print(f"   Min Cluster Size: {min_cluster_size}")
    
    # Run HDBSCAN
    # metric='euclidean' on normalized features implies that "distance" = "dissimilarity"
    clusterer = HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=None, # Auto (usually equal to min_cluster_size)
        cluster_selection_epsilon=epsilon,
        metric='euclidean',
        store_centers='centroid',
        n_jobs=-1 # Use all cores
    )
    
    cluster_labels = clusterer.fit_predict(feature_matrix)
    
    # Add cluster labels to dataframe
    df_features['block_id'] = cluster_labels
    df_features['similarity_group'] = cluster_labels.copy()
    
    # Add STABILITY score (Probability)
    # unique to HDBSCAN
    if hasattr(clusterer, 'probabilities_'):
        df_features['zone_stability'] = clusterer.probabilities_
    else:
        df_features['zone_stability'] = 1.0
        
    # -1 means noise (unclustered)
    noise_mask = cluster_labels == -1
    n_noise = noise_mask.sum()
    
    if n_noise > 0:
        # Assign unique IDs to noise points (starting from max_cluster + 1)
        max_cluster = cluster_labels.max()
        if max_cluster == -1: max_cluster = 0
            
        noise_ids = np.arange(max_cluster + 1, max_cluster + 1 + n_noise)
        df_features.loc[noise_mask, 'block_id'] = noise_ids
        df_features.loc[noise_mask, 'similarity_group'] = -1  # Keep -1 for coloring
        df_features.loc[noise_mask, 'zone_stability'] = 0.0 # Noise has 0 stability
    
    # Count blocks
    n_blocks = len(set(cluster_labels)) - (1 if -1 in cluster_labels else 0)
    
    print(f"\n✅ Created {n_blocks} topological zones")
    print(f"   Properties in zones: {(~noise_mask).sum():,}")
    print(f"   Unclustered (Noise): {n_noise:,}")
    
    # Calculate block statistics
    block_stats = {}
    for block_id in df_features['block_id'].unique():
        if block_id == -1:
            continue
            
        # If it was originally noise but we gave it a unique ID, we still want stats
        # But 'similarity_group' will be -1 for noise.
        # Let's map stats by 'block_id' (unique) but group by 'similarity_group' (visual)
        
        is_noise = df_features.loc[df_features['block_id'] == block_id, 'similarity_group'].iloc[0] == -1
        if is_noise:
            # Skip computing full stats for individual noise points to save time?
            # Or keep them? Let's keep them but mark as noise.
            pass

        block_properties = df_features[df_features['block_id'] == block_id]
        
        # Determine dominant characteristics for labeling
        avg_val = block_properties['property_value'].mean()
        avg_age = block_properties['building_age'].mean() if 'building_age' in block_properties.columns else 0
        
        label = f"Zone {block_id}"
        if avg_val > 2000000: label += " | High Value"
        elif avg_val < 800000: label += " | Affordable"
        else: label += " | Mid Market"
        
        block_stats[block_id] = {
            'n_properties': len(block_properties),
            'avg_property_value': avg_val,
            'median_property_value': block_properties['property_value'].median(),
            'avg_building_age': avg_age,
            'primary_type': block_properties['property_type'].mode()[0] if 'property_type' in block_properties.columns else None,
            'stability': block_properties['zone_stability'].mean(),
            'is_noise': is_noise,
            'label': label,
            'properties_coords': block_properties[['latitude', 'longitude']].dropna().values.tolist(),
            # Convert Shapely Polygon to list of [lat, lon] for Folium
        }
        
        # Calculate convex hull
        hull = create_convex_hull(block_properties[['latitude', 'longitude']].dropna().values.tolist())
        if hull:
            # Extract coords (lon, lat) from Shapely and convert to (lat, lon) for Folium
            # Shapely stores (x, y) = (lon, lat)
            hull_coords = [[lat, lon] for lon, lat in hull.exterior.coords]
            block_stats[block_id]['convex_hull'] = hull_coords
        else:
            block_stats[block_id]['convex_hull'] = None
    
    # Merge back with original dataframe
    result_df = properties_df.merge(
        df_features[['PID', 'block_id', 'similarity_group', 'zone_stability']],
        on='PID',
        how='left'
    )
    
    print(f"\n📊 Zone size distribution:")
    block_sizes = df_features[df_features['similarity_group'] != -1].groupby('similarity_group').size()
    if not block_sizes.empty:
        print(f"   Min: {block_sizes.min()} properties")
        print(f"   Median: {block_sizes.median():.0f} properties")
        print(f"   Max: {block_sizes.max()} properties")
    print("="*70 + "\n")
    
    return result_df, block_stats


# =============================================================================
# BLOCK ENRICHMENT (Add crime, transit, lighting stats)
# =============================================================================

def enrich_blocks_with_crime(properties_with_blocks: pd.DataFrame,
                             crime_df: pd.DataFrame,
                             block_stats: Dict) -> Dict:
    """
    Add crime statistics to each block
    
    Args:
        properties_with_blocks: Properties with block_id assigned
        crime_df: Crime data with latitude/longitude
        block_stats: Dictionary of block statistics
    
    Returns:
        Updated block_stats with crime counts
    """
    from utils.geo_utils import point_in_polygon, create_convex_hull
    
    print("\n🚨 Enriching blocks with crime data...")
    
    for block_id, stats in block_stats.items():
        # Get property coordinates for this block
        coords = stats.get('properties_coords', [])
        
        if len(coords) < 3:
            stats['crime_count'] = 0
            stats['crime_rate'] = 0.0
            continue
        
        # Create convex hull polygon for block
        # Convert coords from list of lists to list of tuples
        coord_tuples = [(lat, lon) for lat, lon in coords if not (np.isnan(lat) or np.isnan(lon))]
        
        if len(coord_tuples) < 3:
            stats['crime_count'] = 0
            stats['crime_rate'] = 0.0
            continue
        
        polygon = create_convex_hull(coord_tuples)
        
        if polygon is None:
            stats['crime_count'] = 0
            stats['crime_rate'] = 0.0
            continue
        
        # Count crimes within this block
        crime_count = 0
        for _, crime in crime_df.iterrows():
            if point_in_polygon(crime['latitude'], crime['longitude'], polygon):
                crime_count += 1
        
        stats['crime_count'] = crime_count
        stats['crime_rate'] = crime_count / stats['n_properties']  # Crimes per property
    
    print(f"   ✅ Crime statistics added to {len(block_stats)} blocks")
    
    return block_stats
