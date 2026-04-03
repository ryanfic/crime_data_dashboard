# Codebase Function Hierarchy And Flow

## What This Repository Does

This project analyzes Vancouver urban data with a strong focus on crime, property values, zoning, lighting, transit, and street structure.

It has two main halves:

1. Python scripts that clean data, run analysis, generate topology-driven features, and export visualization-ready artifacts.
2. A static web dashboard that loads precomputed GeoJSON/JSON files and renders them interactively in the browser with Leaflet.

## High-Level File Hierarchy

```mermaid
flowchart TD
    A["Repository"] --> B["src/"]
    A --> C["dashboard/utils/"]
    A --> D["dashboard/web_dashboard/"]
    A --> E["data_pipeline/"]
    A --> F["street_networks/"]
    A --> G["Data/ + outputs/ + visualizations/"]

    B --> B1["clean_crime_data.py"]
    B --> B2["visualize_break_enter.py"]
    B --> B3["analysis_tda.py"]
    B --> B4["property_crime_tda.py"]
    B --> B5["create_network_visuals.py"]

    C --> C1["data_loader.py"]
    C --> C2["geo_utils.py"]
    C --> C3["spatial_analysis.py"]
    C --> C4["generate_spatial_blocks.py"]
    C --> C5["geocode_properties.py"]
    C --> C6["export_street_network.py"]

    D --> D1["index.html"]
    D --> D2["style.css"]
    D --> D3["main.js"]
    D --> D4["public/data/*.json"]

    E --> E1["extract_crime_loops.py"]

    F --> F1["visualize_network.py"]
    F --> F2["data/junctions.csv"]
    F --> F3["data/segments.csv"]
```

## Pipeline Diagram

```mermaid
flowchart LR
    A["Raw crime/property/zoning/street data"] --> B["Python preprocessing"]
    B --> B1["clean_crime_data.py"]
    B --> B2["generate_spatial_blocks.py"]
    B --> B3["extract_crime_loops.py"]
    B --> B4["property_crime_tda.py / analysis_tda.py"]

    B1 --> C["outputs/processed/cleaned_break_enter_data.csv"]
    B2 --> D["dashboard/web_dashboard/public/data/blocks.json"]
    B2 --> E["dashboard/web_dashboard/public/data/properties.json"]
    B3 --> F["dashboard/web_dashboard/public/data/crime_loops.json"]
    B4 --> G["HTML maps + PNGs + text reports"]

    D --> H["dashboard/web_dashboard/main.js"]
    E --> H
    F --> H
    H --> I["Interactive Leaflet dashboard"]
```

## Main Python Scripts

### 1. `src/clean_crime_data.py`

```mermaid
flowchart TD
    A["main()"] --> B["load_crime_data()"]
    B --> C["filter_break_enter_crimes()"]
    C --> D["clean_coordinates()"]
    D --> E["clean_neighborhoods()"]
    E --> F["add_derived_fields()"]
    F --> G["write cleaned_break_enter_data.csv"]
```

Purpose:
- Loads the Vancouver crime CSV.
- Keeps only break-and-enter incidents.
- Removes unusable coordinates such as `(0, 0)`.
- Removes missing neighborhoods.
- Adds a simpler `CRIME_CATEGORY` field.
- Saves a cleaned dataset for later mapping.

### 2. `src/visualize_break_enter.py`

```mermaid
flowchart TD
    A["main()"] --> B["load_cleaned_data()"]
    A --> C["load_zoning_data()"]
    A --> D["create_base_map()"]
    D --> E["add_zoning_districts()"]
    B --> F["add_crime_markers()"]
    C --> E
    E --> G["add_legend()"]
    F --> G
    G --> H["add_layer_control()"]
    H --> I["save_map()"]
```

Purpose:
- Converts UTM crime coordinates into latitude/longitude.
- Loads zoning polygons.
- Builds a Folium map.
- Draws zoning districts and crime points as separate layers.
- Exports an interactive HTML map.

