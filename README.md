# Crime Analysis Research Project

This repository contains analysis and visualization of crime data in Vancouver, with a focus on break and enter incidents.

## Project Structure

```
A_research/
├── src/                    # Source code
│   ├── analysis_tda.py                           # Topological Data Analysis
│   ├── clean_crime_data.py                       # Data cleaning scripts
│   ├── create_network_visuals.py                 # Network visualization generation
│   ├── persistent_homology_crime_analysis.py     # Persistent homology analysis
│   ├── property_crime_tda.py                     # Property crime TDA analysis
│   └── visualize_break_enter.py                  # Break & Enter visualization
├── data/                   # Raw data files
├── outputs/                # Generated outputs
│   ├── images/            # PNG visualizations
│   ├── html/              # Interactive HTML maps
│   └── processed/         # Cleaned/processed data files
├── docs/                   # Documentation and reports
├── Data/                   # Original data directory
├── Employment_docs/        # Employment-related documents
└── venv/                   # Python virtual environment

```

## Scripts Overview

### Analysis Scripts
- **`analysis_tda.py`** - Topological Data Analysis on crime data
- **`persistent_homology_crime_analysis.py`** - Analyzes crime patterns using persistent homology
- **`property_crime_tda.py`** - TDA specifically for property crimes

### Data Processing
- **`clean_crime_data.py`** - Cleans and preprocesses raw crime data

### Visualization Scripts
- **`create_network_visuals.py`** - Creates network-based visualizations
- **`visualize_break_enter.py`** - Generates interactive maps for break and enter crimes

## Getting Started

1. **Activate virtual environment:**
   ```bash
   source venv/bin/activate
   ```

2. **Run analysis scripts:**
   ```bash
   python src/clean_crime_data.py
   python src/visualize_break_enter.py
   ```

3. **View outputs:**
   - Check `outputs/images/` for visualization PNGs
   - Open `outputs/html/` files in a browser for interactive maps
   - Find processed data in `outputs/processed/`

## Output Files

Generated outputs are organized in the `outputs/` directory:
- **Images**: Spatial distribution maps, persistence barcodes, and other visualizations
- **HTML**: Interactive crime maps
- **Processed**: Cleaned CSV files ready for analysis

## Notes

- All raw data should be placed in the `data/` directory
- Source code is in the `src/` directory
- Keep the root directory clean - all outputs go to `outputs/`
