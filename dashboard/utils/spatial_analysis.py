"""
Spatial analysis utilities for crime and lighting coverage

Author: Research Team
Date: February 2026
"""

import numpy as np
from typing import Tuple
import pandas as pd


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great circle distance between two points on Earth (in meters)
    
    Args:
        lat1, lon1: First point coordinates
        lat2, lon2: Second point coordinates
    
    Returns:
        Distance in meters
    """
    # Convert to radians
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    
    # Haversine formula
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat/2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2)**2
    c = 2 * np.arcsin(np.sqrt(a))
    
    # Earth radius in meters
    r = 6371000
    
    return c * r


def find_nearest_light_distance(crime_lat: float, crime_lon: float, 
                                 lights_df: pd.DataFrame) -> float:
    """
    Find the distance to the nearest street light from a crime location
    
    Args:
        crime_lat, crime_lon: Crime location coordinates
        lights_df: DataFrame with street light locations (must have 'latitude', 'longitude')
    
    Returns:
        Distance to nearest light in meters
    """
    if len(lights_df) == 0:
        return float('inf')
    
    # Vectorized distance calculation to all lights
    distances = haversine_distance(
        crime_lat, crime_lon,
        lights_df['latitude'].values, lights_df['longitude'].values
    )
    
    return np.min(distances)


def analyze_crimes_outside_lights(crimes_df: pd.DataFrame, 
                                   lights_df: pd.DataFrame,
                                   light_radius: float = 30) -> Tuple[pd.DataFrame, dict]:
    """
    Analyze which crimes occur outside street light coverage
    
    Args:
        crimes_df: DataFrame with crime locations (must have 'latitude', 'longitude')
        lights_df: DataFrame with street light locations (must have 'latitude', 'longitude')
        light_radius: Coverage radius of each light in meters (default: 30m)
    
    Returns:
        Tuple of:
            - crimes_df with added 'distance_to_light' and 'outside_light' columns
            - Dictionary with analysis statistics
    """
    # Make a copy to avoid modifying original
    crimes = crimes_df.copy()
    
    # Calculate distance to nearest light for each crime
    crimes['distance_to_light'] = crimes.apply(
        lambda row: find_nearest_light_distance(row['latitude'], row['longitude'], lights_df),
        axis=1
    )
    
    # Mark crimes outside light coverage
    crimes['outside_light'] = crimes['distance_to_light'] > light_radius
    
    # Calculate statistics
    total_crimes = len(crimes)
    crimes_outside = crimes['outside_light'].sum()
    crimes_inside = total_crimes - crimes_outside
    percent_outside = (crimes_outside / total_crimes * 100) if total_crimes > 0 else 0
    
    stats = {
        'total_crimes': total_crimes,
        'crimes_inside_light': crimes_inside,
        'crimes_outside_light': crimes_outside,
        'percent_outside': percent_outside,
        'avg_distance_to_light': crimes['distance_to_light'].mean(),
        'median_distance_to_light': crimes['distance_to_light'].median()
    }
    
    return crimes, stats
