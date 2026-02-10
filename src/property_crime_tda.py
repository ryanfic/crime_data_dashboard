"""
Property Crime Analysis with Topological Data Analysis
Analyzes how zoning and property characteristics affect property crime rates
"""

import pandas as pd
import numpy as np
import pydeck as pdk
from ripser import ripser
from persim import plot_diagrams
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import DBSCAN
from shapely.geometry import Point, Polygon, shape
import matplotlib.pyplot as plt
import seaborn as sns
from pyproj import Transformer
import json
import warnings
warnings.filterwarnings('ignore')

# File Paths
CRIME_FILE = '../data/crimedata_csv_Grandview-Woodland_2020.csv'
PROPERTY_FILE = '../Data /property-tax-report.csv'
ZONING_FILE = '../Data /zoning-districts-and-labels.csv'
OUTPUT_MAP = '../outputs/html/crime_property_analysis.html'
OUTPUT_REPORT = 'analysis_report.txt'

# Property Crime Types
PROPERTY_CRIMES = [
    'Theft from Vehicle',
    'Other Theft',
    'Break and Enter Commercial',
    'Break and Enter Residential/Other',
    'Theft of Bicycle',
    'Theft of Vehicle'
]

def load_and_clean_data():
    """Load and clean all datasets"""
    print("=" * 60)
    print("DATA LOADING & CLEANING")
    print("=" * 60)
    
    # 1. Crime Data
    print("\n1. Loading crime data...")
    crime_df = pd.read_csv(CRIME_FILE)
    print(f"   Total records: {len(crime_df)}")
    
    # Filter for property crimes only
    crime_df = crime_df[crime_df['TYPE'].isin(PROPERTY_CRIMES)]
    print(f"   Property crimes: {len(crime_df)}")
    
    # Remove privacy-protected records
    crime_df = crime_df[(crime_df['X'] != 0) & (crime_df['Y'] != 0)].dropna(subset=['X', 'Y'])
    print(f"   After removing protected locations: {len(crime_df)}")
    
    # Convert coordinates
    transformer = Transformer.from_crs("EPSG:26910", "EPSG:4326")
    lat, lon = transformer.transform(crime_df['X'].values, crime_df['Y'].values)
    crime_df['lat'] = lat
    crime_df['lon'] = lon
    
    # Extract temporal features
    crime_df['month'] = crime_df['MONTH']
    crime_df['hour'] = crime_df['HOUR']
    crime_df['day_of_week'] = pd.to_datetime(
        crime_df[['YEAR', 'MONTH', 'DAY']].rename(columns={'YEAR':'year', 'MONTH':'month', 'DAY':'day'})
    ).dt.dayofweek
    
    # Clean address
    crime_df['clean_address'] = crime_df['HUNDRED_BLOCK'].str.replace('XX', '00', regex=False)
    
    print(f"   Crime type breakdown:")
    for crime_type in PROPERTY_CRIMES:
        count = len(crime_df[crime_df['TYPE'] == crime_type])
        print(f"     - {crime_type}: {count}")
    
    # 2. Zoning Data
    print("\n2. Loading zoning data...")
    zoning_df = pd.read_csv(ZONING_FILE, sep=';')
    print(f"   Total zones: {len(zoning_df)}")
    
    # Parse geometries
    def parse_geom(json_str):
        try:
            return json.loads(json_str)
        except:
            return None
    
    zoning_df['geometry'] = zoning_df['Geom'].apply(parse_geom)
    zoning_df = zoning_df.dropna(subset=['geometry'])
    
    # Filter to crime area
    min_lon, max_lon = crime_df['lon'].min() - 0.01, crime_df['lon'].max() + 0.01
    min_lat, max_lat = crime_df['lat'].min() - 0.01, crime_df['lat'].max() + 0.01
    
    def in_bbox(geom):
        try:
            if geom['type'] == 'Polygon':
                coords = geom['coordinates'][0]
            elif geom['type'] == 'MultiPolygon':
                coords = geom['coordinates'][0][0]
            else:
                return False
            lons = [p[0] for p in coords]
            lats = [p[1] for p in coords]
            p_min_lon, p_max_lon = min(lons), max(lons)
            p_min_lat, p_max_lat = min(lats), max(lats)
            if (p_max_lon < min_lon) or (p_min_lon > max_lon): return False
            if (p_max_lat < min_lat) or (p_min_lat > max_lat): return False
            return True
        except:
            return False
    
    zoning_df = zoning_df[zoning_df['geometry'].apply(in_bbox)]
    print(f"   Zones in crime area: {len(zoning_df)}")
    
    # Convert to shapely geometries and calculate shape metrics
    zoning_df['shape'] = zoning_df['geometry'].apply(lambda x: shape(x) if x else None)
    zoning_df = zoning_df.dropna(subset=['shape'])
    
    zoning_df['area'] = zoning_df['shape'].apply(lambda x: x.area)  # sq degrees
    zoning_df['perimeter'] = zoning_df['shape'].apply(lambda x: x.length)
    zoning_df['compactness'] = zoning_df.apply(
        lambda x: (4 * np.pi * x['area']) / (x['perimeter'] ** 2) if x['perimeter'] > 0 else 0,
        axis=1
    )
    
    # 3. Property Tax Data
    print("\n3. Loading property tax data...")
    prop_df = pd.read_csv(PROPERTY_FILE, sep=';', on_bad_lines='skip')
    print(f"   Total property records: {len(prop_df)}")
    
    # Filter to relevant zoning districts
    valid_zones = zoning_df['Zoning District'].unique()
    prop_df = prop_df[prop_df['ZONING_DISTRICT'].isin(valid_zones)]
    print(f"   Properties in study area: {len(prop_df)}")
    
    # Data cleaning
    prop_df['YEAR_BUILT'] = pd.to_numeric(prop_df['YEAR_BUILT'], errors='coerce')
    prop_df['CURRENT_LAND_VALUE'] = pd.to_numeric(prop_df['CURRENT_LAND_VALUE'], errors='coerce')
    prop_df['CURRENT_IMPROVEMENT_VALUE'] = pd.to_numeric(prop_df['CURRENT_IMPROVEMENT_VALUE'], errors='coerce')
    
    return crime_df, zoning_df, prop_df

