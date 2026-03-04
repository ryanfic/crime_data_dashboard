import os
import json
import pandas as pd
import networkx as nx
from shapely.geometry import Polygon, Point, LineString
from shapely.ops import polygonize
import math

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'Data')
PUBLIC_DATA_DIR = os.path.join(BASE_DIR, 'web_dashboard', 'public', 'data')

def generate_blocks():
    print("Loading street network data...")
    segments_path = os.path.join(os.path.dirname(BASE_DIR), 'street_networks', 'data', 'segments.csv')
    junctions_path = os.path.join(os.path.dirname(BASE_DIR), 'street_networks', 'data', 'junctions.csv')
    
    if not os.path.exists(segments_path) or not os.path.exists(junctions_path):
        print(f"Error: {segments_path} or {junctions_path} not found.")
        return

    segments_df = pd.read_csv(segments_path)
    junctions_df = pd.read_csv(junctions_path)
    
    # Create coordinate lookup
    junction_coords = {}
    for _, row in junctions_df.iterrows():
        jid = row['id']
        junction_coords[jid] = [row['longitude'], row['latitude']]
            
    # Build lines for polygonize
    print("Building street segment lines...")
    lines = []
    seen_edges = set()
    
    for _, row in junctions_df.iterrows():
        n1 = row['id']
        try:
            neighbors_list = eval(row['neighbors'])
            for neighbor_info in neighbors_list:
                if isinstance(neighbor_info, (list, tuple)):
                    n2 = neighbor_info[0]
                else:
                    n2 = neighbor_info
                    
                if n2 in junction_coords:
                    # avoid back and forth line duplicates
                    edge = tuple(sorted([n1, n2]))
                    if edge not in seen_edges:
                        seen_edges.add(edge)
                        p1 = junction_coords[n1]
                        p2 = junction_coords[n2]
                        lines.append(LineString([p1, p2]))
        except Exception as e:
            pass
            
    print(f"Created {len(lines)} street segment lines.")
    
    # Extract blocks
    print("Detecting spatial blocks using polygonize...")
    polygons = list(polygonize(lines))
    print(f"Polygonize found {len(polygons)} raw polygons.")
    
    block_id = 0
    block_polygons = []
    
    for poly in polygons:
        try:
            if not poly.is_valid:
                poly = poly.buffer(0) # Attempt to fix self-intersections
                
            if poly.is_valid and poly.area > 0:
                # Filter out absurdly large polygons (like the one bounding the whole city)
                # area is in degrees, a typical block is very small (< 0.001)
                if poly.area < 0.001: 
                    block_polygons.append({
                        'id': block_id,
                        'polygon': poly,
                        'property_values': [],
                        'property_ages': [],
                        'crime_count': 0
                    })
                    block_id += 1
        except Exception as e:
            pass
            
    print(f"Created {len(block_polygons)} valid sized block polygons.")
    
    # Load properties and crimes to spatial join
    print("Loading properties and crimes...")
    properties_path = os.path.join(PUBLIC_DATA_DIR, 'properties.json')
    crimes_path = os.path.join(PUBLIC_DATA_DIR, 'crimes.json')
    
    with open(properties_path, 'r') as f:
        properties_data = json.load(f)
        
    with open(crimes_path, 'r') as f:
        crimes_data = json.load(f)
        
    # Spatial join (Naive O(N*M) - optimizing by bounding box)
    print("Aggregating properties by block...")
    # Pre-compute bounding boxes to speed up intersection checks
    for block in block_polygons:
        block['bounds'] = block['polygon'].bounds
        
    def point_in_block(pt, block):
        minx, miny, maxx, maxy = block['bounds']
        if not (minx <= pt.x <= maxx and miny <= pt.y <= maxy):
            return False
        return block['polygon'].contains(pt)

    for feature in properties_data['features']:
        coords = feature['geometry']['coordinates']
        pt = Point(coords[0], coords[1])
        props = feature['properties']
        
        val = props.get('property_value')
        age = props.get('building_age')
        
        # Find which block it belongs to
        assigned = False
        for block in block_polygons:
            if point_in_block(pt, block):
                if val: block['property_values'].append(val)
                if age: block['property_ages'].append(age)
                # We can also tag the feature with the block id
                props['block_id'] = block['id']
                assigned = True
                break

    print("Aggregating crimes by block...")
    for feature in crimes_data['features']:
        coords = feature['geometry']['coordinates']
        pt = Point(coords[0], coords[1])
        for block in block_polygons:
            if point_in_block(pt, block):
                block['crime_count'] += 1
                break
                
    # Compute Averages and Adjacency
    print("Calculating statistics and adjacencies...")
    
    # Adjacency check using Shapely touches/intersects
    for i, b1 in enumerate(block_polygons):
        b1['neighbors'] = []
        for j, b2 in enumerate(block_polygons):
            if i != j:
                # blocks are adjacent if their boundaries intersect
                if b1['polygon'].intersects(b2['polygon']):
                    b1['neighbors'].append(b2['id'])
                    
    # Build final GeoJSON features
    out_features = []
    
    for block in block_polygons:
        avg_val = sum(block['property_values']) / len(block['property_values']) if block['property_values'] else None
        avg_age = sum(block['property_ages']) / len(block['property_ages']) if block['property_ages'] else None
        
        # Only keep blocks with actual data
        if avg_val is None and avg_age is None and block['crime_count'] == 0:
            continue
            
        # Calculate standard deviation for property values and ages in the block
        std_val = 0
        std_age = 0
        
        if block['property_values'] and len(block['property_values']) > 1:
            variance_val = sum([(v - avg_val)**2 for v in block['property_values']]) / len(block['property_values'])
            std_val = math.sqrt(variance_val)
            
        if block['property_ages'] and len(block['property_ages']) > 1:
            variance_age = sum([(a - avg_age)**2 for a in block['property_ages']]) / len(block['property_ages'])
            std_age = math.sqrt(variance_age)
            
        block['avg_val'] = avg_val
        block['std_val'] = std_val
        block['avg_age'] = avg_age
        block['std_age'] = std_age
            
        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [list(block['polygon'].exterior.coords)]
            },
            "properties": {
                "block_id": block['id'],
                "avg_value": avg_val,
                "avg_age": avg_age,
                "property_count": len(block['property_values']) if block['property_values'] else 0,
                "crime_count": block['crime_count'],
                "neighbors": block['neighbors']
            }
        }
        out_features.append(feature)
        
    out_geojson = {
        "type": "FeatureCollection",
        "features": out_features
    }
    
    blocks_out_path = os.path.join(PUBLIC_DATA_DIR, 'blocks.json')
    with open(blocks_out_path, 'w') as f:
        json.dump(out_geojson, f)
        
    # Write updated properties with outlier flags
    print("Calculating property outliers and updating properties.json...")
    
    # Create lookup for block stats
    block_stats = {b['id']: {'avg_val': b.get('avg_val'), 'std_val': b.get('std_val'), 
                             'avg_age': b.get('avg_age'), 'std_age': b.get('std_age')} 
                   for b in block_polygons if 'avg_val' in b or 'avg_age' in b}
    
    outlier_count_val = 0
    outlier_count_age = 0
    
    for feature in properties_data['features']:
        props = feature['properties']
        block_id = props.get('block_id')
        
        if block_id is not None and block_id in block_stats:
            stats = block_stats[block_id]
            val = props.get('property_value')
            age = props.get('building_age')
            
            # Always pass the block average to the property for the tooltip
            if stats['avg_val'] is not None:
                props['block_avg_val'] = round(stats['avg_val'], 2)
            if stats['avg_age'] is not None:
                props['block_avg_age'] = round(stats['avg_age'], 2)
            
            # Value outlier (Z-score > 1.5 or < -1.5)
            if val is not None and stats['avg_val'] is not None and stats['std_val']:
                z_score_val = (val - stats['avg_val']) / stats['std_val']
                if abs(z_score_val) > 1.5:
                    props['is_value_outlier'] = True
                    props['value_z_score'] = round(z_score_val, 2)
                    outlier_count_val += 1
                    
            # Age outlier
            if age is not None and stats['avg_age'] is not None and stats['std_age']:
                z_score_age = (age - stats['avg_age']) / stats['std_age']
                if abs(z_score_age) > 1.5:
                    props['is_age_outlier'] = True
                    props['age_z_score'] = round(z_score_age, 2)
                    outlier_count_age += 1
                    
    print(f"Flagged {outlier_count_val} value outliers and {outlier_count_age} age outliers.")
    
    with open(properties_path, 'w') as f:
        json.dump(properties_data, f)
        
    print("Done!")

if __name__ == "__main__":
    generate_blocks()
