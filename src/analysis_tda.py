
import pandas as pd
import numpy as np
import pydeck as pdk
from ripser import ripser
from persim import plot_diagrams
from sklearn.preprocessing import StandardScaler
from shapely import wkt
from shapely.geometry import Point, Polygon
import json
import sys

# File Paths
CRIME_FILE = '../data/crimedata_csv_Grandview-Woodland_2020.csv'
PROPERTY_FILE = '../Data /property-tax-report.csv'
ZONING_FILE = '../Data /zoning-districts-and-labels.csv'
OUTPUT_MAP = '../outputs/html/crime_property_tda_map.html'

# Constants
# GRANDVIEW_WOODLAND_CODE = '010' # Estimated - will verify if possible
# If specific code unknown, we might Analyze ALL properties 
# aggregated by Zoning District which links to the Zoning Map.

def load_data():
    print("Loading data...")
    
    # 1. Crime Data
    crime_df = pd.read_csv(CRIME_FILE)
    # Filter valid coordinates
    crime_df = crime_df[(crime_df['X'] != 0) & (crime_df['Y'] != 0)].dropna(subset=['X', 'Y'])
    
    # Convert UTM to Lat/Lon (Use the one from visualize_crime.py logic or pyproj if needed)
    # Wait, the previous script used pyproj. Let's reuse that logic.
    from pyproj import Transformer
    transformer = Transformer.from_crs("EPSG:26910", "EPSG:4326") # UTM Zone 10N to WGS84
    
    # Vectorized conversion is faster
    lat, lon = transformer.transform(crime_df['X'].values, crime_df['Y'].values)
    crime_df['lat'] = lat
    crime_df['lon'] = lon
    
    # 2. Zoning Data (Geometries)
    zoning_df = pd.read_csv(ZONING_FILE, sep=';')
    # It has 'Geom' as GeoJSON string or similar. 
    # Let's inspect column 'Geom' or 'geo_point_2d'.
    # Based on previous `head`, 'Geom' contains: "{\"coordinates\": ... \"type\": \"Polygon\"}"
    
    # 3. Property Tax Data
    # Use sep=';' as verified from file inspection
    prop_df = pd.read_csv(PROPERTY_FILE, sep=';', on_bad_lines='skip')
    
    return crime_df, zoning_df, prop_df

def process_property_tda(prop_df):
    print("Processing Property Data with TDA...")
    
    # Aggregate by ZONING_DISTRICT to characterize the "Type of Zone"
    # We want to find "Complex" zones.
    # Features: Current Land Value, Current Improvement Value, Year Built
    
    # Group by Zoning District
    zone_stats = []
    
    for zone, group in prop_df.groupby('ZONING_DISTRICT'):
        if len(group) < 5: continue # Skip small groups
        
        # Extract features
        features = group[['CURRENT_LAND_VALUE', 'CURRENT_IMPROVEMENT_VALUE', 'YEAR_BUILT']].dropna()
        if len(features) < 5: continue
        
        # Subsample if too large (TDA is expensive O(N^3))
        if len(features) > 200:
            features = features.sample(200, random_state=42)

        # Normalize
        scaler = StandardScaler()
        normalized_features = scaler.fit_transform(features)
        
        # Check for NaNs/Infs
        if not np.isfinite(normalized_features).all():
             # print(f"Skipping {zone} due to non-finite values.")
             continue

        # print(f"Processing {zone} with {len(features)} points...")

        # TDA - Compute Persistence
        # We limit maxdim=1 (loops)
        try:
            diagrams = ripser(normalized_features, maxdim=1)['dgms']
            
            # Feature Extraction from Diagrams
            # H0 (Clusters): Lifetime sum? Max lifetime?
            # H1 (Loops): Max lifetime?
            
            h0_lifetimes = diagrams[0][:, 1] - diagrams[0][:, 0]
            h0_lifetimes = h0_lifetimes[np.isfinite(h0_lifetimes)]
            
            h1_lifetimes = []
            if len(diagrams) > 1 and len(diagrams[1]) > 0:
                h1_lifetimes = diagrams[1][:, 1] - diagrams[1][:, 0]
            
            avg_h0 = np.mean(h0_lifetimes) if len(h0_lifetimes) > 0 else 0
            max_h1 = np.max(h1_lifetimes) if len(h1_lifetimes) > 0 else 0
            
            # Complexity Score could be Max H1 (Loopiness/outliers) + Avg H0 (Clustering)
            complexity_score = max_h1 + avg_h0
            
            zone_stats.append({
                'ZONING_DISTRICT': zone,
                'prop_count': len(group),
                'avg_land_value': features['CURRENT_LAND_VALUE'].mean(),
                'tda_complexity': complexity_score,
                'max_h1': max_h1
            })
            
        except Exception as e:
            print(f"Error processing zone {zone}: {e}")
            continue
            
    return pd.DataFrame(zone_stats)