def extract_tda_features(prop_df, zoning_df):
    """Extract TDA features for each zoning district"""
    print("\n" + "=" * 60)
    print("TDA FEATURE EXTRACTION")
    print("=" * 60)
    
    tda_features = []
    
    for zone in zoning_df['Zoning District'].unique():
        zone_props = prop_df[prop_df['ZONING_DISTRICT'] == zone]
        
        if len(zone_props) < 5:
            continue
        
        # Get shape metrics
        zone_info = zoning_df[zoning_df['Zoning District'] == zone].iloc[0]
        
        # Extract property features
        features = zone_props[['CURRENT_LAND_VALUE', 'CURRENT_IMPROVEMENT_VALUE', 'YEAR_BUILT']].dropna()
        
        if len(features) < 5:
            continue
        
        # Subsample if too large
        if len(features) > 200:
            features = features.sample(200, random_state=42)
        
        # Add shape features
        shape_features = np.array([[zone_info['area'], zone_info['perimeter'], zone_info['compactness']]])
        shape_features_repeated = np.repeat(shape_features, len(features), axis=0)
        
        # Combined feature space (7D)
        combined_features = np.hstack([features.values, shape_features_repeated])
        
        # Normalize
        scaler = StandardScaler()
        normalized = scaler.fit_transform(combined_features)
        
        # Check for valid data
        if not np.isfinite(normalized).all():
            continue
        
        # Compute persistence
        try:
            diagrams = ripser(normalized, maxdim=1)['dgms']
            
            # H0 features
            h0_lifetimes = diagrams[0][:, 1] - diagrams[0][:, 0]
            h0_lifetimes = h0_lifetimes[np.isfinite(h0_lifetimes)]
            
            # H1 features
            h1_lifetimes = []
            if len(diagrams) > 1 and len(diagrams[1]) > 0:
                h1_lifetimes = diagrams[1][:, 1] - diagrams[1][:, 0]
            
            # Extract features
            tda_features.append({
                'zone': zone,
                'zone_category': zone_info['Zoning Category'],
                'zone_classification': zone_info['Zoning Classification'],
                'prop_count': len(zone_props),
                'avg_land_value': features['CURRENT_LAND_VALUE'].mean(),
                'avg_improvement': features['CURRENT_IMPROVEMENT_VALUE'].mean(),
                'avg_year_built': features['YEAR_BUILT'].mean(),
                'area': zone_info['area'],
                'compactness': zone_info['compactness'],
                # TDA features
                'n_h0_components': len(h0_lifetimes),
                'max_h0_lifetime': np.max(h0_lifetimes) if len(h0_lifetimes) > 0 else 0,
                'avg_h0_lifetime': np.mean(h0_lifetimes) if len(h0_lifetimes) > 0 else 0,
                'n_h1_loops': len(h1_lifetimes),
                'max_h1_lifetime': np.max(h1_lifetimes) if len(h1_lifetimes) > 0 else 0,
                'total_persistence': np.sum(h0_lifetimes) + np.sum(h1_lifetimes),
                'tda_complexity': (np.max(h1_lifetimes) if len(h1_lifetimes) > 0 else 0) + 
                                (np.mean(h0_lifetimes) if len(h0_lifetimes) > 0 else 0)
            })
            
        except Exception as e:
            print(f"   Error processing zone {zone}: {e}")
            continue
    
    tda_df = pd.DataFrame(tda_features)
    print(f"\nExtracted TDA features for {len(tda_df)} zones")
    print(f"Features: {list(tda_df.columns)}")
    
    return tda_df

