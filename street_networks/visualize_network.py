import pandas as pd
import folium
import ast
import os
import webbrowser

# Define paths relative to this script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
JUNCTIONS_FILE = os.path.join(DATA_DIR, 'junctions.csv')
SEGMENTS_FILE = os.path.join(DATA_DIR, 'segments.csv')
OUTPUT_FILE = os.path.join(BASE_DIR, 'vancouver_street_network.html')

def load_data():
    print("Loading data...")
    try:
        junctions = pd.read_csv(JUNCTIONS_FILE)
        segments = pd.read_csv(SEGMENTS_FILE)
    except FileNotFoundError as e:
        print(f"Error: Could not find data files. Make sure they exist in {DATA_DIR}")
        print(e)
        return None, None
    return junctions, segments

def create_map(junctions, segments):
    print("Creating map...")
    
    # Calculate map center from junctions
    center_lat = junctions['latitude'].mean()
    center_lon = junctions['longitude'].mean()
    
    # Use OpenStreetMap as default for better clarity
    m = folium.Map(location=[center_lat, center_lon], zoom_start=12, tiles='OpenStreetMap')

    # Add other tile layers for validation/preference
    folium.TileLayer('CartoDB dark_matter', name='Dark Mode').add_to(m)
    folium.TileLayer('CartoDB positron', name='Light Mode').add_to(m)

    # Create a dictionary for quick junction lookup: id -> (lat, lon)
    junction_lookup = {}
    for _, row in junctions.iterrows():
        junction_lookup[row['id']] = (row['latitude'], row['longitude'])

    # Add segments to the map
    print(f"Processing {len(segments)} segments...")
    count = 0
    
    # Create a FeatureGroup for the streets so they can be toggled if we add more layers later
    full_network = folium.FeatureGroup(name="Street Network")
    
    for _, row in segments.iterrows():
        try:
            # neighbors is a string representation of a list of junction IDs, e.g., "[2974, 3166]"
            neighbor_ids = ast.literal_eval(row['neighbors'])
            
            # We need at least 2 junctions to draw a line
            if len(neighbor_ids) >= 2:
                # Get coordinates for all neighbors
                points = []
                valid_segment = True
                for j_id in neighbor_ids:
                    if j_id in junction_lookup:
                        points.append(junction_lookup[j_id])
                    else:
                        valid_segment = False 
                        break
                
                if valid_segment:
                    # Draw lines between consecutive points
                    folium.PolyLine(points, weight=2, opacity=0.6, color='blue').add_to(full_network)
                    count += 1
                    
        except (ValueError, SyntaxError) as e:
            print(f"Error parsing neighbors for segment {row.get('id', 'unknown')}: {e}")
            continue

    full_network.add_to(m)
    
    # Add LayerControl to toggle base maps
    folium.LayerControl().add_to(m)

    print(f"Added {count} street segments to the map.")
    return m

def main():
    junctions, segments = load_data()
    if junctions is not None and segments is not None:
        network_map = create_map(junctions, segments)
        network_map.save(OUTPUT_FILE)
        print(f"Map saved to {OUTPUT_FILE}")
        # Automatically open the map
        webbrowser.open('file://' + OUTPUT_FILE)

if __name__ == "__main__":
    main()
