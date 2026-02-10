"""
Geographic utility functions for the Vancouver Crime Analysis Dashboard

Handles coordinate transformations, spatial operations, and GeoJSON parsing

Research: Vancouver Crime Pattern Analysis with Property Similarity
Author: Research Team
Date: February 2026
"""

import json
import re
from typing import Tuple, List, Dict, Optional
import numpy as np
from shapely.geometry import Point, Polygon, MultiPolygon, shape
from shapely.ops import unary_union
import geopandas as gpd
from pyproj import Transformer

from config import CRS_WGS84, CRS_UTM_10N, MIN_LATITUDE, MAX_LATITUDE, MIN_LONGITUDE, MAX_LONGITUDE


# =============================================================================
# COORDINATE TRANSFORMATIONS
# =============================================================================

# Create transformer for UTM to WGS84 conversion (reusable)
_utm_to_wgs84 = Transformer.from_crs(CRS_UTM_10N, CRS_WGS84, always_xy=True)
_wgs84_to_utm = Transformer.from_crs(CRS_WGS84, CRS_UTM_10N, always_xy=True)


def utm_to_latlon(x: float, y: float) -> Tuple[float, float]:
    """
    Convert UTM Zone 10N coordinates to WGS84 latitude/longitude
    
    Args:
        x: UTM easting (meters)
        y: UTM northing (meters)
        
    Returns:
        Tuple of (latitude, longitude)
    """
    lon, lat = _utm_to_wgs84.transform(x, y)
    return lat, lon


def latlon_to_utm(lat: float, lon: float) -> Tuple[float, float]:
    """
    Convert WGS84 latitude/longitude to UTM Zone 10N coordinates
    
    Args:
        lat: Latitude
        lon: Longitude
        
    Returns:
        Tuple of (x, y) in UTM coordinates
    """
    x, y = _wgs84_to_utm.transform(lon, lat)
    return x, y


def is_valid_vancouver_coordinate(lat: float, lon: float) -> bool:
    """
    Check if coordinates are within Vancouver bounds
    
    Args:
        lat: Latitude
        lon: Longitude
        
    Returns:
        True if within Vancouver bounds, False otherwise
    """
    return (MIN_LATITUDE <= lat <= MAX_LATITUDE and 
            MIN_LONGITUDE <= lon <= MAX_LONGITUDE)


# =============================================================================
# GEOJSON PARSING
# =============================================================================

def parse_geojson_from_string(geojson_str: str) -> Optional[dict]:
    """
    Parse GeoJSON from a string column in CSV files
    
    Many Vancouver Open Data CSV files contain GeoJSON as stringified JSON
    in a column named 'Geom' or similar.
    
    Args:
        geojson_str: String representation of GeoJSON
        
    Returns:
        Parsed GeoJSON dict or None if parsing fails
    """
    if not geojson_str or pd.isna(geojson_str):
        return None
        
    try:
        # Handle both single and double quotes
        geojson_str = geojson_str.replace("'", '"')
        return json.loads(geojson_str)
    except (json.JSONDecodeError, AttributeError) as e:
        return None


def geojson_to_shapely(geojson: dict) -> Optional[object]:
    """
    Convert GeoJSON dict to Shapely geometry
    
    Args:
        geojson: GeoJSON dictionary
        
    Returns:
        Shapely geometry object or None
    """
    try:
        return shape(geojson)
    except Exception:
        return None


def extract_coordinates_from_geojson(geojson: dict) -> Optional[Tuple[float, float]]:
    """
    Extract lat/lon from GeoJSON Point
    
    Args:
        geojson: GeoJSON dictionary with type='Point'
        
    Returns:
        Tuple of (latitude, longitude) or None
    """
    if not geojson or geojson.get('type') != 'Point':
        return None
        
    coords = geojson.get('coordinates')
    if coords and len(coords) >= 2:
        lon, lat = coords[0], coords[1]
        return lat, lon
    return None


# =============================================================================
# ADDRESS GEOCODING (For exact hundred-block locations)
# =============================================================================

def geocode_hundred_block(hundred_block: str, neighborhood: str = None) -> Optional[Tuple[float, float]]:
    """
    Convert hundred block address to exact coordinates
    
    For privacy, crime data uses "15XX Main St" format. We convert this to
    "1500 Main St" and geocode to get precise location.
    
    Args:
        hundred_block: Address like "15XX MAIN ST" or "1500-BLOCK MAIN ST"
        neighborhood: Optional neighborhood for context
        
    Returns:
        Tuple of (latitude, longitude) or None
        
    Note:
        This is a simplified version. For production, would use:
        - Google Maps Geocoding API
        - OpenStreetMap Nominatim
        - BC Address Geocoder
        
        For now, we'll use a pattern-based approach with known Vancouver streets.
    """
    if not hundred_block or pd.isna(hundred_block):
        return None
    
    # Clean the address
    address = hundred_block.upper().strip()
    
    # Extract block number - replace XX with 00
    # Pattern: "15XX MAIN ST" -> "1500 MAIN ST"
    address = re.sub(r'(\d+)XX\b', r'\g<1>00', address)
    
    # Also handle "1500-BLOCK MAIN ST" -> "1500 MAIN ST"
    address = re.sub(r'(\d+)-BLOCK\s+', r'\1 ', address)
    
    # For this research prototype, we'll return None and let the calling
    # function handle it. In production, would call geocoding service here.
    # The crime data should already have X,Y coordinates we can use instead.
    
    return None


