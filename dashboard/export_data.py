import os
import sys
import json
import logging

# Ensure dashboard directory is in path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

import pandas as pd
from utils.data_loader import (
    load_property_data, load_crime_data, load_transit_stations,
    load_street_lights, load_businesses, load_parks, load_zoning
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

def sanitize_float(val):
    if val is None:
        return None
    import math
    if math.isnan(val) or math.isinf(val):
        return None
    return val

def export_to_geojson(df, output_path, properties_to_keep, name):
    logging.info(f"Exporting {name} to {output_path}...")
    
    # Filter rows with missing coordinates (clean data)
    if 'latitude' not in df.columns or 'longitude' not in df.columns:
        logging.warning(f"No latitude/longitude in {name}. Skipping.")
        return
        
    df_clean = df.dropna(subset=['latitude', 'longitude'])
    
    features = []
    for _, row in df_clean.iterrows():
        props = {}
        for p in properties_to_keep:
            if p in row and not pd.isna(row[p]):
                # Convert specific types to easily serializable forms
                val = row[p]
                if isinstance(val, (int, float, str, bool)):
                    props[p] = sanitize_float(val) if isinstance(val, float) else val
                else:
                    props[p] = str(val)
                    
        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [sanitize_float(row['longitude']), sanitize_float(row['latitude'])]
            },
            "properties": props
        }
        features.append(feature)
        
    geojson = {
        "type": "FeatureCollection",
        "features": features
    }
    
    with open(output_path, 'w') as f:
        json.dump(geojson, f)
        
    # Calculate file size in MB
    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    logging.info(f"✅ Successfully exported {name} ({len(features)} records). Size: {size_mb:.2f} MB")

def main():
    cleaned_dir = os.path.join(current_dir, "cleaned_data")
    os.makedirs(cleaned_dir, exist_ok=True)
    
    # 1. Properties
    logging.info("Loading properties...")
    import pandas as pd
    properties_df = load_property_data()
    # Adding FROM_CIVIC_NUMBER and STREET_NAME for addresses
    export_to_geojson(
        properties_df, 
        os.path.join(cleaned_dir, "properties.json"),
        ['PID', 'property_value', 'building_age', 'property_type', 'ZONING_DISTRICT', 'FROM_CIVIC_NUMBER', 'STREET_NAME'],
        "Properties"
    )
    
    # 2. Crimes
    logging.info("Loading crimes...")
    crime_df = load_crime_data()
    # Filter out crimes that have obfuscated locations
    if 'HUNDRED_BLOCK' in crime_df.columns:
        crime_df = crime_df[~crime_df['HUNDRED_BLOCK'].str.contains('OFFSET TO PROTECT PRIVACY', case=False, na=False)]
    
    # Adding HUNDRED_BLOCK for addresses
    export_to_geojson(
        crime_df,
        os.path.join(cleaned_dir, "crimes.json"),
        ['TYPE', 'YEAR', 'CRIME_CATEGORY', 'NEIGHBOURHOOD', 'HUNDRED_BLOCK'],
        "Crimes"
    )
    
    # 3. Transit
    logging.info("Loading transit...")
    transit_df = load_transit_stations()
    export_to_geojson(
        transit_df,
        os.path.join(cleaned_dir, "transit.json"),
        ['STATION'],
        "Transit Stations"
    )
    
    # 4. Street Lights
    logging.info("Loading street lights...")
    lights_df = load_street_lights()
    export_to_geojson(
        lights_df,
        os.path.join(cleaned_dir, "street_lights.json"),
        [],
        "Street Lights"
    )
    
    # 5. Businesses
    logging.info("Loading businesses...")
    bus_df = load_businesses()
    export_to_geojson(
        bus_df,
        os.path.join(cleaned_dir, "businesses.json"),
        ['BusinessName', 'BusinessType', 'Status'],
        "Businesses"
    )
    
    # 6. Parks
    logging.info("Loading parks...")
    parks_df = load_parks()
    export_to_geojson(
        parks_df,
        os.path.join(cleaned_dir, "parks.json"),
        ['Name', 'Hectare', 'NeighborhoodName'],
        "Parks"
    )
    
    logging.info("All data exported cleanly!")

if __name__ == "__main__":
    main()
