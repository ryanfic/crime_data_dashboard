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
import os
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
    Load and preprocess property tax report data with REAL coordinates
    
    This is the PRIMARY dataset for the similarity-based block analysis.
    
    Returns:
        DataFrame with columns:
            - PID, FROM_CIVIC_NUMBER, STREET_NAME, PROPERTY_POSTAL_CODE
            - CURRENT_LAND_VALUE, CURRENT_IMPROVEMENT_VALUE
            - YEAR_BUILT, ZONING_DISTRICT, ZONING_CLASSIFICATION, LEGAL_TYPE
            - latitude, longitude (REAL coordinates from geocoding)
            - property_value (total value, calculated)
            - building_age (calculated)
            - property_type (categorized)
    """
    print("📊 Loading geocoded property data...")
    
    # Use absolute path based on this file's location
    current_dir = os.path.dirname(os.path.abspath(__file__))
    geocoded_file = os.path.join(current_dir, "geocoded_properties.csv")
    script_path = os.path.join(current_dir, "geocode_properties.py")
    
    try:
        df = pd.read_csv(geocoded_file)
        print(f"   ✅ Loaded {len(df):,} geocoded properties")
    except FileNotFoundError:
        print(f"   ⚠️ Geocoded file not found at {geocoded_file}")
        print("   Running geocoding script...")
        
        # Run the geocoding script
        import subprocess
        result = subprocess.run(
            ["python3", script_path],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print("   ✅ Geocoding complete, loading data...")
            df = pd.read_csv(geocoded_file)
        else:
            print(f"   ❌ Geocoding failed: {result.stderr}")
            # Fallback to empty dataframe with correct columns
            df = pd.DataFrame(columns=[
                'PID', 'FROM_CIVIC_NUMBER', 'STREET_NAME', 'PROPERTY_POSTAL_CODE',
                'CURRENT_LAND_VALUE', 'CURRENT_IMPROVEMENT_VALUE',
                'YEAR_BUILT', 'ZONING_DISTRICT', 'ZONING_CLASSIFICATION', 'LEGAL_TYPE',
                'latitude', 'longitude', 'property_value', 'building_age', 'property_type'
            ])
            return df
    
    # Data is already preprocessed from geocoding script
    # Just validate and return
    
    print(f"   Properties with coordinates: {df['latitude'].notna().sum():,}")
    print(f"   Property value range: ${df['property_value'].min():,.0f} - ${df['property_value'].max():,.0f}")
    print(f"   Latitude range: {df['latitude'].min():.4f} - {df['latitude'].max():.4f}")
    print(f"   Longitude range: {df['longitude'].min():.4f} - {df['longitude'].max():.4f}")
    print(f"   Property types: {df['property_type'].value_counts().to_dict()}")
    
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
    
    try:
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
        
    except Exception as e:
        print(f"   ❌ Error loading transit: {e}")
        return pd.DataFrame(columns=['STATION', 'latitude', 'longitude'])


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
    
    try:
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
        
    except Exception as e:
        print(f"   ❌ Error loading street lights: {e}")
        return pd.DataFrame(columns=['latitude', 'longitude'])


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
    
    try:
        df = pd.read_csv(PARKS_FILE, delimiter=';', encoding='utf-8-sig') # Handle BOM
        
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
        else:
            print(f"   ⚠️ GoogleMapDest column not found in parks data (Cols: {list(df.columns)})")
            # Ensure columns exist anyway
            df['latitude'] = np.nan
            df['longitude'] = np.nan
        
        df = df.dropna(subset=['latitude', 'longitude'])
        
        print(f"   Loaded {len(df)} parks")
        return df
        
    except Exception as e:
        print(f"   ❌ Error loading parks: {e}")
        return pd.DataFrame(columns=['Name', 'Hectare', 'latitude', 'longitude'])


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
