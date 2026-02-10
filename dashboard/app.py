"""
Vancouver Crime Analysis Dashboard - Phase 1: Property Similarity & Base Layers
Using Folium for high-quality, detailed map visualization

Interactive research dashboard for analyzing crime patterns using property-based
similarity blocks instead of traditional administrative boundaries.

Research: Vancouver Crime Pattern Analysis with Property Similarity
Author: Research Team
Date: February 2026
"""

import streamlit as st
from streamlit_folium import st_folium
import folium
from folium import plugins
import pandas as pd
import numpy as np

# Import utilities
from config import (
    VANCOUVER_CENTER, DEFAULT_ZOOM, MAP_HEIGHT,
    DEFAULT_SIMILARITY_THRESHOLD, DEFAULT_MIN_CLUSTER_SIZE,
    DEFAULT_SELECTED_VARIABLES, SIMILARITY_VARIABLES,
    SIMILARITY_COLORS, PARKS_COLOR, CRIME_COLORS,
    STREET_LIGHT_COLOR, LIGHT_ILLUMINATION_RADIUS
)
from utils.data_loader import (
    load_property_data, load_crime_data, load_transit_stations,
    load_street_lights, load_businesses, load_parks,
    get_data_summary
)
from analysis.property_similarity import create_similarity_blocks, enrich_blocks_with_crime
from utils.spatial_analysis import analyze_crimes_outside_lights


# =============================================================================
# PAGE CONFIGURATION
# =============================================================================

