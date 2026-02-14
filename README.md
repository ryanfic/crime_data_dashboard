# Crime Analysis Research Project

This repository contains analysis and visualization of crime data in Vancouver, with a focus on break and enter incidents. The project includes both static analysis scripts and an interactive Plotly Dash dashboard for real-time exploration of crime patterns.

## Project Structure

```
A_research/
├── src/                    # Analysis scripts
│   ├── analysis_tda.py                           # Topological Data Analysis
│   ├── clean_crime_data.py                       # Data cleaning scripts
│   ├── create_network_visuals.py                 # Network visualization generation
│   ├── persistent_homology_crime_analysis.py     # Persistent homology analysis
│   ├── property_crime_tda.py                     # Property crime TDA analysis
│   └── visualize_break_enter.py                  # Break & Enter visualization
├── dashboard/              # Interactive Plotly Dash application
│   ├── app.py             # Main dashboard application
│   ├── config.py          # Configuration settings
│   ├── requirements.txt   # Dashboard dependencies
│   ├── utils/             # Utility modules (data loading, geo processing)
│   └── analysis/          # Analysis modules (property similarity)
├── data/                   # Processed data files
├── Data/                   # Raw data files (see Data Requirements below)
├── outputs/                # Generated outputs
│   ├── images/            # PNG visualizations
│   ├── html/              # Interactive HTML maps
│   └── processed/         # Cleaned/processed data files
├── docs/                   # Documentation and reports
├── crimedata_csv_AllNeighbourhoods_2020/  # Crime incident data
├── visualizations/         # Additional visualization outputs
└── venv/                   # Python virtual environment
```

## Features

### Interactive Dashboard
The Plotly Dash dashboard (`dashboard/app.py`) provides:
- **Interactive crime mapping** with customizable filters
- **Zoning district visualization** with color-coded categories
- **Street lighting analysis** to examine correlations with crime
- **Temporal analysis** for crime patterns over time
- **Property similarity analysis** (requires geocoded property data)

### Analysis Scripts
- **`analysis_tda.py`** - Topological Data Analysis on crime data
- **`persistent_homology_crime_analysis.py`** - Analyzes crime patterns using persistent homology
- **`property_crime_tda.py`** - TDA specifically for property crimes
- **`clean_crime_data.py`** - Cleans and preprocesses raw crime data
- **`create_network_visuals.py`** - Creates network-based visualizations
- **`visualize_break_enter.py`** - Generates interactive maps for break and enter crimes

## Getting Started

### Prerequisites
```bash
# Activate virtual environment
source venv/bin/activate

# Install dashboard dependencies
pip install -r dashboard/requirements.txt
```

### Running the Dashboard
```bash
cd dashboard
python app.py
```
The dashboard will be available at `http://localhost:8050`

### Running Analysis Scripts
```bash
python src/clean_crime_data.py
python src/visualize_break_enter.py
```

### View Outputs
- Check `outputs/images/` for visualization PNGs
- Open `outputs/html/` files in a browser for interactive maps
- Find processed data in `outputs/processed/`

## Data Requirements

### Included Data Files
The repository includes smaller dataset files such as:
- Crime incident data (2020)
- Transit data (routes, stops, schedules)
- Parks and rapid transit station locations
- Street lighting pole locations
- Traffic signal data
- Zoning district information

### Large Data Files (Not Included in Repository)

> **⚠️ IMPORTANT**: Due to GitHub's file size limitations, the following large data files are **excluded** from the repository but are required for full functionality:

| File | Size | Purpose | Status |
|------|------|---------|--------|
| `Data /property-tax-report.csv` | 421 MB | Property tax data for similarity analysis | **Excluded** |
| `Data /building-footprints-2015.csv` | 85 MB | Building footprint geometries | **Excluded** |
| `Data /google_transit/stop_times.txt` | 87 MB | Transit stop timing data | **Excluded** |
| `Data /google_transit.zip` | Large | Compressed transit data | **Excluded** |
| `Data /business-licences.csv` | Large | Business license records | **Excluded** |

**To use these files:**
1. Download them separately from the original Vancouver Open Data portal
2. Place them in the `Data /` directory
3. The applications will automatically detect and use them

**Note:** The dashboard's property similarity feature requires `property-tax-report.csv` with geocoded coordinates. Without this file, that specific feature will be disabled.

## Output Files

Generated outputs are organized in the `outputs/` directory:
- **Images**: Spatial distribution maps, persistence barcodes, and other visualizations
- **HTML**: Interactive crime maps with Folium/Plotly
- **Processed**: Cleaned CSV files ready for analysis

## Technical Notes

- All raw data should be placed in the `Data/` directory
- Source code is in the `src/` directory
- Dashboard code is in the `dashboard/` directory
- Keep the root directory clean - all outputs go to `outputs/`
- The `.gitignore` file excludes large data files, virtual environments, and cache directories

## Repository Setup

This repository uses a `.gitignore` to exclude:
- Large data files (>50MB)
- Virtual environment (`venv/`)
- Python cache files (`__pycache__/`, `*.pyc`)
- System files (`.DS_Store`)

## License & Data Sources

Crime data and city datasets are sourced from the Vancouver Open Data portal. Please refer to the original data sources for licensing information.
