import pandas as pd
import ast
import json
import os

def export_street_network():
    print("Loading street network data...")
    base_dir = "/Users/tanyaaggarwal/Desktop/A_research"
    junctions_path = os.path.join(base_dir, "street_networks", "data", "junctions.csv")
    segments_path = os.path.join(base_dir, "street_networks", "data", "segments.csv")
    output_path = os.path.join(base_dir, "dashboard", "web_dashboard", "public", "data", "street_network.geojson")
    
    # Load data
    junctions = pd.read_csv(junctions_path)
    segments = pd.read_csv(segments_path)
    
    # Create lookup map
    lookup = {}
    for _, row in junctions.iterrows():
        lookup[row['id']] = (row['longitude'], row['latitude']) # GeoJSON needs lon, lat
        
    features = []
    
    print(f"Processing {len(segments)} segments...")
    for _, row in segments.iterrows():
        try:
            neighbor_ids = ast.literal_eval(row['neighbors'])
            
            if len(neighbor_ids) >= 2:
                coords = []
                valid = True
                for j_id in neighbor_ids:
                    if j_id in lookup:
                        coords.append(lookup[j_id])
                    else:
                        valid = False
                        break
                
                if valid:
                    features.append({
                        "type": "Feature",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": coords
                        },
                        "properties": {
                            "id": row.get('id', 'unknown'),
                            "name": row.get('name', 'Unknown Street')
                        }
                    })
        except Exception as e:
            continue
            
    geojson = {
        "type": "FeatureCollection",
        "features": features
    }
    
    with open(output_path, 'w') as f:
        json.dump(geojson, f)
        
    print(f"Successfully exported {len(features)} street segments to {output_path}")

if __name__ == '__main__':
    export_street_network()
