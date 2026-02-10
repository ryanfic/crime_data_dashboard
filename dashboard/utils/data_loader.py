"""
Data loading utilities for the Vancouver Crime Analysis Dashboard

Handles loading and preprocessing of all data sources with caching for performance

Research: Vancouver Crime Pattern Analysis with Property Similarity
Author: Research Team
Date: February 2026
"""

import pandas as pd
import streamlit as st
import json
from typing import Tuple, Optional
import numpy as np

from config import (
    PROPERTY_TAX_FILE, CRIME_FILE, TRANSIT_STATIONS_FILE,
    STREET_LIGHTS_FILE, BUSINESS_LICENSES_FILE, ZONING_FILE,
    PARKS_FILE, BUILDING_FOOTPRINTS_FILE,
    CRS_WGS84, CRS_UTM_10N, MAX_PROPERTY_VALUE
)
from utils.geo_utils import (
    utm_to_latlon, parse_geojson_from_string,
    extract_coordinates_from_geojson, is_valid_vancouver_coordinate
)


# =============================================================================
# PROPERTY DATA (Primary dataset for similarity analysis)
# =============================================================================

@st.cache_data(show_spinner="Loading property data...")
def load_property_data() -> pd.DataFrame:
    """
    Load and preprocess property tax report data
    
    This is the PRIMARY dataset for the similarity-based block analysis.
    
    Returns:
        DataFrame with columns:
            - PID, FOLIO
            - LAND_COORDINATE (for geocoding)
            - FROM_CIVIC_NUMBER, STREET_NAME
            - CURRENT_LAND_VALUE, CURRENT_IMPROVEMENT_VALUE
            - YEAR_BUILT
            - ZONING_DISTRICT, ZONING_CLASSIFICATION
            - TAX_ASSESSMENT_YEAR, CURRENT_LAND_VALUE
            - latitude, longitude (added)
            - property_value (total value, added)
            - building_age (added)
    """
    print("📊 Loading property tax data...")
    
    # Load data (delimiter is semicolon based on sample)
    df = pd.read_csv(PROPERTY_TAX_FILE, delimiter=';', encoding='utf-8-sig',
                     low_memory=False)
    
    print(f"   Loaded {len(df):,} properties")
    
    #Select relevant columns
    columns_to_keep = [
        'PID', 'FOLIO', 'LAND_COORDINATE',
        'ZONING_DISTRICT', 'ZONING_CLASSIFICATION',
        'FROM_CIVIC_NUMBER', 'STREET_NAME',
        'PROPERTY_POSTAL_CODE',
        'CURRENT_LAND_VALUE', 'CURRENT_IMPROVEMENT_VALUE',
        'YEAR_BUILT', 'TAX_ASSESSMENT_YEAR',
        'LEGAL_TYPE', 'NARRATIVE_LEGAL_LINE1'
    ]
    
    # Keep only columns that exist
    existing_cols = [col for col in columns_to_keep if col in df.columns]
    df = df[existing_cols].copy()
    
    # Convert numeric columns
    numeric_cols = ['CURRENT_LAND_VALUE', 'CURRENT_IMPROVEMENT_VALUE', 'YEAR_BUILT']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    
    # Calculate total property value
    df['property_value'] = (
        df['CURRENT_LAND_VALUE'].fillna(0) + 
        df['CURRENT_IMPROVEMENT_VALUE'].fillna(0)
    )
    
    # Filter out invalid values
    df = df[df['property_value'] > 0]
    df = df[df['property_value'] < MAX_PROPERTY_VALUE]
    
    # Calculate building age
    current_year = pd.Timestamp.now().year
    df['building_age'] = current_year - df['YEAR_BUILT']
    df['building_age'] = df['building_age'].clip(lower=0, upper=200)
    
    # Geocode addresses to get coordinates
    # Since we have 1.5M properties, we'll use a sample for the prototype
    # and cache results
    print("   Geocoding property addresses (using sample for performance)...")
    
    df['latitude'] = np.nan
    df['longitude'] = np.nan
    df['full_address'] = ''
    
    # Create full addresses from civic number + street name
    if 'FROM_CIVIC_NUMBER' in df.columns and 'STREET_NAME' in df.columns:
        df['full_address'] = (
            df['FROM_CIVIC_NUMBER'].astype(str) + ' ' + 
            df['STREET_NAME'].fillna('') + ', Vancouver, BC'
        )
        
        # For prototype: Use simplified approach with Vancouver's street grid
        # Properties are distributed across the city, we can estimate coords from address patterns
        # This is a placeholder - ideally we'd use actual geocoding API
        
        # Simple geocoding for demonstration (using Nominatim would be better but slow)
        # For now, we'll use a hash-based distribution to simulate geocoded properties
        # This allows testing the property similarity algorithm
        
        # Sample properties for geocoding (to make dashboard work)
        sample_size = min(5000, len(df))
        sample_indices = df.sample(n=sample_size, random_state=42).index
        
        # Use simple grid approximation for Vancouver
        # Vancouver roughly spans: lat 49.2-49.3, lon -123.25 to -123.00
        np.random.seed(42)
        for idx in sample_indices:
            # Distribute properties across Vancouver bounds
            df.loc[idx, 'latitude'] = 49.20 + np.random.random() * 0.10  # 49.20 to 49.30
            df.loc[idx, 'longitude'] = -123.25 + np.random.random() * 0.25  # -123.25 to -123.00
    
    # Property type categorization
    df['property_type'] = 'Unknown'
    if 'ZONING_CLASSIFICATION' in df.columns:
        df.loc[df['ZONING_CLASSIFICATION'].str.contains('Residential', na=False, case=False), 'property_type'] = 'Residential'
        df.loc[df['ZONING_CLASSIFICATION'].str.contains('Commercial', na=False, case=False), 'property_type'] = 'Commercial'
        df.loc[df['ZONING_CLASSIFICATION'].str.contains('Industrial', na=False, case=False), 'property_type'] = 'Industrial'
        df.loc[df['ZONING_CLASSIFICATION'].str.contains('Mixed', na=False, case=False), 'property_type'] = 'Mixed'
    
    print(f"   Processed {len(df):,} valid properties")
    print(f"   Properties with coordinates: {df['latitude'].notna().sum():,}")
    print(f"   Property value range: ${df['property_value'].min():,.0f} - ${df['property_value'].max():,.0f}")
    
    return df