st.set_page_config(
    page_title="Vancouver Crime Analysis Dashboard",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
    <style>
    .main > div {
        padding-top: 1rem;
    }
    h1 {
        color: #1f77b4;
        padding-bottom: 0.5rem;
        font-size: 2rem;
    }
    h2 {
        font-size: 1.3rem;
    }
    .metric-card {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 5px;
        margin: 0.5rem 0;
    }
    </style>
""", unsafe_allow_html=True)


# =============================================================================
# HEADER
# =============================================================================

st.title("🗺️ Vancouver Crime Pattern Analysis")
st.markdown("""
**Research Dashboard**: Property Similarity-Based Block Analysis | High-Resolution Map View
""")

st.divider()


# =============================================================================
# SESSION STATE INITIALIZATION (Prevents full reruns)
# =============================================================================

# Initialize session state for better performance
if 'map_initialized' not in st.session_state:
    st.session_state.map_initialized = False
    st.session_state.crime_data_cached = None
    st.session_state.transit_data_cached = None
    st.session_state.lights_data_cached = None
    st.session_state.parks_data_cached = None


# =============================================================================
# SIDEBAR CONTROLS
# =============================================================================

with st.sidebar:
    st.header("⚙️ Analysis Controls")
    
    # ===================
    # Property Similarity Settings
    # ===================
    st.subheader("🏘️ Property Similarity Blocks")
    
    st.markdown("**Select variables for similarity:**")
    selected_vars = []
    for var_key, var_label in SIMILARITY_VARIABLES.items():
        if st.checkbox(var_label, value=var_key in DEFAULT_SELECTED_VARIABLES, key=f"var_{var_key}"):
            selected_vars.append(var_key)
    
    if len(selected_vars) == 0:
        st.warning("⚠️ Select at least one variable")
        selected_vars = DEFAULT_SELECTED_VARIABLES
    
    similarity_threshold = st.slider(
        "Similarity Threshold",
        min_value=0.1,
        max_value=0.9,
        value=DEFAULT_SIMILARITY_THRESHOLD,
        step=0.1,
        format="%.0f%%",
        help="Minimum similarity (%) for grouping properties"
    )
    
    min_cluster_size = st.select_slider(
        "Min Properties per Block",
        options=[5, 10, 20, 30, 50],
        value=DEFAULT_MIN_CLUSTER_SIZE,
        help="Minimum number of properties to form a block"
    )
    
    st.divider()
    
    # ===================
    # Layer Toggles
    # ===================
    st.subheader("📍 Map Layers")
    st.markdown("*Check multiple to stack*")
    
    show_crime = st.checkbox("Crime Points", value=True)
    show_transit = st.checkbox("Transit Stations", value=True)
    show_lighting = st.checkbox("Street Lighting", value=False)
    show_parks = st.checkbox("Parks", value=False)
    
    st.divider()
    
    # ===================
    # Map Style
    # ===================
    st.subheader("🎨 Map Style")
    
    use_dark_mode = st.checkbox(
        "Dark Mode (Better for Lighting)",
        value=False,
        help="Dark map shows street lighting coverage more clearly"
    )
    
    st.divider()
    
    # ===================
    # Performance Settings
    # ===================
    st.subheader("⚡ Performance")
    
    crime_sample_size = st.select_slider(
        "Crime Points to Display",
        options=[1000, 5000, 10000, 20000, "All"],
        value=10000,
        help="Reduce for faster map loading"
    )
    
    st.divider()
    
    # ===================
    # Crime Filters
    # ===================
    if show_crime:
        st.subheader("🚨 Crime Filters")
        
        # Load crime data only once and cache in session state
        if st.session_state.crime_data_cached is None:
            st.session_state.crime_data_cached = load_crime_data()
        
        crime_data = st.session_state.crime_data_cached
        
        # Crime type selection
        crime_types = crime_data['TYPE'].unique().tolist()
        selected_crime_types = st.multiselect(
            "Crime Types",
            options=crime_types,
            default=crime_types[:3] if len(crime_types) >= 3 else crime_types
        )
        
        # Year info (no slider if single year)
        min_year = int(crime_data['YEAR'].min())
        max_year = int(crime_data['YEAR'].max())
        
        if min_year == max_year:
            st.info(f"📅 Data year: {min_year}")
            year_range = (min_year, max_year)
        else:
            year_range = st.slider(
                "Year Range",
                min_value=min_year,
                max_value=max_year,
                value=(min_year, max_year)
            )
        
        st.divider()
    
    # ===================
    # Data Summary
    # ===================
    st.subheader("📊 Data Summary")
    with st.expander("View dataset info"):
        summary = get_data_summary()
        for dataset, count in summary.items():
            st.metric(dataset, f"{count:,}" if isinstance(count, int) else count)


# =============================================================================
# MAIN CONTENT AREA
# =============================================================================

# Full width map
st.subheader("🗺️ Interactive Map - High Resolution")

# Create Folium map
map_tiles = 'CartoDB dark_matter' if use_dark_mode else 'CartoDB positron'

m = folium.Map(
    location=VANCOUVER_CENTER,
    zoom_start=12,
    tiles=map_tiles,  # Dynamic based on user choice
    prefer_canvas=True,
    max_zoom=19
)

# ===================
# Layer 0: Property Similarity Blocks
# ===================
show_property_blocks = True  # Always compute if variables selected

if len(selected_vars) > 0:
    with st.spinner("Computing property similarity blocks..."):
        properties = load_property_data()
        properties_with_coords = properties[properties['latitude'].notna() & properties['longitude'].notna()]
        
        if len(properties_with_coords) > 0:
            properties_with_blocks, block_stats = create_similarity_blocks(
                properties_with_coords,
                selected_vars,
                similarity_threshold,
                min_cluster_size
            )
            
            # Create feature group for property blocks
            property_group = folium.FeatureGroup(name=f'🏘️ Property Blocks ({len(block_stats)})')
            
            # Plot properties colored by similarity group
            for group_id in properties_with_blocks['similarity_group'].unique():
                if pd.isna(group_id) or group_id == -1:
                    continue  # Skip noise points
                
                group_data = properties_with_blocks[properties_with_blocks['similarity_group'] == group_id]
                
                # Assign color
                color_idx = int(group_id) % len(SIMILARITY_COLORS)
                color = SIMILARITY_COLORS[color_idx]
                
                # Add points for this group
                for _, prop in group_data.iterrows():
                    folium.CircleMarker(
                        location=[prop['latitude'], prop['longitude']],
                        radius=5,
                        popup=folium.Popup(
                            f"<b>Block {prop['block_id']}</b><br>"
                            f"Value: ${prop['property_value']:,.0f}<br>"
                            f"Age: {prop['building_age']:.0f} years<br>"
                            f"Type: {prop['property_type']}",
                            max_width=250
                        ),
                        color=color,
                        fillColor=color,
                        fillOpacity=0.6,
                        weight=1,
                        tooltip=f"Block {prop['block_id']}"
                    ).add_to(property_group)
            
            property_group.add_to(m)
        else:
            st.info("ℹ️ Property data being geocoded - using sample for demonstration")

# ===================
# Layer 1: Crime Points
# ===================
if show_crime and 'crime_data' in locals():
    # Apply filters
    if selected_crime_types:
        filtered_crime = crime_data[crime_data['TYPE'].isin(selected_crime_types)]
    else:
        filtered_crime = crime_data
    
    filtered_crime = filtered_crime[
        (filtered_crime['YEAR'] >= year_range[0]) &
        (filtered_crime['YEAR'] <= year_range[1])
    ]
    
    # Apply sampling for performance
    if crime_sample_size != "All" and len(filtered_crime) > crime_sample_size:
        filtered_crime = filtered_crime.sample(n=crime_sample_size, random_state=42)
        st.info(f"📊 Showing {crime_sample_size:,} of {len(crime_data):,} crimes (adjust in sidebar)")
    
    # Group by crime type for better organization
    for crime_type in filtered_crime['TYPE'].unique():
        crime_subset = filtered_crime[filtered_crime['TYPE'] == crime_type]
        
        # Get color for this crime type
        color = CRIME_COLORS.get(crime_type, '#FF0000')
        
        # Create feature group for this crime type
        crime_group = folium.FeatureGroup(name=f'🚨 {crime_type} ({len(crime_subset)})')
        
        # Add markers (use CircleMarker for performance)
        for _, crime in crime_subset.iterrows():
            folium.CircleMarker(
                location=[crime['latitude'], crime['longitude']],
                radius=4,
                popup=folium.Popup(
                    f"<b>{crime['TYPE']}</b><br>"
                    f"Date: {crime['YEAR']}-{crime['MONTH']:02d}-{crime['DAY']:02d}<br>"
                    f"Time: {crime['HOUR']:02d}:{crime['MINUTE']:02d}<br>"
                    f"Location: {crime['HUNDRED_BLOCK']}",
                    max_width=300
                ),
                color=color,
                fillColor=color,
                fillOpacity=0.7,
                weight=1
            ).add_to(crime_group)
        
        crime_group.add_to(m)

# ===================
# Layer 2: Transit Stations
# ===================
if show_transit:
    transit = load_transit_stations()
    
    transit_group = folium.FeatureGroup(name=f'🚇 Transit Stations ({len(transit)})')
    
    for _, station in transit.iterrows():
        folium.Marker(
            location=[station['latitude'], station['longitude']],
            popup=folium.Popup(f"<b>{station['STATION']}</b><br>SkyTrain Station", max_width=200),
            icon=folium.Icon(color='blue', icon='train', prefix='fa'),
            tooltip=station['STATION']
        ).add_to(transit_group)
    
    transit_group.add_to(m)

# ===================
# Layer 3: Street Lighting (Illumination Effect)
# ===================
if show_lighting:
    lights = load_street_lights()
    
    # Sample for performance (5000 lights is enough to see patterns)
    lights_sample = lights.sample(n=min(5000, len(lights)), random_state=42)
    
    lighting_group = folium.FeatureGroup(name=f'💡 Street Lighting Coverage ({len(lights_sample):,} lights)')
    
    # Add illumination zones (circles showing light coverage)
    for _, light in lights_sample.iterrows():
        # Illumination glow (METER-BASED so geographic coverage is accurate at all zoom levels)
        folium.Circle(
            location=[light['latitude'], light['longitude']],
            radius=30,  # meters (actual geographic coverage area)
            color='#FFD700',  # Gold border
            fillColor='#FFFF00',  # Yellow fill
            fillOpacity=0.15,  # Semi-transparent for overlapping effect
            weight=1,
            opacity=0.3,
            tooltip="Street Light Coverage (30m radius)"
        ).add_to(lighting_group)
        
        # Light pole marker (small bright center)
        folium.CircleMarker(
            location=[light['latitude'], light['longitude']],
            radius=2,  # small pixels for the pole itself
            color='#FFD700',
            fillColor='#FFFFFF',  # White bright center
            fillOpacity=1.0,  # Fully opaque
            weight=1,
            tooltip="Street Light"
        ).add_to(lighting_group)
    
    lighting_group.add_to(m)

# ===================
# Layer 4: Parks
# ===================
if show_parks:
    parks = load_parks()
    
    parks_group = folium.FeatureGroup(name=f'🌳 Parks ({len(parks)})')
    
    for _, park in parks.iterrows():
        folium.CircleMarker(
            location=[park['latitude'], park['longitude']],
            radius=8,
            popup=folium.Popup(
                f"<b>{park['Name'] if 'Name' in park else 'Park'}</b><br>"
                f"Area: {park['Hectare'] if 'Hectare' in park else 'N/A'} hectares",
                max_width=200
            ),
            color=PARKS_COLOR,
            fillColor=PARKS_COLOR,
            fillOpacity=0.6,
            weight=2,
            tooltip=park['Name'] if 'Name' in park else 'Park'
        ).add_to(parks_group)
    
    parks_group.add_to(m)

# Add layer control
folium.LayerControl(collapsed=False).add_to(m)

# Add fullscreen option
plugins.Fullscreen(
    position='topright',
    title='Enter fullscreen',
    title_cancel='Exit fullscreen',
    force_separate_button=True
).add_to(m)

# Add search
plugins.Geocoder(collapsed=True, position='topleft').add_to(m)

# Display the map in Streamlit
map_data = st_folium(
    m,
    width='100%',
    height=900,
    returned_objects=[]
)


# =============================================================================
# STATISTICS PANEL (Below map)
# =============================================================================

st.divider()

# ===================
# Spatial Analysis: Crime vs Lighting Coverage
# ===================
spatial_stats = None
if show_crime and show_lighting and 'filtered_crime' in locals() and 'lights' in locals():
    with st.spinner("Analyzing crime locations relative to street lighting..."):
        # Perform spatial analysis
        crimes_analyzed, spatial_stats = analyze_crimes_outside_lights(
            filtered_crime, lights, light_radius=30
        )
        
        # Display prominent analysis results
        st.subheader("🔍 Crime & Lighting Coverage Analysis")
        
        col_a, col_b, col_c = st.columns(3)
        
        with col_a:
            st.metric(
                "🌟 Crimes in Lit Areas", 
                f"{spatial_stats['crimes_inside_light']:,}",
                help="Crimes within 30m of a street light"
            )
        
        with col_b:
            st.metric(
                "🌑 Crimes in Dark Areas", 
                f"{spatial_stats['crimes_outside_light']:,}",
                delta=f"{spatial_stats['percent_outside']:.1f}% of total",
                delta_color="inverse",
                help="Crimes more than 30m from any street light"
            )
        
        with col_c:
            st.metric(
                "📏 Avg Distance to Light",
                f"{spatial_stats['avg_distance_to_light']:.0f}m",
                help="Average distance from crime location to nearest street light"
            )
        
        # Additional insights
        if spatial_stats['percent_outside'] > 50:
            st.warning(f"⚠️ **{spatial_stats['percent_outside']:.1f}%** of selected crimes occur outside street light coverage areas. This suggests a potential correlation between inadequate lighting and crime occurrence.")
        elif spatial_stats['percent_outside'] < 30:
            st.info(f"ℹ️ Only **{spatial_stats['percent_outside']:.1f}%** of selected crimes occur in poorly lit areas. Most crimes happen in well-lit zones.")
        else:
            st.info(f"📊 **{spatial_stats['percent_outside']:.1f}%** of selected crimes occur outside light coverage. Consider analyzing specific crime types for more detailed insights.")
        
        st.divider()

# ===================
# General Statistics
# ===================
col1, col2, col3, col4 = st.columns(4)

with col1:
    if show_crime and 'filtered_crime' in locals():
        st.metric("🚨 Crime Records", f"{len(filtered_crime):,}")

with col2:
    if show_transit and 'transit' in locals():
        st.metric("🚇 Transit Stations", len(transit))

with col3:
    if show_lighting and 'lights' in locals():
        st.metric("💡 Street Lights", f"{len(lights):,}")

with col4:
    if show_parks and 'parks' in locals():
        st.metric("🌳 Parks", len(parks))


# =============================================================================
# FOOTER
# =============================================================================

st.divider()
st.markdown("""
<div style='text-align: center; color: #666; padding: 0.5rem;'>
<small>Vancouver Crime Pattern Analysis Dashboard | Research Prototype | High-Resolution Folium Map<br>
Data sources: Vancouver Open Data Portal, VPD GeoDASH | February 2026</small>
</div>
""", unsafe_allow_html=True)
