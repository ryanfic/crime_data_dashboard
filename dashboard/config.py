"""
Configuration file for the Vancouver Crime Analysis Dashboard
Contains all constants, color schemes, and data paths

Research: Vancouver Crime Pattern Analysis with Property Similarity
Author: Research Team
Date: February 2026
"""

import os

# =============================================================================
# FILE PATHS
# =============================================================================

# Base directory (relative to dashboard/ folder)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "Data ")  # Note: space in folder name

# Data files
PROPERTY_TAX_FILE = os.path.join(DATA_DIR, "property-tax-report.csv")
CRIME_FILE = os.path.join(DATA_DIR, "crimedata_csv_AllNeighbourhoods_2020", "crimedata_csv_AllNeighbourhoods_2020.csv")  # ALL neighborhoods
TRANSIT_STATIONS_FILE = os.path.join(DATA_DIR, "rapid-transit-stations.csv")
STREET_LIGHTS_FILE = os.path.join(DATA_DIR, "street-lighting-poles.csv")
BUSINESS_LICENSES_FILE = os.path.join(DATA_DIR, "business-licences.csv")
ZONING_FILE = os.path.join(DATA_DIR, "zoning_d.csv")
PARKS_FILE = os.path.join(DATA_DIR, "parks.csv")
BUILDING_FOOTPRINTS_FILE = os.path.join(DATA_DIR, "building-footprints-2015.csv")
TRAFFIC_SIGNALS_FILE = os.path.join(DATA_DIR, "traffic-signals.csv")

print(f"DEBUG: BASE_DIR = {BASE_DIR}")
print(f"DEBUG: DATA_DIR = {DATA_DIR}")
print(f"DEBUG: CRIME_FILE = {CRIME_FILE}")

# =============================================================================
# MAP SETTINGS
# =============================================================================

# Vancouver center coordinates [latitude, longitude]
VANCOUVER_CENTER = [49.2827, -123.1207]

# Default zoom level (11 = city-wide, 13 = neighborhood, 15 = street-level)
DEFAULT_ZOOM = 11

# Coordinate Reference Systems
CRS_WGS84 = "EPSG:4326"  # Standard lat/lon
CRS_UTM_10N = "EPSG:26910"  # UTM Zone 10N (Vancouver)

# =============================================================================
# COLOR SCHEMES
# =============================================================================

# Crime type colors (distinct, colorblind-friendly)
CRIME_COLORS = {
    'Break and Enter Commercial': '#8B0000',  # Dark red
    'Break and Enter Residential/Other': '#DC143C',  # Crimson
    'Theft from Vehicle': '#FF6347',  # Tomato
    'Theft of Vehicle': '#FF4500',  # Orange red
    'Theft of Bicycle': '#FFA500',  # Orange
    'Other Theft': '#FFD700',  # Gold
    'Mischief': '#9370DB',  # Medium purple
    'Offence Against a Person': '#4B0082',  # Indigo
    'Homicide': '#000000',  # Black
    'Vehicle Collision or Pedestrian Struck (with Injury)': '#696969',  # Dim gray
    'Vehicle Collision or Pedestrian Struck (with Fatality)': '#2F4F4F',  # Dark slate gray
}

# Property value color scale (for choropleth)
PROPERTY_VALUE_COLORS = [
    [0, '#0d0887'],      # Very low - dark blue
    [0.2, '#46039f'],    # Low - purple
    [0.4, '#7201a8'],    # Medium-low - magenta
    [0.6, '#9c179e'],    # Medium - pink
    [0.8, '#bd3786'],    # Medium-high - red
    [1, '#ed7953']       # High - orange
]

# Similarity block colors (distinct groups)
SIMILARITY_COLORS = [
    '#e6194b', '#3cb44b', '#ffe119', '#4363d8', '#f58231',
    '#911eb4', '#46f0f0', '#f032e6', '#bcf60c', '#fabebe',
    '#008080', '#e6beff', '#9a6324', '#fffac8', '#800000',
    '#aaffc3', '#808000', '#ffd8b1', '#000075', '#808080'
]

# Zoning category colors (from original plan)
ZONE_COLORS = {
    'Comprehensive Development': '#2196F3',
    'Commercial': '#FF9800',
    'Multiple Dwelling Residential': '#66BB6A',
    'One-Family Dwelling': '#4CAF50',
    'Two-Family Dwelling': '#81C784',
    'Industrial (Core / Protected)': '#9C27B0',
    'Industrial (Mixed Employment)': '#7E57C2',
    'Residential Rental': '#C5E1A5',
    'Two-Family Dwelling (Legacy)': '#A5D6A7',
    'Downtown District': '#FF5722',
    'Institutional': '#795548',
    'Historic Area': '#E91E63',
    'Other': '#9E9E9E',
    'Residential Apartment': '#4DB6AC',
}

# Parks color
PARKS_COLOR = '#2ecc71'  # Green

# Street light visualization
STREET_LIGHT_COLOR = '#FFD700'  # Gold
LIGHT_ILLUMINATION_RADIUS = 30  # meters (increased for visibility)
TRANSIT_COLOR = '#0066CC'  # Blue

# =============================================================================
# PROPERTY SIMILARITY SETTINGS
# =============================================================================

# Available variables for similarity analysis
SIMILARITY_VARIABLES = {
    'property_value': 'Property Value (Land + Improvements)',
    'building_age': 'Building Age',
    'property_type': 'Property Type',
    'tax_levy': 'Tax Levy',
    'zoning': 'Zoning Category',
    'lot_size': 'Lot Size (if available)'
}

# Default similarity settings
DEFAULT_SIMILARITY_THRESHOLD = 0.7  # 70% similarity
DEFAULT_MIN_CLUSTER_SIZE = 10  # Minimum 10 properties per block
DEFAULT_SELECTED_VARIABLES = ['property_value', 'building_age', 'property_type']

# =============================================================================
# VISUALIZATION SETTINGS
# =============================================================================

# Layer opacity defaults
DEFAULT_OPACITY = 0.6
HIGHLIGHT_OPACITY = 0.9

# Point sizes
CRIME_POINT_SIZE = 8
TRANSIT_POINT_SIZE = 15
LIGHT_POINT_SIZE = 3

# Buffer radii (meters)
TRANSIT_BUFFER_RADII = [100, 200, 500, 1000, 2000]
LIGHT_ILLUMINATION_RADIUS = 25  # meters

# Map height in pixels
MAP_HEIGHT = 900  # Increased for better visibility

# =============================================================================
# DATA QUALITY THRESHOLDS
# =============================================================================

# Minimum valid coordinate values for Vancouver
MIN_LATITUDE = 49.0
MAX_LATITUDE = 49.5
MIN_LONGITUDE = -123.3
MAX_LONGITUDE = -122.9

# Maximum reasonable property value (to filter errors)
MAX_PROPERTY_VALUE = 100_000_000  # $100 million

# =============================================================================
# CENSUS/DEMOGRAPHIC
# =============================================================================

# Vancouver neighborhoods (22 local planning areas)
NEIGHBORHOODS = [
    'Arbutus-Ridge', 'Downtown', 'Dunbar-Southlands', 'Fairview',
    'Grandview-Woodland', 'Hastings-Sunrise', 'Kensington-Cedar Cottage',
    'Kerrisdale', 'Killarney', 'Kitsilano', 'Marpole', 'Mount Pleasant',
    'Oakridge', 'Renfrew-Collingwood', 'Riley Park', 'Shaughnessy',
    'South Cambie', 'Strathcona', 'Sunset', 'Victoria-Fraserview',
    'West End', 'West Point Grey'
]