def cluster_zones(tda_df):
    """Cluster zones based on TDA features"""
    print("\n" + "=" * 60)
    print("ZONE CLUSTERING")
    print("=" * 60)
    
    # Select TDA features for clustering
    feature_cols = ['tda_complexity', 'n_h1_loops', 'max_h1_lifetime', 'compactness', 'prop_count']
    X = tda_df[feature_cols].fillna(0)
    
    # Normalize
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    # DBSCAN clustering
    clustering = DBSCAN(eps=0.8, min_samples=3)
    tda_df['cluster'] = clustering.fit_predict(X_scaled)
    
    print(f"\nClusters found: {tda_df['cluster'].nunique()}")
    print(tda_df['cluster'].value_counts().sort_index())
    
    # Assign cluster names
    cluster_names = {
        -1: 'Outlier',
        0: 'Simple/Homogeneous',
        1: 'Mixed/Complex',
        2: 'Irregular',
        3: 'Dense Commercial',
        4: 'Sparse Residential'
    }
    
    tda_df['cluster_name'] = tda_df['cluster'].map(
        lambda x: cluster_names.get(x, f'Cluster {x}')
    )
    
    return tda_df

def analyze_crime_correlation(crime_df, zoning_df, tda_df):
    """Spatial join and correlation analysis"""
    print("\n" + "=" * 60)
    print("CRIME CORRELATION ANALYSIS")
    print("=" * 60)
    
    # Count crimes per zone
    crime_points = [Point(xy) for xy in zip(crime_df['lon'], crime_df['lat'])]
    
    crime_counts = []
    for idx, zone_row in zoning_df.iterrows():
        poly = zone_row['shape']
        if poly is None:
            crime_counts.append(0)
            continue
        count = sum(1 for p in crime_points if poly.contains(p))
        crime_counts.append(count)
    
    zoning_df['crime_count'] = crime_counts
    zoning_df['crime_density'] = zoning_df['crime_count'] / zoning_df['area']
    
    # Merge with TDA features
    merged = zoning_df.merge(
        tda_df,
        left_on='Zoning District',
        right_on='zone',
        how='left'
    )
    
    merged['tda_complexity'] = merged['tda_complexity'].fillna(0)
    merged['crime_density'] = merged['crime_density'].fillna(0)
    merged['cluster'] = merged['cluster'].fillna(-1).astype(int)
    merged['cluster_name'] = merged['cluster_name'].fillna('No Data')
    
    # Calculate correlations
    print("\n--- Correlation Analysis ---")
    if len(merged[merged['tda_complexity'] > 0]) > 2:
        # Only calculate correlations for columns that exist
        available_cols = []
        if 'tda_complexity' in merged.columns:
            available_cols.append('tda_complexity')
            corr_complexity = merged[['tda_complexity', 'crime_density']].corr().iloc[0, 1]
            print(f"TDA Complexity vs Crime Density: {corr_complexity:.3f}")
        
        if 'max_h1_lifetime' in merged.columns:
            corr_h1 = merged[['max_h1_lifetime', 'crime_density']].corr().iloc[0, 1]
            print(f"Max H1 (Loops) vs Crime Density: {corr_h1:.3f}")
        
        if 'area' in merged.columns:
            corr_area = merged[['area', 'crime_density']].corr().iloc[0, 1]
            print(f"Zone Area vs Crime Density: {corr_area:.3f}")
    
    # Crime by cluster
    print("\n--- Crime by Cluster ---")
    cluster_stats = merged.groupby('cluster_name').agg({
        'crime_count': ['sum', 'mean'],
        'crime_density': 'mean',
        'zone': 'count'
    }).round(3)
    print(cluster_stats)
    
    return merged