def build_map(crime_df, zoning_df, zone_stats_df):
    print("Building PyDeck Map...")
    
    # Prepare Zoning Polygons for PyDeck
    # Join with Zone Stats
    
    # We need to parse the GeoJSON string in 'Geom'
    def parse_geom(json_str):
        try:
            return json.loads(json_str)
        except:
            return None

    zoning_df['geometry'] = zoning_df['Geom'].apply(parse_geom)
    zoning_df = zoning_df.dropna(subset=['geometry'])
    
    # Merge with TDA stats
    # zoning_df has 'Zoning District' (e.g. RS-1). prop_df has 'ZONING_DISTRICT'.
    merged_zoning = zoning_df.merge(zone_stats_df, left_on='Zoning District', right_on='ZONING_DISTRICT', how='left')
    
    # Fill NaN for visualization
    merged_zoning['tda_complexity'] = merged_zoning['tda_complexity'].fillna(0)
    merged_zoning['avg_land_value'] = merged_zoning['avg_land_value'].fillna(0)
    
    # Normalize complexity for height/color
    max_comp = merged_zoning['tda_complexity'].max()
    if max_comp > 0:
        merged_zoning['norm_complexity'] = merged_zoning['tda_complexity'] / max_comp
    else:
        merged_zoning['norm_complexity'] = 0
        
    # Create Layers
    
    # 1. Zoning Layer (Polygon) - Extruded by Complexity
    # We need to extract coordinates in the format PyDeck expects
    # PyDeck PolygonLayer expects: [[lng, lat], [lng, lat], ...]
    
    # Note: 'geometry' is a dict like {"type": "Polygon", "coordinates": [[[x,y],...]]}
    # PyDeck needs the list of coordinates.
    # We need to ensure we pass the right structure.
    
    def get_coords(geom):
        if geom['type'] == 'Polygon':
            return geom['coordinates'][0] # Outer ring
        elif geom['type'] == 'MultiPolygon':
            return geom['coordinates'][0][0] # First polygon first ring (simplification)
        return []

    merged_zoning['path'] = merged_zoning['geometry'].apply(get_coords)
    
    # Normalize Land Value for Color (Red = High Value, Blue = Low)
    # Visualizing TDA Complexity as Height
    
    zoning_layer = pdk.Layer(
        "PolygonLayer",
        merged_zoning,
        get_polygon="path",
        get_elevation="tda_complexity * 1000", # Scale height
        get_fill_color="[255, (1-norm_complexity)*255, (1-norm_complexity)*255, 140]", # Redder = More Complex
        get_line_color=[0, 0, 0],
        line_width_min_pixels=1,
        extruded=True,
        pickable=True,
        auto_highlight=True,
    )
    
    # Format Address: Replace 'XX' with '00'
    crime_df['clean_address'] = crime_df['HUNDRED_BLOCK'].str.replace('XX', '00', regex=False)

    crime_layer = pdk.Layer(
        "ScatterplotLayer",
        crime_df,
        get_position=['lon', 'lat', 2000], # Z=2000m to float top
        get_radius=6, # Smaller dots
        get_fill_color=[0, 255, 255, 255], # Opaque Cyan
        pickable=True,
        stroked=True,
        line_width_min_pixels=1,
    )
    
    # Initial View State
    view_state = pdk.ViewState(
        latitude=crime_df['lat'].mean(),
        longitude=crime_df['lon'].mean(),
        zoom=13,
        pitch=45,
        bearing=0
    )
    
    # Render
    r = pdk.Deck(
        layers=[zoning_layer, crime_layer],
        initial_view_state=view_state,
        tooltip={
            "html": "<b>Zone:</b> {Zoning District}<br/>"
                    "<b>Complexity:</b> {tda_complexity}<br/>"
                    "<b>Address:</b> {clean_address}<br/>"
                    "<b>Type:</b> {TYPE}"
        }
    )
    
    r.to_html(OUTPUT_MAP)
    print(f"Map saved to {OUTPUT_MAP}")

