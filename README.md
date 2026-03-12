# Vancouver Data Explorer (Web Dashboard)

An interactive, high-performance web dashboard for exploring spatial blocks, real estate properties, and urban infrastructure in Vancouver.

This dashboard statically serves large pre-computed spatial datasets (from `public/data/`) and performs lightning-fast client-side filtering, aggregation, and statistical outlier rendering entirely in the browser using Leaflet.js and spatial indexing.

## Architecture

The application is completely static (no backend database or Python server is required to run the dashboard). It consists of:
- `index.html`: The layout and CSS custom properties.
- `main.js`: Core logic (data fetching, map rendering, grid indexing, statistical filtering).
- `style.css`: UI styling and custom range slider aesthetics.
- `public/data/`: Pre-computed JSON data files (Blocks, Properties, Crimes, Street Lights, Transit).

## Running the Dashboard

You need Node.js installed to run the local development server.

```bash
cd web_dashboard
npm install
npm run dev
```

The terminal will provide a local URL (usually `http://localhost:5173/` or `http://localhost:5174/`). Open this URL in your web browser.

## Key Features

1. **Spatial Blocks Coloring**: Color blocks by Average Property Value or Average Building Age, with dynamic color gradients based on the visible data range.
2. **SD Outlier Filter**: A client-side filter that hides extreme property outliers (e.g., properties > 1.5 standard deviations from their block's mean). The map and block statistics recompute instantly when adjusted.
3. **Block Grouping**: Dynamically merge adjacent blocks whose average values are within a user-defined percentage threshold, rendering them as a unified region with a shared color.
4. **Street Crime Network**: Overlay historic crime data onto the street network, styling street segments by local crime density.
5. **Interactive Popups**: Click any property dot to see its value, its block's average, and a dynamically computed Z-score.

## Available Data Layers
- Spatial Blocks (Street Intersections)
- Real Estate Properties
- Street Network (optionally colored by Crime Density)
- Crime Incidents (2020)
- Transit Stations
- Street Lights
- Parks & Businesses

## Performance Notes
- Renders ~50,000 property geometries and intricate street networks directly in the browser.
- Uses **custom spatial grids** (defined in `main.js`) for $O(1)$ fast lookups between street layers and crimes/intersections, entirely avoiding expensive spatial joins on the main thread during rendering.
- Dynamically rescales all color gradients based on 2nd to 98th percentile distributions to ensure high visual contrast regardless of active filters.