def create_visualizations(crime_df, merged_df):
    """Generate all visualizations"""
    print("\n" + "=" * 60)
    print("CREATING VISUALIZATIONS")
    print("=" * 60)
    
    # Normalize for coloring
    max_dens = merged_df['crime_density'].max()
    if max_dens > 0:
        merged_df['norm_density'] = merged_df['crime_density'] / max_dens
    else:
        merged_df['norm_density'] = 0
    
    # Color by cluster
    cluster_colors = {
        -1: [128, 128, 128],  # Gray
        0: [100, 200, 100],    # Green
        1: [200, 100, 100],    # Red
        2: [100, 100, 200],    # Blue
        3: [200, 200, 100],    # Yellow
        4: [200, 100, 200]     # Purple
    }
    
    merged_df['fill_color'] = merged_df['cluster'].apply(
        lambda x: cluster_colors.get(x, [150, 150, 150]) + [150]
    )
    
    # Extract polygon coordinates
    def get_coords(geom):
        if geom['type'] == 'Polygon':
            return geom['coordinates'][0]
        elif geom['type'] == 'MultiPolygon':
            return geom['coordinates'][0][0]
        return []
    
    merged_df['path'] = merged_df['geometry'].apply(get_coords)
    
    # 1. 3D Map
    print("\n1. Creating 3D map...")
    
    zoning_layer = pdk.Layer(
        "PolygonLayer",
        merged_df,
        get_polygon="path",
        get_elevation="crime_density * 50000",  # Scale for visibility
        get_fill_color="fill_color",
        get_line_color=[0, 0, 0],
        line_width_min_pixels=1,
        extruded=True,
        pickable=True,
        auto_highlight=True,
    )
    
    crime_layer = pdk.Layer(
        "ScatterplotLayer",
        crime_df,
        get_position=['lon', 'lat', 1000],
        get_radius=8,
        get_fill_color=[255, 255, 0, 255],  # Yellow
        pickable=True,
        stroked=True,
        line_width_min_pixels=1,
    )
    
    view_state = pdk.ViewState(
        latitude=crime_df['lat'].mean(),
        longitude=crime_df['lon'].mean(),
        zoom=13,
        pitch=45,
        bearing=0
    )
    
    r = pdk.Deck(
        layers=[zoning_layer, crime_layer],
        initial_view_state=view_state,
        tooltip={
            "html": "<b>Zone:</b> {Zoning District}<br/>"
                    "<b>Cluster:</b> {cluster_name}<br/>"
                    "<b>Crimes:</b> {crime_count}<br/>"
                    "<b>TDA Complexity:</b> {tda_complexity:.2f}<br/>"
                    "<b>Address:</b> {clean_address}<br/>"
                    "<b>Type:</b> {TYPE}"
        }
    )
    
    r.to_html(OUTPUT_MAP)
    print(f"   Saved: {OUTPUT_MAP}")
    
    # 2. Statistical Charts
    print("\n2. Creating statistical charts...")
    
    # Crime by zone type
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    
    # A. Crime by cluster
    cluster_crime = merged_df.groupby('cluster_name')['crime_count'].sum().sort_values(ascending=False)
    axes[0, 0].bar(range(len(cluster_crime)), cluster_crime.values)
    axes[0, 0].set_xticks(range(len(cluster_crime)))
    axes[0, 0].set_xticklabels(cluster_crime.index, rotation=45, ha='right')
    axes[0, 0].set_title('Property Crimes by Zone Cluster')
    axes[0, 0].set_ylabel('Crime Count')
    
    # B. Crime by zone category
    category_crime = merged_df.groupby('zone_category')['crime_count'].sum().sort_values(ascending=False)
    axes[0, 1].bar(range(len(category_crime)), category_crime.values)
    axes[0, 1].set_xticks(range(len(category_crime)))
    axes[0, 1].set_xticklabels(category_crime.index, rotation=45, ha='right')
    axes[0, 1].set_title('Property Crimes by Zoning Category')
    axes[0, 1].set_ylabel('Crime Count')
    
    # C. Temporal pattern
    crime_by_hour = crime_df.groupby('hour').size()
    axes[1, 0].plot(crime_by_hour.index, crime_by_hour.values, marker='o')
    axes[1, 0].set_title('Property Crimes by Hour of Day')
    axes[1, 0].set_xlabel('Hour')
    axes[1, 0].set_ylabel('Crime Count')
    axes[1, 0].grid(True, alpha=0.3)
    
    # D. Crime type distribution
    crime_types = crime_df['TYPE'].value_counts()
    axes[1, 1].barh(range(len(crime_types)), crime_types.values)
    axes[1, 1].set_yticks(range(len(crime_types)))
    axes[1, 1].set_yticklabels(crime_types.index)
    axes[1, 1].set_title('Property Crime Type Distribution')
    axes[1, 1].set_xlabel('Count')
    
    plt.tight_layout()
    plt.savefig('../visualizations/crime_analysis.png', dpi=150, bbox_inches='tight')
    print("   Saved: ../visualizations/crime_analysis.png")
    
    # 3. Correlation heatmap
    corr_features = ['crime_density', 'tda_complexity', 'max_h1_lifetime']
    # Only include columns that actually exist
    corr_features = [col for col in corr_features if col in merged_df.columns]
    
    if len(corr_features) > 1:
        corr_matrix = merged_df[corr_features].corr()
        
        plt.figure(figsize=(10, 8))
        sns.heatmap(corr_matrix, annot=True, cmap='coolwarm', center=0, fmt='.2f')
        plt.title('Feature Correlation Matrix')
        plt.tight_layout()
        plt.savefig('../visualizations/correlation_matrix.png', dpi=150, bbox_inches='tight')
        print("   Saved: ../visualizations/correlation_matrix.png")
    
    return merged_df