def main():
    crime, zoning, prop = load_data()
    
    # Filter Zoning Polygons to Crime Area
    # Crime Area BBOX with buffer
    min_lon, max_lon = crime['lon'].min(), crime['lon'].max()
    min_lat, max_lat = crime['lat'].min(), crime['lat'].max()
    
    buffer = 0.01 # ~1km buffer
    min_lon -= buffer
    max_lon += buffer
    min_lat -= buffer
    max_lat += buffer

    print(f"Filtering zoning to bbox: {min_lon}, {min_lat}, {max_lon}, {max_lat}")
    
    # Simple bbox filter on parsed geometry
    if 'geometry' not in zoning.columns:
         zoning['geometry'] = zoning['Geom'].apply(lambda x: json.loads(x) if isinstance(x, str) else None)
    
    zoning = zoning.dropna(subset=['geometry'])

    def in_bbox(geom):
        # fast check on first point
        try:
            if geom['type'] == 'Polygon':
                coords = geom['coordinates'][0]
            elif geom['type'] == 'MultiPolygon':
                coords = geom['coordinates'][0][0]
            else:
                return False
                
            lons = [p[0] for p in coords]
            lats = [p[1] for p in coords]
            
            # Check if ANY point is in bbox (intersects) or if centroid is inside
            # Simplest: Check if polygon min/max overlaps bbox
            p_min_lon, p_max_lon = min(lons), max(lons)
            p_min_lat, p_max_lat = min(lats), max(lats)
            
            if (p_max_lon < min_lon) or (p_min_lon > max_lon): return False
            if (p_max_lat < min_lat) or (p_min_lat > max_lat): return False
            return True
        except:
            return False

    zoning = zoning[zoning['geometry'].apply(in_bbox)]
    print(f"Filtered to {len(zoning)} zoning polygons.")

    # Run TDA
    zone_stats = process_property_tda(prop)
    print(zone_stats.head())
    
    # DEBUG: Check coordinates
    print("--- DEBUG COORDINATES ---")
    print(f"Crime Points: {len(crime)}")
    print(f"Crime Bounds: Lat {crime['lat'].min()}-{crime['lat'].max()}, Lon {crime['lon'].min()}-{crime['lon'].max()}")
    
    # Check Zoning Bounds from the filtered set
    all_zoning_coords = []
    for geom in zoning['geometry']:
        if geom['type'] == 'Polygon':
            all_zoning_coords.extend(geom['coordinates'][0])
        elif geom['type'] == 'MultiPolygon':
            all_zoning_coords.extend(geom['coordinates'][0][0])
    
    if all_zoning_coords:
        lons = [p[0] for p in all_zoning_coords]
        lats = [p[1] for p in all_zoning_coords]
        print(f"Zoning Bounds: Lat {min(lats)}-{max(lats)}, Lon {min(lons)}-{max(lons)}")
    else:
        print("No zoning coordinates found!")
    print("-------------------------")

    build_map(crime, zoning, zone_stats)

if __name__ == "__main__":
    main()
