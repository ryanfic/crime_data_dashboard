"""
Enhanced Network Visualizations for Property Crime Analysis
Creates beautiful, meaningful graphs showing connections between zones, crimes, and TDA features
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import networkx as nx
from matplotlib.patches import FancyBboxPatch
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import json

# Set style
plt.style.use('dark_background')
sns.set_palette("husl")

def load_analysis_results():
    """Load the analysis results from previous run"""
    print("Loading analysis results...")
    
    # Load crime data
    crime_df = pd.read_csv('../data/crimedata_csv_Grandview-Woodland_2020.csv')
    PROPERTY_CRIMES = [
        'Theft from Vehicle', 'Other Theft', 'Break and Enter Commercial',
        'Break and Enter Residential/Other', 'Theft of Bicycle', 'Theft of Vehicle'
    ]
    crime_df = crime_df[crime_df['TYPE'].isin(PROPERTY_CRIMES)]
    crime_df = crime_df[(crime_df['X'] != 0) & (crime_df['Y'] != 0)]
    
    from pyproj import Transformer
    transformer = Transformer.from_crs("EPSG:26910", "EPSG:4326")
    lat, lon = transformer.transform(crime_df['X'].values, crime_df['Y'].values)
    crime_df['lat'] = lat
    crime_df['lon'] = lon
    
    # Simulated TDA results (since we don't have the merged_df saved)
    # In practice, you'd save and load the actual results
    
    return crime_df

def create_crime_network_graph(crime_df):
    """Create network graph showing crime type relationships"""
    print("\n1. Creating Crime Network Graph...")
    
    # Create co-occurrence matrix (crimes happening in same area)
    # Group by approximate location
    crime_df['location_group'] = (
        crime_df['lat'].round(3).astype(str) + ',' + 
        crime_df['lon'].round(3).astype(str)
    )
    
    # Create network
    G = nx.Graph()
    
    # Add nodes for crime types
    crime_types = crime_df['TYPE'].unique()
    for crime_type in crime_types:
        count = len(crime_df[crime_df['TYPE'] == crime_type])
        G.add_node(crime_type, node_type='crime', count=count)
    
    # Add edges based on co-occurrence in same locations
    location_groups = crime_df.groupby('location_group')['TYPE'].apply(list)
    
    for crimes_at_location in location_groups:
        if len(crimes_at_location) > 1:
            for i in range(len(crimes_at_location)):
                for j in range(i+1, len(crimes_at_location)):
                    crime_i = crimes_at_location[i]
                    crime_j = crimes_at_location[j]
                    if G.has_edge(crime_i, crime_j):
                        G[crime_i][crime_j]['weight'] += 1
                    else:
                        G.add_edge(crime_i, crime_j, weight=1)
    
    # Create visualization
    fig, ax = plt.subplots(figsize=(16, 12), facecolor='#0a0a0a')
    ax.set_facecolor('#0a0a0a')
    
    # Layout
    pos = nx.spring_layout(G, k=2, iterations=50, seed=42)
    
    # Draw edges with width based on weight
    edges = G.edges()
    weights = [G[u][v]['weight'] for u, v in edges]
    max_weight = max(weights) if weights else 1
    
    for (u, v), weight in zip(edges, weights):
        nx.draw_networkx_edges(
            G, pos,
            edgelist=[(u, v)],
            width=weight/max_weight * 5,
            alpha=0.6,
            edge_color='#00d9ff',
            ax=ax
        )
    
    # Draw nodes
    node_sizes = [G.nodes[node]['count'] * 3 for node in G.nodes()]
    node_colors = plt.cm.plasma(np.linspace(0, 1, len(G.nodes())))
    
    nx.draw_networkx_nodes(
        G, pos,
        node_size=node_sizes,
        node_color=node_colors,
        alpha=0.9,
        edgecolors='white',
        linewidths=2,
        ax=ax
    )
    
    # Labels
    labels = {node: f"{node}\n({G.nodes[node]['count']})" for node in G.nodes()}
    nx.draw_networkx_labels(
        G, pos,
        labels,
        font_size=10,
        font_weight='bold',
        font_color='white',
        ax=ax
    )
    
    ax.set_title('Property Crime Network\nNode Size = Crime Count | Edge Width = Co-occurrence',
                 fontsize=20, pad=20, color='white', fontweight='bold')
    ax.axis('off')
    
    plt.tight_layout()
    plt.savefig('../visualizations/crime_network.png', dpi=200, facecolor='#0a0a0a', bbox_inches='tight')
    print("   Saved: ../visualizations/crime_network.png")
    plt.close()

def create_spatial_crime_map(crime_df):
    """Create interactive 3D scatter map"""
    print("\n2. Creating Interactive Spatial Map...")
    
    # Sample for performance
    sample_df = crime_df.sample(min(500, len(crime_df)), random_state=42)
    
    # Create color mapping
    crime_types = sample_df['TYPE'].unique()
    colors = px.colors.qualitative.Vivid[:len(crime_types)]
    color_map = dict(zip(crime_types, colors))
    sample_df['color'] = sample_df['TYPE'].map(color_map)
    
    # Create 3D scatter
    fig = go.Figure()
    
    for crime_type in crime_types:
        subset = sample_df[sample_df['TYPE'] == crime_type]
        fig.add_trace(go.Scatter3d(
            x=subset['lon'],
            y=subset['lat'],
            z=subset['HOUR'],  # Time as Z-axis
            mode='markers',
            name=crime_type,
            marker=dict(
                size=5,
                color=color_map[crime_type],
                opacity=0.8,
                line=dict(color='white', width=0.5)
            ),
            text=[f"{crime_type}<br>Time: {h}:00" for h in subset['HOUR']],
            hovertemplate='%{text}<extra></extra>'
        ))
    
    fig.update_layout(
        title=dict(
            text='Property Crimes in 3D Space<br><sub>X,Y = Location | Z = Hour of Day</sub>',
            font=dict(size=24, color='white')
        ),
        scene=dict(
            xaxis_title='Longitude',
            yaxis_title='Latitude',
            zaxis_title='Hour of Day',
            bgcolor='#0a0a0a',
            xaxis=dict(backgroundcolor="rgb(20,20,30)", gridcolor="gray"),
            yaxis=dict(backgroundcolor="rgb(20,20,30)", gridcolor="gray"),
            zaxis=dict(backgroundcolor="rgb(20,20,30)", gridcolor="gray")
        ),
        paper_bgcolor='#0a0a0a',
        plot_bgcolor='#0a0a0a',
        font=dict(color='white'),
        legend=dict(
            bgcolor='rgba(0,0,0,0.5)',
            bordercolor='white',
            borderwidth=1
        ),
        height=800
    )
    
    fig.write_html('../visualizations/interactive_3d_map.html')
    print("   Saved: ../visualizations/interactive_3d_map.html")

def create_temporal_network(crime_df):
    """Create network showing temporal patterns"""
    print("\n3. Creating Temporal Pattern Network...")
    
    # Create hour-crime type relationships
    hour_crime = crime_df.groupby(['HOUR', 'TYPE']).size().reset_index(name='count')
    
    # Create bipartite graph
    G = nx.Graph()
    
    # Add hour nodes
    for hour in range(24):
        G.add_node(f"Hour {hour}", node_type='hour', layer=0)
    
    # Add crime type nodes
    for crime_type in crime_df['TYPE'].unique():
        G.add_node(crime_type, node_type='crime', layer=1)
    
    # Add edges
    for _, row in hour_crime.iterrows():
        G.add_edge(f"Hour {int(row['HOUR'])}", row['TYPE'], weight=row['count'])
    
    # Create visualization
    fig, ax = plt.subplots(figsize=(20, 12), facecolor='#0a0a0a')
    ax.set_facecolor('#0a0a0a')
    
    # Bipartite layout
    hour_nodes = [n for n in G.nodes() if G.nodes[n]['node_type'] == 'hour']
    crime_nodes = [n for n in G.nodes() if G.nodes[n]['node_type'] == 'crime']
    
    pos = {}
    for i, node in enumerate(hour_nodes):
        pos[node] = (i * 0.8, 0)
    for i, node in enumerate(crime_nodes):
        pos[node] = (i * 3, 2)
    
    # Draw edges
    for (u, v) in G.edges():
        weight = G[u][v]['weight']
        nx.draw_networkx_edges(
            G, pos,
            edgelist=[(u, v)],
            width=weight/20,
            alpha=0.4,
            edge_color='#00d9ff',
            ax=ax
        )
    
    # Draw nodes
    nx.draw_networkx_nodes(
        G, pos,
        nodelist=hour_nodes,
        node_size=500,
        node_color='#ff6b6b',
        alpha=0.9,
        edgecolors='white',
        linewidths=2,
        ax=ax
    )
    
    nx.draw_networkx_nodes(
        G, pos,
        nodelist=crime_nodes,
        node_size=1500,
        node_color='#4ecdc4',
        alpha=0.9,
        edgecolors='white',
        linewidths=2,
        ax=ax
    )
    
    # Labels
    nx.draw_networkx_labels(
        G, pos,
        font_size=9,
        font_weight='bold',
        font_color='white',
        ax=ax
    )
    
    ax.set_title('Temporal Crime Pattern Network\nRed = Hours | Teal = Crime Types',
                 fontsize=22, pad=20, color='white', fontweight='bold')
    ax.axis('off')
    
    plt.tight_layout()
    plt.savefig('../visualizations/temporal_network.png', dpi=200, facecolor='#0a0a0a', bbox_inches='tight')
    print("   Saved: ../visualizations/temporal_network.png")
    plt.close()

def create_sunburst_chart(crime_df):
    """Create hierarchical sunburst chart"""
    print("\n4. Creating Hierarchical Sunburst Chart...")
    
    # Add time categories
    crime_df['hour_category'] = pd.cut(crime_df['HOUR'], 
                                       bins=[-1, 6, 12, 18, 24],
                                       labels=['Night (0-6)', 'Morning (6-12)', 
                                              'Afternoon (12-18)', 'Evening (18-24)'])
    
    # Create hierarchy
    hierarchy = crime_df.groupby(['hour_category', 'TYPE']).size().reset_index(name='count')
    
    fig = go.Figure(go.Sunburst(
        labels=list(hierarchy['hour_category']) + list(hierarchy['TYPE']),
        parents=[''] * len(hierarchy['hour_category'].unique()) + list(hierarchy['hour_category']),
        values=[hierarchy[hierarchy['hour_category'] == cat]['count'].sum() 
                for cat in hierarchy['hour_category'].unique()] + list(hierarchy['count']),
        branchvalues="total",
        marker=dict(
            colors=px.colors.qualitative.Vivid,
            line=dict(color='white', width=2)
        ),
        hovertemplate='<b>%{label}</b><br>Count: %{value}<extra></extra>'
    ))
    
    fig.update_layout(
        title=dict(
            text='Crime Distribution by Time and Type',
            font=dict(size=24, color='white')
        ),
        paper_bgcolor='#0a0a0a',
        font=dict(color='white', size=14),
        height=700
    )
    
    fig.write_html('../visualizations/crime_sunburst.html')
    print("   Saved: ../visualizations/crime_sunburst.html")

def create_sankey_diagram(crime_df):
    """Create Sankey flow diagram"""
    print("\n5. Creating Sankey Flow Diagram...")
    
    # Create month -> type -> hour flow
    crime_df['month_name'] = pd.to_datetime(crime_df['MONTH'], format='%m').dt.strftime('%B')
    crime_df['hour_cat'] = pd.cut(crime_df['HOUR'], bins=4, labels=['Early', 'Mid', 'Late', 'Night'])
    
    # Aggregate
    flow = crime_df.groupby(['month_name', 'TYPE', 'hour_cat']).size().reset_index(name='count')
    flow = flow.nlargest(50, 'count')  # Top 50 flows
    
    # Create node lists
    all_nodes = list(flow['month_name'].unique()) + list(flow['TYPE'].unique()) + list(flow['hour_cat'].unique())
    node_dict = {node: i for i, node in enumerate(all_nodes)}
    
    # Create links
    source = []
    target = []
    value = []
    colors = []
    
    for _, row in flow.iterrows():
        source.append(node_dict[row['month_name']])
        target.append(node_dict[row['TYPE']])
        value.append(row['count'])
        colors.append('rgba(100, 200, 250, 0.4)')
    
    fig = go.Figure(data=[go.Sankey(
        node=dict(
            pad=15,
            thickness=20,
            line=dict(color='white', width=2),
            label=all_nodes,
            color=px.colors.qualitative.Vivid[:len(all_nodes)]
        ),
        link=dict(
            source=source,
            target=target,
            value=value,
            color=colors
        )
    )])
    
    fig.update_layout(
        title=dict(
            text='Crime Flow: Month → Type → Time',
            font=dict(size=24, color='white')
        ),
        font=dict(size=12, color='white'),
        paper_bgcolor='#0a0a0a',
        height=700
    )
    
    fig.write_html('../visualizations/crime_flow_sankey.html')
    print("   Saved: ../visualizations/crime_flow_sankey.html")

def main():
    print("="*70)
    print(" CREATING ENHANCED NETWORK VISUALIZATIONS")
    print("="*70 + "\n")
    
    crime_df = load_analysis_results()
    
    create_crime_network_graph(crime_df)
    create_spatial_crime_map(crime_df)
    create_temporal_network(crime_df)
    create_sunburst_chart(crime_df)
    create_sankey_diagram(crime_df)
    
    print("\n" + "="*70)
    print(" VISUALIZATION COMPLETE!")
    print("="*70)
    print("\nCreated:")
    print("  1. visualizations/crime_network.png - Network graph of crime relationships")
    print("  2. visualizations/interactive_3d_map.html - 3D spatial-temporal map")
    print("  3. visualizations/temporal_network.png - Time-crime network")
    print("  4. visualizations/crime_sunburst.html - Hierarchical breakdown")
    print("  5. visualizations/crime_flow_sankey.html - Flow diagram")
    print()

if __name__ == "__main__":
    main()