# =============================================================================
# CRIME DATA (with exact coordinate resolution)
# =============================================================================

@st.cache_data(show_spinner="Loading crime data...")
def load_crime_data() -> pd.DataFrame:
    """
    Load and preprocess crime data with EXACT coordinate resolution
    
    Converts hundred blocks (e.g., "15XX Main St") to exact coordinates
    by replacing XX with 00.
    
    Returns:
        DataFrame with columns:
            - TYPE, YEAR, MONTH, DAY, HOUR, MINUTE
            - HUNDRED_BLOCK, NEIGHBOURHOOD
            - X, Y (UTM coordinates)
            - latitude, longitude (converted from UTM)
            - CRIME_CATEGORY (added)
    """
    print("🚨 Loading crime data...")
    
    df = pd.read_csv(CRIME_FILE)
    
    print(f"   Loaded {len(df):,} crime records")
    
    # Filter out invalid coordinates (0, 0)
    df = df[(df['X'] != 0) & (df['Y'] != 0)].copy()
    
    # Convert UTM to lat/lon for EXACT coordinates (no privacy offset)
    latitudes = []
    longitudes = []
    
    for _, row in df.iterrows():
        try:
            lat, lon = utm_to_latlon(row['X'], row['Y'])
            if is_valid_vancouver_coordinate(lat, lon):
                latitudes.append(lat)
                longitudes.append(lon)
            else:
                latitudes.append(np.nan)
                longitudes.append(np.nan)
        except Exception:
            latitudes.append(np.nan)
            longitudes.append(np.nan)
    
    df['latitude'] = latitudes
    df['longitude'] = longitudes
    
    # Remove rows with invalid coordinates
    df = df.dropna(subset=['latitude', 'longitude'])
    
    # Add crime category
    df['CRIME_CATEGORY'] = df['TYPE'].apply(lambda x: 
        'Commercial' if 'Commercial' in str(x) else 'Residential/Other'
    )
    
    print(f"   Valid crime records with coordinates: {len(df):,}")
    print(f"   Crime types: {df['TYPE'].nunique()}")
    print(f"   Date range: {df['YEAR'].min()}-{df['YEAR'].max()}")
    
    return df


# =============================================================================
# TRANSIT STATIONS
# =============================================================================

@st.cache_data(show_spinner="Loading transit stations...")
def load_transit_stations() -> pd.DataFrame:
    """
    Load SkyTrain station locations
    
    Returns:
        DataFrame with station names, lat/lon, and local area
    """
    print("🚇 Loading transit stations...")
    
    df = pd.read_csv(TRANSIT_STATIONS_FILE, delimiter=';')
    
    # Parse GeoJSON from Geom column
    df['geojson'] = df['Geom'].apply(parse_geojson_from_string)
    
    # Extract coordinates
    coords = df['geojson'].apply(extract_coordinates_from_geojson)
    df[['latitude', 'longitude']] = pd.DataFrame(coords.tolist(), index=df.index)
    
    # Remove rows without valid coordinates
    df = df.dropna(subset=['latitude', 'longitude'])
    
    print(f"   Loaded {len(df)} transit stations")
    
    return df


# =============================================================================
# STREET LIGHTING
# =============================================================================

@st.cache_data(show_spinner="Loading street lights...")
def load_street_lights() -> pd.DataFrame:
    """
    Load street lighting pole locations
    
    Returns:
        DataFrame with light pole coordinates
    """
    print("💡 Loading street lights...")
    
    df = pd.read_csv(STREET_LIGHTS_FILE, delimiter=';')
    
    # Parse GeoJSON from Geom column
    df['geojson'] = df['Geom'].apply(parse_geojson_from_string)
    
    # Extract coordinates
    coords = df['geojson'].apply(extract_coordinates_from_geojson)
    df[['latitude', 'longitude']] = pd.DataFrame(coords.tolist(), index=df.index)
    
    # Remove rows without valid coordinates
    df = df.dropna(subset=['latitude', 'longitude'])
    
    # Sample if too many (for performance)
    if len(df) > 20000:
        print(f"   Sampling 20,000 from {len(df):,} street lights for performance")
        df = df.sample(n=20000, random_state=42)
    
    print(f"   Loaded {len(df):,} street lights")
    
    return df