### 3. `src/analysis_tda.py`

```mermaid
flowchart TD
    A["main()"] --> B["load_data()"]
    B --> C["bbox-filter zoning polygons"]
    C --> D["process_property_tda()"]
    D --> E["build_map()"]
    E --> F["crime + zoning PyDeck HTML"]
```

Purpose:
- A simpler TDA prototype.
- Loads crime, zoning, and property records.
- Computes persistence-based complexity metrics for each zoning district.
- Builds a PyDeck 3D map with crime points and extruded zoning polygons.

### 4. `src/property_crime_tda.py`

```mermaid
flowchart TD
    A["main()"] --> B["load_and_clean_data()"]
    B --> C["extract_tda_features()"]
    C --> D["cluster_zones()"]
    D --> E["analyze_crime_correlation()"]
    E --> F["create_visualizations()"]
    F --> G["generate_report()"]
```

Purpose:
- This is the most complete analysis script in `src/`.
- Loads crimes, zoning polygons, and property tax data.
- Builds topological features from property distributions plus zone shape metrics.
- Clusters zoning districts with DBSCAN.
- Counts crimes inside each zone.
- Produces a 3D map, charts, correlation heatmap, and text report.

### 5. `src/create_network_visuals.py`

```mermaid
flowchart TD
    A["main()"] --> B["load_analysis_results()"]
    B --> C["create_crime_network_graph()"]
    B --> D["create_spatial_crime_map()"]
    B --> E["create_temporal_network()"]
    B --> F["create_sunburst_chart()"]
    B --> G["create_sankey_diagram()"]
```

Purpose:
- Builds secondary visual summaries from crime data.
- Produces:
- a crime co-occurrence network,
- a 3D spatial-time scatter plot,
- an hour-vs-crime bipartite network,
- a sunburst chart,
- and a Sankey diagram.

## Dashboard Utility Layer

```mermaid
flowchart TD
    A["dashboard/utils/data_loader.py"] --> B["load_property_data()"]
    A --> C["load_crime_data()"]
    A --> D["load_transit_stations()"]
    A --> E["load_street_lights()"]
    A --> F["load_businesses()"]
    A --> G["load_parks()"]
    A --> H["load_zoning()"]
    A --> I["get_data_summary()"]

    J["dashboard/utils/geo_utils.py"] --> J1["utm_to_latlon()"]
    J --> J2["latlon_to_utm()"]
    J --> J3["parse_geojson_from_string()"]
    J --> J4["extract_coordinates_from_geojson()"]
    J --> J5["create_buffer()"]
    J --> J6["point_in_polygon()"]
    J --> J7["calculate_distance()"]

    K["dashboard/utils/spatial_analysis.py"] --> K1["haversine_distance()"]
    K --> K2["find_nearest_light_distance()"]
    K --> K3["analyze_crimes_outside_lights()"]

    L["dashboard/utils/generate_spatial_blocks.py"] --> L1["generate_blocks()"]
    L1 --> L2["polygonize street network"]
    L2 --> L3["assign properties/crimes to blocks"]
    L3 --> L4["compute neighbors + averages + outliers"]
    L4 --> L5["write blocks.json + updated properties.json"]

    M["data_pipeline/extract_crime_loops.py"] --> M1["extract_loops()"]
    M1 --> M2["ripser H1 loops by crime type"]
    M2 --> M3["derive mode1/mode2/mode3 geometries"]
    M3 --> M4["write crime_loops.json"]
```

## Web Dashboard Function Hierarchy

