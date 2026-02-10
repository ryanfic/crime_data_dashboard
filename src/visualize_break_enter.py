"""
Break and Enter Crime Visualization with Zoning Districts
==========================================================
This script creates an interactive map visualization of break and enter
crimes across all Vancouver neighborhoods, with colored zoning districts
overlaid on the map.

Author: Data Analysis Pipeline  
Date: 2026-02-01
"""

import pandas as pd
import folium
from folium import plugins
import json
from pyproj import Transformer

# ============================================================================
# CONFIGURATION
# ============================================================================

# Input files
INPUT_FILE = '../outputs/processed/cleaned_break_enter_data.csv'
ZONING_FILE = '../Data /zoning_d.csv'

# Output HTML map file
OUTPUT_FILE = '../outputs/html/clean_crime_map.html'

# Map center (Vancouver coordinates)
VANCOUVER_CENTER = [49.2827, -123.1207]

# Map zoom level
INITIAL_ZOOM = 13

# Color scheme for crime types
CRIME_COLORS = {
    'Commercial': '#8B0000',  # Dark red for commercial break-ins
    'Residential/Other': '#DC143C'  # Crimson for residential break-ins
}

# Color scheme for zoning categories (matching previous map)
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
    'Burrard Corridor Public Benefits & Employment District': '#FFC107',
    'Institutional': '#795548',
    'Historic Area': '#E91E63',
    'False Creek Comprehensive Development District': '#0097A7',
    'False Creek': '#00BCD4',
    'Other': '#9E9E9E',
    'Residential Apartment': '#4DB6AC',
    'Coal Harbour Waterfront District': '#0288D1',
    'First Shaughnessy District': '#F48FB1',
    'Downtown Eastside/Oppenheimer District': '#D32F2F'
}


# ============================================================================
# DATA LOADING
# ============================================================================

def load_cleaned_data(filepath):
    """
    Load the cleaned crime data and convert UTM coordinates to lat/lon.
    
    The X,Y coordinates in the dataset are in UTM Zone 10N.
    We need to convert them to WGS84 (latitude/longitude).
    
    Args:
        filepath (str): Path to the cleaned CSV file
        
    Returns:
        pd.DataFrame: Cleaned crime data with lat/lon coordinates
    """
    print(f"\n{'='*70}")
    print("LOADING CLEANED DATA")
    print(f"{'='*70}")
    
    df = pd.read_csv(filepath)
    print(f"✓ Loaded {len(df):,} cleaned crime records")
    print(f"✓ Sample UTM coordinates: X={df['X'].iloc[0]:.2f}, Y={df['Y'].iloc[0]:.2f}")
    
    # Convert UTM (Zone 10N, NAD83) to WGS84 lat/lon
    print("\n✓ Converting UTM coordinates to latitude/longitude...")
    transformer = Transformer.from_crs("EPSG:26910", "EPSG:4326", always_xy=True)
    
    # Transform all coordinates at once (X, Y -> lon, lat)
    lon, lat = transformer.transform(df['X'].values, df['Y'].values)
    df['latitude'] = lat
    df['longitude'] = lon
    
    print(f"✓ Converted coordinates - Sample: lat={df['latitude'].iloc[0]:.2f}, lon={df['longitude'].iloc[0]:.2f}")
    print(f"✓ Crime categories: {df['CRIME_CATEGORY'].value_counts().to_dict()}")
    print(f"✓ Date range: {df['YEAR'].unique()}")
    
    return df


def load_zoning_data(filepath):
    """
    Load and parse the zoning district data.
    
    Args:
        filepath (str): Path to the zoning CSV file
        
    Returns:
        pd.DataFrame: Zoning district data with parsed geometry
    """
    print(f"\n{'='*70}")
    print("LOADING ZONING DATA")
    print(f"{'='*70}")
    
    df = pd.read_csv(filepath)
    
    # Parse the geometry JSON
    df['geometry'] = df['Geom'].apply(lambda x: json.loads(x))
    
    print(f"✓ Loaded {len(df):,} zoning districts")
    print(f"✓ Unique categories: {df['Zoning Category Full'].nunique()}")
    
    return df


# ============================================================================
# MAP CREATION
# ============================================================================

def create_base_map():
    """
    Create the base folium map with Vancouver centered.
    
    Returns:
        folium.Map: Base map object
    """
    print(f"\n{'='*70}")
    print("CREATING BASE MAP")
    print(f"{'='*70}")
    
    # Create map with a clean CartoDB Positron basemap
    m = folium.Map(
        location=VANCOUVER_CENTER,
        zoom_start=INITIAL_ZOOM,
        tiles='cartodbpositron',
        prefer_canvas=True  # Better performance for many markers
    )
    
    print("✓ Base map created")
    print(f"✓ Center: {VANCOUVER_CENTER}")
    print(f"✓ Zoom level: {INITIAL_ZOOM}")
    
    return m