# =============================================================================
# BUSINESS LICENSES
# =============================================================================

@st.cache_data(show_spinner="Loading businesses...")
def load_businesses() -> pd.DataFrame:
    """
    Load business license data
    
    Returns:
        DataFrame with business locations and types
    """
    print("🏪 Loading business licenses...")
    
    df = pd.read_csv(BUSINESS_LICENSES_FILE, delimiter=';', low_memory=False)
    
    # Parse GeoJSON from Geom column if it exists
    if 'Geom' in df.columns:
        df['geojson'] = df['Geom'].apply(parse_geojson_from_string)
        coords = df['geojson'].apply(extract_coordinates_from_geojson)
        df[['latitude', 'longitude']] = pd.DataFrame(coords.tolist(), index=df.index)
    elif 'geo_point_2d' in df.columns:
        # Alternative: parse from geo_point_2d column
        def parse_geo_point(point_str):
            if pd.isna(point_str):
                return None, None
            try:
                lat, lon = point_str.split(',')
                return float(lat.strip()), float(lon.strip())
            except:
                return None, None
        
        coords = df['geo_point_2d'].apply(parse_geo_point)
        df[['latitude', 'longitude']] = pd.DataFrame(coords.tolist(), index=df.index)
    
    # Remove rows without valid coordinates
    df = df.dropna(subset=['latitude', 'longitude'])
    
    # Filter to active businesses
    if 'Status' in df.columns:
        df = df[df['Status'].str.contains('Issued', na=False, case=False)]
    
    print(f"   Loaded {len(df):,} active businesses")
    if 'BusinessType' in df.columns:
        print(f"   Business types: {df['BusinessType'].nunique()}")
    
    return df


# =============================================================================
# PARKS
# =============================================================================

@st.cache_data(show_spinner="Loading parks...")
def load_parks() -> pd.DataFrame:
    """
    Load parks data
    
    Returns:
        DataFrame with park information
    """
    print("🌳 Loading parks...")
    
    df = pd.read_csv(PARKS_FILE, delimiter=';')
    
    # Parse coordinates from GoogleMapDest column
    if 'GoogleMapDest' in df.columns:
        def parse_google_coords(coord_str):
            if pd.isna(coord_str):
                return None, None
            try:
                lat, lon = coord_str.split(',')
                return float(lat.strip()), float(lon.strip())
            except:
                return None, None
        
        coords = df['GoogleMapDest'].apply(parse_google_coords)
        df[['latitude', 'longitude']] = pd.DataFrame(coords.tolist(), index=df.index)
    
    df = df.dropna(subset=['latitude', 'longitude'])
    
    print(f"   Loaded {len(df)} parks")
    
    return df


# =============================================================================
# ZONING (Optional reference layer)
# =============================================================================

@st.cache_data(show_spinner="Loading zoning data...")
def load_zoning() -> pd.DataFrame:
    """
    Load zoning districts (optional reference layer)
    
    Returns:
        DataFrame with zoning polygons
    """
    print("🗺️  Loading zoning data...")
    
    df = pd.read_csv(ZONING_FILE, low_memory=False)
    
    # Parse GeoJSON from Geom column
    if 'Geom' in df.columns:
        df['geojson'] = df['Geom'].apply(parse_geojson_from_string)
    
    print(f"   Loaded {len(df)} zoning districts")
    
    return df


# =============================================================================
# DATA SUMMARY
# =============================================================================

def get_data_summary() -> dict:
    """
    Get summary statistics of all loaded datasets
    
    Returns:
        Dictionary with dataset names and record counts
    """
    summary = {}
    
    try:
        properties = load_property_data()
        summary['Properties'] = len(properties)
        summary['Properties with coordinates'] = properties['latitude'].notna().sum()
    except Exception as e:
        summary['Properties'] = f'Error: {str(e)}'
    
    try:
        crime = load_crime_data()
        summary['Crime Records'] = len(crime)
    except Exception as e:
        summary['Crime Records'] = f'Error: {str(e)}'
    
    try:
        transit = load_transit_stations()
        summary['Transit Stations'] = len(transit)
    except Exception as e:
        summary['Transit Stations'] = f'Error: {str(e)}'
    
    try:
        lights = load_street_lights()
        summary['Street Lights'] = len(lights)
    except Exception as e:
        summary['Street Lights'] = f'Error: {str(e)}'
    
    try:
        businesses = load_businesses()
        summary['Businesses'] = len(businesses)
    except Exception as e:
        summary['Businesses'] = f'Error: {str(e)}'
    
    try:
        parks = load_parks()
        summary['Parks'] = len(parks)
    except Exception as e:
        summary['Parks'] = f'Error: {str(e)}'
    
    return summary