```mermaid
flowchart TD
    A["main.js startup"] --> B["loadDatasets()"]
    B --> C["buildBlockPropertyIndex()"]
    B --> D["buildLightGrid()"]
    B --> E["buildStreetNetworkGrids()"]
    B --> F["setupEventListeners()"]
    B --> G["updateGradientLegends()"]

    F --> H["renderActiveLayers()"]

    H --> I["computeBlockGroups()"]
    H --> J["updateStreetCrimeStats()"]
    H --> K["generateLayer()"]
    H --> L["updateIlluminationStats()"]
    H --> M["updateTdaPanel()"]
    H --> N["updateGradientLegends()"]

    I --> O["getFilteredBlockStats()"]
    J --> P["getStreetDirection()"]
    J --> Q["getSegmentOrientation()"]
    J --> R["distPointToSegment()"]
    R --> S["getDistanceMeters()"]

    K --> T["getValueColor()"]
    K --> U["getBlockValueColor()"]
    K --> V["getBlockAgeColor()"]
    K --> W["getAgeColor()"]
    T --> X["multiInterpolateColor()"]
    U --> X
    V --> X
    W --> X
    X --> Y["interpolateColor()"]
```

## Dashboard Logic Explained

### `loadDatasets()`
- Fetches all JSON and GeoJSON files from `public/data/`.
- Stores them in the global `state`.
- Precomputes dynamic min/max values for map legends.
- Builds indexes so later interactions stay fast.

### `buildBlockPropertyIndex()` and `getFilteredBlockStats()`
- Group property values and ages by `block_id`.
- Recompute a filtered mean using a standard deviation threshold.
- This powers block coloring, outlier logic, and tooltips.

### `computeBlockGroups()`
- Optionally merges nearby block averages into value bands.
- This is not geometry merging; it is display grouping by similar averages.

### `buildLightGrid()`
- Stores street lights in a spatial grid for fast “crime near a light?” checks.

### `buildStreetNetworkGrids()` and `updateStreetCrimeStats()`
- Indexes street segments and intersections in grid cells.
- For each active crime point, finds the nearest street segment.
- Aggregates counts so streets can be colored by crime intensity.

### `generateLayer()`
- Creates the correct Leaflet layer for each dataset.
- Handles custom behavior for:
- property dots,
- street lights,
- transit icons,
- blocks,
- crimes,
- street network,
- and TDA loop overlays.

### `renderActiveLayers()`
- Central render loop of the dashboard.
- Clears old layers.
- Recomputes any derived state needed by current settings.
- Creates layers in z-order.
- Updates statistics cards, legends, lighting stats, and the TDA side panel.

### `setupEventListeners()`
- Connects all checkboxes, sliders, and radio buttons to state changes.
- Most interactions eventually call `renderActiveLayers()`.

### `updateTdaPanel()`
- Reads `crime_loops.json`.
- Filters loops by currently active crime type.
- Compares loop-adjacent block values or ages against citywide values.
- Generates the explanatory sidebar content for the topological layer.

## Important Cross-File Connections

```mermaid
flowchart LR
    A["clean_crime_data.py"] --> B["outputs/processed/cleaned_break_enter_data.csv"]
    B --> C["visualize_break_enter.py"]

    D["street_networks/data/*.csv"] --> E["generate_spatial_blocks.py"]
    F["public/data/properties.json"] --> E
    G["public/data/crimes.json"] --> E
    E --> H["public/data/blocks.json"]
    E --> I["public/data/properties.json (updated with block stats/outliers)"]

    I --> J["web_dashboard/main.js"]
    H --> J

    G --> K["extract_crime_loops.py"]
    H --> K
    K --> L["public/data/crime_loops.json"]
    L --> J
```

## In Plain English

The codebase is building a spatial research workflow:

- It starts by cleaning and transforming city datasets.
- It converts raw points and polygons into map-ready data.
- It creates derived spatial units called blocks using the street network.
- It attaches properties and crimes to those blocks.
- It uses topological data analysis to measure structure and irregularity in both property distributions and crime patterns.
- It exports those results into a browser-based dashboard where the user can filter layers, inspect outliers, compare blocks, and explore TDA crime loops interactively.

## Notable Design Pattern

The repository is mostly “precompute in Python, explore in JavaScript”:

- Python does expensive data cleaning, geometry handling, topological analysis, and artifact generation.
- The browser only loads prepared JSON and focuses on fast interaction, filtering, coloring, and tooltip/stat rendering.