def add_zoning_districts(map_object, zoning_df):
    """
    Add colored zoning district polygons to the map.
    
    Args:
        map_object (folium.Map): The map to add zones to
        zoning_df (pd.DataFrame): Zoning district data
        
    Returns:
        folium.Map: Map with zoning districts added
    """
    print(f"\n{'='*70}")
    print("ADDING ZONING DISTRICTS")
    print(f"{'='*70}")
    
    # Create a feature group for zoning districts
    zoning_group = folium.FeatureGroup(name='Zoning Districts', show=True)
    
    for idx, row in zoning_df.iterrows():
        zone_category = row['Zoning Category Full']
        zone_color = ZONE_COLORS.get(zone_category, '#9E9E9E')  # Default to grey
        
        # Extract coordinates from geometry
        if row['geometry']['type'] == 'Polygon':
            coordinates = row['geometry']['coordinates']
            # Folium expects [lat, lon] but GeoJSON is [lon, lat]
            # Also handle multiple rings (outer ring + holes)
            for ring in coordinates:
                # Swap lon/lat to lat/lon
                folium_coords = [[coord[1], coord[0]] for coord in ring]
                
                # Create polygon
                folium.Polygon(
                    locations=folium_coords,
                    color=zone_color,
                    fill=True,
                    fillColor=zone_color,
                    fillOpacity=0.6,
                    weight=3,
                    popup=folium.Popup(
                        f"""<b>Category:</b> {zone_category}<br>
                        <b>District Code:</b> {row['Zoning District']}<br>
                        <b>Classification:</b> {row['Zoning Classification']}""",
                        max_width=300
                    ),
                    tooltip=row['Zoning District']
                ).add_to(zoning_group)
    
    zoning_group.add_to(map_object)
    
    print(f"✓ Added {len(zoning_df):,} zoning district polygons")
    
    return map_object


def add_crime_markers(map_object, df):
    """
    Add crime markers to the map.
    
    Each crime is represented as a circle marker, color-coded by type.
    
    Args:
        map_object (folium.Map): The map to add markers to
        df (pd.DataFrame): Crime data
        
    Returns:
        folium.Map: Map with crime markers added
    """
    print(f"\n{'='*70}")
    print("ADDING CRIME MARKERS")
    print(f"{'='*70}")
    
    # Create feature groups for each crime category
    commercial_group = folium.FeatureGroup(name='Break & Enter Commercial')
    residential_group = folium.FeatureGroup(name='Break & Enter Residential/Other')
    
    # Counters for tracking
    commercial_count = 0
    residential_count = 0
    
    # Add markers for each crime
    for idx, row in df.iterrows():
        # Determine color based on crime category
        color = CRIME_COLORS.get(row['CRIME_CATEGORY'], '#000000')
        
        # Create popup with crime details
        popup_html = f"""
        <div style="font-family: Arial; font-size: 12px; width: 200px;">
            <b>Crime Type:</b> {row['TYPE']}<br>
            <b>Neighborhood:</b> {row['NEIGHBOURHOOD']}<br>
            <b>Date:</b> {row['YEAR']}-{row['MONTH']:02d}-{row['DAY']:02d}<br>
            <b>Time:</b> {row['HOUR']:02d}:{row['MINUTE']:02d}<br>
            <b>Location:</b> {row['HUNDRED_BLOCK']}
        </div>
        """
        
        # Create circle marker using lat/lon (not X/Y!)
        marker = folium.CircleMarker(
            location=[row['latitude'], row['longitude']],
            radius=4,
            popup=folium.Popup(popup_html, max_width=250),
            color=color,
            fill=True,
            fillColor=color,
            fillOpacity=0.7,
            weight=1
        )
        
        # Add to appropriate group
        if row['CRIME_CATEGORY'] == 'Commercial':
            marker.add_to(commercial_group)
            commercial_count += 1
        else:
            marker.add_to(residential_group)
            residential_count += 1
    
    # Add groups to map
    commercial_group.add_to(map_object)
    residential_group.add_to(map_object)
    
    print(f"✓ Added {commercial_count:,} commercial break-in markers")
    print(f"✓ Added {residential_count:,} residential break-in markers")
    print(f"✓ Total markers: {commercial_count + residential_count:,}")
    
    return map_object