# =============================================================================
# SPATIAL OPERATIONS
# =============================================================================

def create_buffer(lat: float, lon: float, radius_m: float) -> Polygon:
    """
    Create a circular buffer around a point
    
    Args:
        lat: Latitude of center point
        lon: Longitude of center point
        radius_m: Radius in meters
        
    Returns:
        Polygon representing the buffered area
        
    Note:
        For accurate buffers, we convert to UTM, buffer, then back to WGS84
    """
    # Convert to UTM for accurate distance-based buffer
    x, y = latlon_to_utm(lat, lon)
    
    # Create point and buffer in UTM
    point_utm = Point(x, y)
    buffer_utm = point_utm.buffer(radius_m)
    
    # Convert buffer polygon back to WGS84
    # Sample points around the buffer perimeter
    coords_utm = list(buffer_utm.exterior.coords)
    coords_wgs84 = []
    
    for x_utm, y_utm in coords_utm:
        lon_wgs, lat_wgs = _utm_to_wgs84.transform(x_utm, y_utm)
        coords_wgs84.append((lon_wgs, lat_wgs))
    
    return Polygon(coords_wgs84)


def point_in_polygon(lat: float, lon: float, polygon: Polygon) -> bool:
    """
    Check if a point is inside a polygon
    
    Args:
        lat: Point latitude
        lon: Point longitude
        polygon: Shapely Polygon
        
    Returns:
        True if point is inside polygon
    """
    point = Point(lon, lat)  # Note: Shapely uses (x, y) = (lon, lat)
    return polygon.contains(point)


def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate distance between two points in meters
    
    Args:
        lat1, lon1: First point coordinates
        lat2, lon2: Second point coordinates
        
    Returns:
        Distance in meters
    """
    # Convert both points to UTM for accurate distance
    x1, y1 = latlon_to_utm(lat1, lon1)
    x2, y2 = latlon_to_utm(lat2, lon2)
    
    # Euclidean distance in meters
    return np.sqrt((x2 - x1)**2 + (y2 - y1)**2)


def points_within_distance(points_df, center_lat: float, center_lon: float, 
                           radius_m: float, lat_col: str = 'latitude', 
                           lon_col: str = 'longitude'):
    """
    Filter points within a certain distance of a center point
    
    Args:
        points_df: DataFrame with point coordinates
        center_lat: Center latitude
        center_lon: Center longitude
        radius_m: Radius in meters
        lat_col: Name of latitude column
        lon_col: Name of longitude column
        
    Returns:
        Filtered DataFrame with only points within radius
    """
    import pandas as pd
    
    # Calculate distance for each point
    distances = points_df.apply(
        lambda row: calculate_distance(
            center_lat, center_lon,
            row[lat_col], row[lon_col]
        ),
        axis=1
    )
    
    # Filter points within radius
    mask = distances <= radius_m
    result = points_df[mask].copy()
    result['distance_m'] = distances[mask]
    
    return result


def create_convex_hull(points: List[Tuple[float, float]]) -> Optional[Polygon]:
    """
    Create a convex hull polygon around a set of points
    
    Used for creating similarity blocks from clustered properties
    
    Args:
        points: List of (latitude, longitude) tuples
        
    Returns:
        Shapely Polygon or None if insufficient points
    """
    if len(points) < 3:
        return None
        
    # Convert to Shapely Points (note: Shapely uses lon, lat order)
    shapely_points = [Point(lon, lat) for lat, lon in points]
    
    # Create GeoSeries and get convex hull
    from geopandas import GeoSeries
    gs = GeoSeries(shapely_points)
    hull = gs.unary_union.convex_hull
    
    return hull if isinstance(hull, Polygon) else None


# =============================================================================
# GEOSPATIAL DATAFRAME UTILITIES
# =============================================================================

def create_geodataframe(df, lat_col: str = 'latitude', lon_col: str = 'longitude',
                       crs: str = CRS_WGS84):
    """
    Convert a regular DataFrame to a GeoDataFrame
    
    Args:
        df: Pandas DataFrame with coordinates
        lat_col: Name of latitude column
        lon_col: Name of longitude column
        crs: Coordinate reference system (default: WGS84)
        
    Returns:
        GeoDataFrame with Point geometry
    """
    import pandas as pd
    
    # Filter out rows with missing coordinates
    valid_df = df.dropna(subset=[lat_col, lon_col])
    
    # Create geometry column
    geometry = [Point(row[lon_col], row[lat_col]) 
                for _, row in valid_df.iterrows()]
    
    # Create GeoDataFrame
    gdf = gpd.GeoDataFrame(valid_df, geometry=geometry, crs=crs)
    
    return gdf


# Import pandas for type hints
import pandas as pd