def generate_report(merged_df, crime_df, tda_df):
    """Generate text report"""
    print("\n" + "=" * 60)
    print("GENERATING REPORT")
    print("=" * 60)
    
    with open(OUTPUT_REPORT, 'w') as f:
        f.write("=" * 70 + "\n")
        f.write("PROPERTY CRIME ANALYSIS - GRANDVIEW-WOODLAND 2020\n")
        f.write("=" * 70 + "\n\n")
        
        f.write("EXECUTIVE SUMMARY\n")
        f.write("-" * 70 + "\n")
        f.write(f"Total Property Crimes Analyzed: {len(crime_df)}\n")
        f.write(f"Zoning Districts Studied: {len(merged_df)}\n")
        f.write(f"TDA Clusters Identified: {tda_df['cluster'].nunique()}\n\n")
        
        f.write("PROPERTY CRIME BREAKDOWN\n")
        f.write("-" * 70 + "\n")
        for crime_type in PROPERTY_CRIMES:
            count = len(crime_df[crime_df['TYPE'] == crime_type])
            pct = 100 * count / len(crime_df)
            f.write(f"{crime_type:40s}: {count:4d} ({pct:5.1f}%)\n")
        
        f.write("\n\nKEY FINDINGS\n")
        f.write("-" * 70 + "\n")
        
        # Correlations
        if len(merged_df[merged_df['tda_complexity'] > 0]) > 2:
            corr_complexity = merged_df[['tda_complexity', 'crime_density']].corr().iloc[0, 1]
            corr_h1 = merged_df[['max_h1_lifetime', 'crime_density']].corr().iloc[0, 1]
            
            f.write(f"\n1. TDA Complexity vs Crime Density Correlation: {corr_complexity:.3f}\n")
            if abs(corr_complexity) > 0.3:
                f.write("   → STRONG relationship between property heterogeneity and crime\n")
            elif abs(corr_complexity) > 0.1:
                f.write("   → MODERATE relationship\n")
            else:
                f.write("   → WEAK relationship\n")
            
            f.write(f"\n2. H1 Loops (Geometric Irregularity) vs Crime: {corr_h1:.3f}\n")
            if abs(corr_h1) > 0.3:
                f.write("   → Areas with complex geometries show different crime patterns\n")
        
        # Highest crime zones
        f.write("\n\n3. TOP 5 HIGHEST CRIME ZONES\n")
        top_zones = merged_df.nlargest(5, 'crime_count')[['zone', 'cluster_name', 'crime_count', 'crime_density']]
        for idx, row in top_zones.iterrows():
            f.write(f"   - {row['zone']:10s} ({row['cluster_name']:20s}): {row['crime_count']:3.0f} crimes\n")
        
        # Cluster analysis
        f.write("\n\n4. CRIME BY ZONE CLUSTER\n")
        cluster_stats = merged_df.groupby('cluster_name').agg({
            'crime_count': ['sum', 'mean'],
            'zone': 'count'
        })
        for cluster_name in cluster_stats.index:
            total = cluster_stats.loc[cluster_name, ('crime_count', 'sum')]
            avg = cluster_stats.loc[cluster_name, ('crime_count', 'mean')]
            count = cluster_stats.loc[cluster_name, ('zone', 'count')]
            f.write(f"   {cluster_name:25s}: {total:5.0f} total, {avg:5.1f} avg/zone ({count:.0f} zones)\n")
        
        f.write("\n\n" + "=" * 70 + "\n")
        f.write("END OF REPORT\n")
        f.write("=" * 70 + "\n")
    
    print(f"\n   Saved: {OUTPUT_REPORT}")

def main():
    """Main execution"""
    print("\n" + "="*70)
    print(" PROPERTY CRIME ANALYSIS WITH TOPOLOGICAL DATA ANALYSIS")
    print("="*70 + "\n")
    
    # Load data
    crime_df, zoning_df, prop_df = load_and_clean_data()
    
    # Extract TDA features
    tda_df = extract_tda_features(prop_df, zoning_df)
    
    # Cluster zones
    tda_df = cluster_zones(tda_df)
    
    # Analyze correlations
    merged_df = analyze_crime_correlation(crime_df, zoning_df, tda_df)
    
    # Create visualizations
    merged_df = create_visualizations(crime_df, merged_df)
    
    # Generate report
    generate_report(merged_df, crime_df, tda_df)
    
    print("\n" + "="*70)
    print(" ANALYSIS COMPLETE!")
    print("="*70)
    print(f"\nOutputs:")
    print(f"  - {OUTPUT_MAP}")
    print(f"  - {OUTPUT_REPORT}")
    print(f"  - visualizations/crime_analysis.png")
    print(f"  - visualizations/correlation_matrix.png")
    print()

if __name__ == "__main__":
    main()