def add_legend(map_object):
    """
    Add a custom legend to the map showing both crime types and zoning categories.
    
    Args:
        map_object (folium.Map): The map to add the legend to
        
    Returns:
        folium.Map: Map with legend added
    """
    print(f"\n{'='*70}")
    print("ADDING LEGEND")
    print(f"{'='*70}")
    
    # Build zoning legend items dynamically
    zoning_items = ""
    for category, color in sorted(ZONE_COLORS.items()):
        # Shorten long names for better display
        display_name = category
        if len(display_name) > 35:
            display_name = display_name[:32] + "..."
        zoning_items += f'<p style="margin: 3px 0; font-size: 11px;"><span style="color: {color};">■</span> {display_name}</p>\n'
    
    # Custom HTML legend with both crimes and zones
    legend_html = f'''
    <div style="position: fixed; 
                bottom: 50px; left: 50px; width: 350px; height: auto; max-height: 90vh;
                background-color: white; border:2px solid grey; z-index:9999; 
                font-size:14px; padding: 10px; border-radius: 5px;
                box-shadow: 0 0 15px rgba(0,0,0,0.2); overflow-y: auto;">
        
        <h4 style="margin-top: 0;">Break & Enter Crimes - 2020</h4>
        <p style="margin: 5px 0; font-size: 12px; color: #666;">All Vancouver Neighborhoods</p>
        
        <div style="margin-top: 10px;">
            <p style="margin: 5px 0;"><span style="color: #8B0000; font-size: 16px;">●</span> <b>Commercial</b></p>
            <p style="margin: 5px 0;"><span style="color: #DC143C; font-size: 16px;">●</span> <b>Residential/Other</b></p>
        </div>
        
        <hr style="margin: 10px 0;">
        
        <h4 style="margin: 10px 0 5px 0;">Zoning Districts</h4>
        <div style="margin-top: 5px;">
            {zoning_items}
        </div>
        
        <hr style="margin: 10px 0;">
        
        <p style="margin: 5px 0; font-size: 11px; color: #666; font-style: italic;">
            Click markers/zones for details<br>
            (Crime locations are privacy-protected to block level)
        </p>
    </div>
    '''
    
    map_object.get_root().html.add_child(folium.Element(legend_html))
    
    print("✓ Legend added to map (crimes + zoning)")
    
    return map_object


def add_layer_control(map_object):
    """
    Add layer control to toggle crime categories.
    
    Args:
        map_object (folium.Map): The map to add layer control to
        
    Returns:
        folium.Map: Map with layer control added
    """
    print(f"\n{'='*70}")
    print("ADDING LAYER CONTROL")
    print(f"{'='*70}")
    
    folium.LayerControl().add_to(map_object)
    
    print("✓ Layer control added (toggle crime types)")
    
    return map_object


# ============================================================================
# SAVE MAP
# ============================================================================

def save_map(map_object, filepath):
    """
    Save the map to an HTML file.
    
    Args:
        map_object (folium.Map): The map to save
        filepath (str): Output file path
    """
    print(f"\n{'='*70}")
    print("SAVING MAP")
    print(f"{'='*70}")
    
    map_object.save(filepath)
    
    print(f"✓ Map saved to: {filepath}")
    print(f"✓ Open this file in a web browser to view the interactive map")


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """
    Main execution function - orchestrates the visualization pipeline.
    """
    print("\n" + "="*70)
    print(" BREAK AND ENTER CRIME VISUALIZATION WITH ZONING")
    print("="*70)
    
    # Step 1: Load cleaned crime data  
    df = load_cleaned_data(INPUT_FILE)
    
    # Step 2: Load zoning data
    zoning_df = load_zoning_data(ZONING_FILE)
    
    # Step 3: Create base map
    crime_map = create_base_map()
    
    # Step 4: Add zoning districts (bottom layer)
    crime_map = add_zoning_districts(crime_map, zoning_df)
    
    # Step 5: Add crime markers (top layer)
    crime_map = add_crime_markers(crime_map, df)
    
    # Step 6: Add legend
    crime_map = add_legend(crime_map)
    
    # Step 7: Add layer control
    crime_map = add_layer_control(crime_map)
    
    # Step 8: Save map
    save_map(crime_map, OUTPUT_FILE)
    
    # Final summary
    print(f"\n{'='*70}")
    print("VISUALIZATION COMPLETE!")
    print(f"{'='*70}")
    print(f"✓ Interactive map created with {len(df):,} crime locations")
    print(f"✓ Added {len(zoning_df):,} colored zoning districts")
    print(f"✓ Open '{OUTPUT_FILE}' in your browser to explore")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
