# Vancouver Crime Analysis Dashboard

Interactive research dashboard for analyzing crime patterns using property-based similarity blocks.

## Phase 1: Property Similarity & Base Layers

This dashboard implements a novel approach to spatial analysis by creating blocks based on property similarity rather than administrative boundaries.

## Installation

```bash
cd /Users/tanyaaggarwal/Desktop/A_research/dashboard
pip install -r requirements.txt
```

## Running the Dashboard

```bash
streamlit run app.py
```

The dashboard will open in your default browser at `http://localhost:8501`

## Features

### Property Similarity Analysis
- Select variables: property value, building age, type, tax levy, zoning
- Adjustable similarity threshold (10%-90%)
- Configurable minimum cluster size
- DBSCAN clustering for block generation

### Multi-Layer Visualization
- **Property Similarity Blocks**: Color-coded by similarity group
- **Crime Points**: Exact coordinates (hundred blocks → precise locations)
- **Transit Stations**: SkyTrain network
- **Street Lighting**: Pole locations with illumination zones
- **Parks**: Green spaces
- **Businesses**: Commercial establishments

### Interactive Controls
- **Checkbox layers**: Stack multiple layers to see correlations
- **Crime filters**: Select types, date ranges
- **Statistics panel**: Real-time metrics for selected layers

## Data Sources

All data from Vancouver Open Data Portal:
- Property Tax Report (primary dataset)
- Crime Data (VPD GeoDASH)
- Rapid Transit Stations
- Street Lighting Poles
- Business Licenses
- Parks
- Zoning Districts (optional reference)

## Research Notes

**Key Innovation**: This dashboard creates analysis units (blocks) dynamically based on property similarity, allowing researchers to identify crime patterns related to property characteristics rather than arbitrary administrative boundaries.

**Next Phases**:
- Phase 2: Advanced crime visualization (heatmaps, temporal animation)
- Phase 3: Environmental correlation analysis
- Phase 4: Comparative block analysis
- Phase 5: Topological Data Analysis (persistent homology)

## File Structure

```
dashboard/
├── app.py                          # Main Streamlit application
├── config.py                       # Configuration and constants
├── requirements.txt                # Python dependencies
├── utils/
│   ├── data_loader.py             # Data loading with caching
│   └── geo_utils.py               # Geographic utilities
├── analysis/
│   └── property_similarity.py     # Core similarity analysis
└── layers/                         # (Future: individual layer modules)
```

## Usage Tips

1. **Start simple**: Enable only "Property Similarity Blocks" first
2. **Adjust threshold**: Lower values = more granular blocks, higher = larger blocks
3. **Stack layers**: Check multiple boxes to see correlations
4. **Click features**: Hover over or click map elements for details
5. **Filter crime**: Use sidebar controls when crime layer is active

## Performance

- Dataset caching with Streamlit `@st.cache_data`
- Street lights subsampled to 20,000 for performance
- Property similarity computed on-demand with progress indicators

## Authors

Research Team - Vancouver Crime Pattern Analysis
February 2026
