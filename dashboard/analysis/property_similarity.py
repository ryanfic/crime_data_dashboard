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
from sklearn.cluster import DBSCAN, AgglomerativeClustering
from sklearn.metrics import pairwise_distances
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
# SIMILARITY CALCULATION
# =============================================================================

def calculate_pairwise_similarity(feature_matrix: np.ndarray,
                                  metric: str = 'euclidean') -> np.ndarray:
    """
    Calculate pairwise similarity between all properties
    
    Args:
        feature_matrix: Normalized feature matrix (n × p)
        metric: Distance metric ('euclidean', 'manhattan', 'cosine')
    
    Returns:
        Similarity matrix (n × n), where similarity ∈ [0, 1]
        Higher values = more similar
    """
    print(f"\n📐 Calculating pairwise similarity ({metric} distance)...")
    
    # Calculate pairwise distances
    distances = pairwise_distances(feature_matrix, metric=metric)
    
    # Convert distances to similarities
    # similarity = 1 / (1 + distance)
    # This maps distance ∈ [0, ∞) to similarity ∈ (0, 1]
    similarity_matrix = 1 / (1 + distances)
    
    # Diagonal should be 1 (property is identical to itself)
    np.fill_diagonal(similarity_matrix, 1.0)
    
    print(f"   Similarity range: {similarity_matrix.min():.3f} - {similarity_matrix.max():.3f}")
    print(f"   Mean similarity: {similarity_matrix.mean():.3f}")
    
    return similarity_matrix


# =============================================================================
# CLUSTERING & BLOCK CREATION
# =============================================================================

@st.cache_data(show_spinner="Computing similarity blocks...")
def create_similarity_blocks(_properties_df: pd.DataFrame,
                            selected_variables: List[str],
                            similarity_threshold: float,
                            min_cluster_size: int = 10) -> Tuple[pd.DataFrame, Dict]:
    """
    Create similarity-based blocks by clustering similar properties
    
    Args:
        _properties_df: DataFrame with property data (underscore to prevent caching issues)
        selected_variables: Variables to use for similarity
        similarity_threshold: Minimum similarity (0-1) for grouping
        min_cluster_size: Minimum properties per block
    
    Returns:
        Tuple of (properties_with_blocks, block_stats)
        - properties_with_blocks: Original df with 'block_id' and 'similarity_group' added
        - block_stats: Dictionary with block-level statistics
    """
    properties_df = _properties_df.copy()
    
    print("\n" + "="*70)
    print("🏘️  CREATING SIMILARITY-BASED BLOCKS")
    print("="*70)
    
    # Extract features
    df_features, feature_matrix = extract_similarity_features(
        properties_df, selected_variables
    )
    
    if len(df_features) == 0:
        print("❌ Cannot create blocks - no valid properties")
        return properties_df, {}
    
    # Calculate similarity
    similarity_matrix = calculate_pairwise_similarity(feature_matrix)
    
    # Convert similarity threshold to distance threshold
    # similarity = 1 / (1 + distance)
    # distance = (1 / similarity) - 1
    distance_threshold = (1 / similarity_threshold) - 1
    
    print(f"\n🎯 Clustering with threshold {similarity_threshold:.0%} (distance ≤ {distance_threshold:.2f})")
    
    # Cluster using DBSCAN (density-based spatial clustering)
    # eps = distance threshold
    # min_samples = minimum cluster size
    clusterer = DBSCAN(
        eps=distance_threshold,
        min_samples=min_cluster_size,
        metric='precomputed'
    )
    
    # Convert similarity to distance for DBSCAN
    distance_matrix = (1 / similarity_matrix) - 1
    np.fill_diagonal(distance_matrix, 0.0)
    
    # Fit clustering
    cluster_labels = clusterer.fit_predict(distance_matrix)
    
    # Add cluster labels to dataframe
    df_features['block_id'] = cluster_labels
    df_features['similarity_group'] = cluster_labels.copy()
    
    # -1 means noise (unclustered), assign individual block IDs
    noise_mask = cluster_labels == -1
    n_noise = noise_mask.sum()
    if n_noise > 0:
        # Assign unique IDs to noise points (starting from max_cluster + 1)
        max_cluster = cluster_labels.max()
        noise_ids = np.arange(max_cluster + 1, max_cluster + 1 + n_noise)
        df_features.loc[noise_mask, 'block_id'] = noise_ids
        df_features.loc[noise_mask, 'similarity_group'] = -1  # Keep -1 for coloring
    
    # Count blocks
    n_blocks = len(set(cluster_labels)) - (1 if -1 in cluster_labels else 0)
    
    print(f"\n✅ Created {n_blocks} similarity blocks")
    print(f"   Properties in blocks: {(~noise_mask).sum():,}")
    print(f"   Unclustered properties: {n_noise:,}")
    
    # Calculate block statistics
    block_stats = {}
    for block_id in df_features['block_id'].unique():
        if block_id == -1:
            continue  # Skip noise
        
        block_properties = df_features[df_features['block_id'] == block_id]
        
        block_stats[block_id] = {
            'n_properties': len(block_properties),
            'avg_property_value': block_properties['property_value'].mean(),
            'median_property_value': block_properties['property_value'].median(),
            'avg_building_age': block_properties['building_age'].mean() if 'building_age' in block_properties.columns else None,
            'primary_type': block_properties['property_type'].mode()[0] if 'property_type' in block_properties.columns else None,
            # Convex hull for spatial representation
            'properties_coords': block_properties[['latitude', 'longitude']].dropna().values.tolist()
        }
    
    # Merge back with original dataframe
    result_df = properties_df.merge(
        df_features[['PID', 'block_id', 'similarity_group']],
        on='PID',
        how='left'
    )
    
    print(f"\n📊 Block size distribution:")
    block_sizes = df_features[df_features['block_id'] != -1].groupby('block_id').size()
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
