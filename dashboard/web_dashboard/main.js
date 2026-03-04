// State
const state = {
    data: {
        properties: null,
        crimes: null,
        transit: null,
        street_lights: null,
        businesses: null,
        parks: null,
        street_network: null,
        blocks: null // Added explicit blocks data tracking
    },
    // Spatial Grid Index for lightning-fast distance queries
    lightGrid: new Map(),
    gridSizeDeg: 0.001, // Roughly 111 meters
    dynamicLimits: {
        blockValMin: 0,
        blockValMax: 5000000,
        blockAgeMin: 0,
        blockAgeMax: 100
    },
    data: {
        properties: null,
        crimes: null,
        transit: null,
        street_lights: null,
        businesses: null,
        parks: null,
        street_network: null
    },
    activeLayers: new Set(),
    activeCrimes: new Set(),
    filters: {
        propMaxValue: 10000000,
        propMaxAge: 150,
        lightRadius: 30,
        propertyColorMode: 'default', // 'default', 'value', 'age'
        propertyColorMode: 'default', // 'default', 'value', 'age'
        blockColorMode: 'value', // 'value', 'age'
        streetColorMode: 'default'
    },
    intersectionGrid: new Map(),
    streetGrid: new Map(),
    streetById: new Map(),
    intersections: new Map(),
    streetCrimeCounts: new Map(),
    streetMaxCrime: 1,
    mapLayers: {}
};

const COLORS = {
    properties: '#3b82f6', // blue
    transit: '#10b981', // emerald
    lights: '#fbbf24', // amber
    parks: '#22c55e', // green
    businesses: '#8b5cf6', // violet
    street_network: '#334155', // slate-700

    // Crimes
    'crime-Break and Enter Residential/Other': '#ef4444', // red
    'crime-Break and Enter Commercial': '#f97316', // orange
    'crime-Theft of Bicycle': '#eab308', // yellow
    'crime-Theft from Vehicle': '#06b6d4', // cyan
    'crime-Mischief': '#d946ef', // fuchsia
    'crime-Offence Against a Person': '#9f1239' // dark red
};

// --- Color Gradient Helpers ---
function interpolateColor(color1, color2, factor) {
    factor = Math.max(0, Math.min(1, factor)); // clamp between 0 and 1
    const r = Math.round(color1[0] + factor * (color2[0] - color1[0]));
    const g = Math.round(color1[1] + factor * (color2[1] - color1[1]));
    const b = Math.round(color1[2] + factor * (color2[2] - color1[2]));
    return `rgb(${r}, ${g}, ${b})`;
}

function multiInterpolateColor(stops, factor) {
    factor = Math.max(0, Math.min(1, factor));
    if (factor === 1) return `rgb(${stops[stops.length - 1].join(',')})`;
    const segment = 1 / (stops.length - 1);
    const index = Math.floor(factor / segment);
    const remainder = (factor - (index * segment)) / segment;
    return interpolateColor(stops[index], stops[index + 1], remainder);
}

// Deep Purple -> Blue -> Green -> Yellow -> Red -> Crimson
const valueStops = [
    [94, 79, 162], [50, 136, 189], [102, 194, 165], [171, 221, 164],
    [230, 245, 152], [254, 224, 139], [253, 174, 97], [244, 109, 67],
    [213, 62, 79], [158, 1, 66]
];

// Light Yellow -> Orange -> Pink -> Purple -> Black
const ageStops = [
    [252, 253, 191], [254, 159, 109], [222, 73, 104],
    [140, 41, 129], [59, 15, 112], [0, 0, 4]
];

// Street Crime Colors: Light Yellow -> Orange -> Red -> Dark Red
const streetCrimeStops = [
    [255, 237, 160], [254, 178, 76], [240, 59, 32],
    [189, 0, 38], [100, 0, 38]
];

function getStreetCrimeColor(count, maxVal) {
    if (count === 0) return '#334155';
    const factor = Math.min(1, Math.max(0, count / (maxVal || 1)));
    return multiInterpolateColor(streetCrimeStops, factor);
}

function getValueColor(value) {
    const factor = Math.min(1, Math.max(0, value / 5000000)); // 0 to $5M
    return multiInterpolateColor(valueStops, factor);
}

// Blocks use dynamic bounds
function getBlockValueColor(value) {
    const min = state.dynamicLimits.blockValMin;
    const max = state.dynamicLimits.blockValMax;
    const range = (max - min) || 1; // avoid div by 0
    const factor = Math.min(1, Math.max(0, (value - min) / range));
    return multiInterpolateColor(valueStops, factor);
}

function getBlockAgeColor(age) {
    const min = state.dynamicLimits.blockAgeMin;
    const max = state.dynamicLimits.blockAgeMax;
    const range = (max - min) || 1;
    const factor = Math.min(1, Math.max(0, (age - min) / range));
    return multiInterpolateColor(ageStops, factor);
}

function getAgeColor(age) {
    const factor = Math.min(1, Math.max(0, age) / 100); // 0 to 100 years
    return multiInterpolateColor(ageStops, factor);
}

// Map Setup
const map = L.map('map', {
    preferCanvas: true, // Crucial for performance with heavy datasets!
    zoomControl: false // Move it or hide it
}).setView([49.26, -123.12], 12);

// Add custom zoom control
L.control.zoom({ position: 'bottomright' }).addTo(map);

// Define base maps
const darkMap = L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; CartoDB',
    subdomains: 'abcd',
    maxZoom: 20
});

const lightMap = L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; CartoDB',
    subdomains: 'abcd',
    maxZoom: 20
});

const osmMap = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap contributors',
    maxZoom: 19
});

// Add default map
darkMap.addTo(map);

// Add layer control for basemaps
const baseMaps = {
    "Dark Mode": darkMap,
    "Light Mode": lightMap,
    "OpenStreetMap": osmMap
};
L.control.layers(baseMaps, null, { position: 'topright' }).addTo(map);

// DOM Elements
const loadingOverlay = document.getElementById('loading-overlay');
const loadingText = document.getElementById('loading-text');
const statsContainer = document.getElementById('stats-container');

// Load Data
async function loadDatasets() {
    const files = [
        { key: 'properties', url: './public/data/properties.json' },
        { key: 'crimes', url: './public/data/crimes.json' },
        { key: 'transit', url: './public/data/transit.json' },
        { key: 'street_lights', url: './public/data/street_lights.json' },
        { key: 'businesses', url: './public/data/businesses.json' },
        { key: 'parks', url: './public/data/parks.json' },
        { key: 'street_network', url: './public/data/street_network.geojson' },
        { key: 'blocks', url: './public/data/blocks.json' }
    ];

    let loaded = 0;
    for (const file of files) {
        try {
            const res = await fetch(file.url);
            if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
            state.data[file.key] = await res.json();
        } catch (e) {
            console.error(`Failed to load ${file.key}`, e);
        }
        // If we loaded blocks, compute dynamic min/max limits for auto-scaling colors
        if (file.key === 'blocks' && state.data.blocks && state.data.blocks.features) {
            let bFeatures = state.data.blocks.features;

            // Value limits
            const validVals = bFeatures.map(f => f.properties.avg_value).filter(v => v > 0);
            if (validVals.length > 0) {
                state.dynamicLimits.blockValMin = Math.min(...validVals);
                state.dynamicLimits.blockValMax = Math.max(...validVals);
            }

            // Age limits
            const validAges = bFeatures.map(f => f.properties.avg_age).filter(a => a > 0);
            if (validAges.length > 0) {
                state.dynamicLimits.blockAgeMin = Math.min(...validAges);
                state.dynamicLimits.blockAgeMax = Math.max(...validAges);
            }
        }

        loaded++;
        loadingText.innerText = `Loading Data (${loaded}/${files.length})...`;
    }

    // Build Spatial Grid for Street Lights once data is loaded
    if (state.data.street_lights && state.data.street_lights.features) {
        buildLightGrid();
    }
    if (state.data.street_network && state.data.street_network.features) {
        buildStreetNetworkGrids();
    }

    loadingOverlay.classList.add('hidden');
    setupEventListeners();
    updateGradientLegends(); // trigger initial legend formats
}

// --- Spatial Grid Logic ---
// Buckets street lights into a grid dict for fast radius searches
function buildLightGrid() {
    state.lightGrid.clear();
    state.data.street_lights.features.forEach(f => {
        if (!f.geometry || !f.geometry.coordinates) return;
        const [lon, lat] = f.geometry.coordinates;
        const key = getGridKey(lat, lon);
        if (!state.lightGrid.has(key)) state.lightGrid.set(key, []);
        state.lightGrid.get(key).push([lat, lon]);
    });
}

function getGridKey(lat, lon) {
    const latIdx = Math.floor(lat / state.gridSizeDeg);
    const lonIdx = Math.floor(lon / state.gridSizeDeg);
    return `${latIdx},${lonIdx}`;
}

// Haversine distance in meters
function getDistanceMeters(lat1, lon1, lat2, lon2) {
    const R = 6371e3; // metres
    const r1 = lat1 * Math.PI / 180;
    const r2 = lat2 * Math.PI / 180;
    const dr = (lat2 - lat1) * Math.PI / 180;
    const dl = (lon2 - lon1) * Math.PI / 180;

    const a = Math.sin(dr / 2) * Math.sin(dr / 2) +
        Math.cos(r1) * Math.cos(r2) *
        Math.sin(dl / 2) * Math.sin(dl / 2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return R * c;
}

// --- Street Network Spatial Logic ---
function buildStreetNetworkGrids() {
    state.intersectionGrid.clear();
    state.streetGrid.clear();
    state.streetById.clear();
    state.intersections.clear();

    state.data.street_network.features.forEach(f => {
        const id = f.properties.id;
        state.streetById.set(id, f);

        if (f.geometry && f.geometry.coordinates) {
            f.geometry.coordinates.forEach((coord, index) => {
                const [lon, lat] = coord;
                const gridKey = getGridKey(lat, lon);

                if (!state.streetGrid.has(gridKey)) state.streetGrid.set(gridKey, []);
                if (!state.streetGrid.get(gridKey).includes(id)) state.streetGrid.get(gridKey).push(id);

                if (index === 0 || index === f.geometry.coordinates.length - 1) {
                    const exactKey = `${lon.toFixed(5)},${lat.toFixed(5)}`;
                    if (!state.intersections.has(exactKey)) {
                        const intObj = { lat, lon, count: 0, exactKey };
                        state.intersections.set(exactKey, intObj);

                        if (!state.intersectionGrid.has(gridKey)) state.intersectionGrid.set(gridKey, []);
                        state.intersectionGrid.get(gridKey).push(intObj);
                    }
                }
            });
        }
    });
}

function updateStreetCrimeStats() {
    state.streetCrimeCounts.clear();
    state.intersections.forEach(i => i.count = 0);
    state.streetMaxCrime = 1;

    const crimeLayers = Array.from(state.activeLayers).filter(k => k.startsWith('crime-'));
    if (crimeLayers.length === 0) return;

    let activeCrimes = [];
    crimeLayers.forEach(k => {
        const type = k.replace('crime-', '');
        if (state.data.crimes) {
            activeCrimes.push(...state.data.crimes.features.filter(f => f.properties.TYPE === type));
        }
    });

    const offsets = [[0, 0], [-1, -1], [-1, 0], [-1, 1], [0, -1], [0, 1], [1, -1], [1, 0], [1, 1]];

    activeCrimes.forEach(crime => {
        if (!crime.geometry || !crime.geometry.coordinates) return;
        const [lon, lat] = crime.geometry.coordinates;
        const latIdx = Math.floor(lat / state.gridSizeDeg);
        const lonIdx = Math.floor(lon / state.gridSizeDeg);

        let foundIntersection = false;

        for (const [dLat, dLon] of offsets) {
            if (foundIntersection) break;
            const key = `${latIdx + dLat},${lonIdx + dLon}`;
            const intList = state.intersectionGrid.get(key);
            if (intList) {
                for (const iObj of intList) {
                    if (Math.abs(lat - iObj.lat) > 0.0002 || Math.abs(lon - iObj.lon) > 0.0003) continue;
                    if (getDistanceMeters(lat, lon, iObj.lat, iObj.lon) <= 20) {
                        iObj.count++;
                        foundIntersection = true;
                        break;
                    }
                }
            }
        }

        if (foundIntersection) return;

        let closestDist = Infinity;
        let closestId = null;

        for (const [dLat, dLon] of offsets) {
            const key = `${latIdx + dLat},${lonIdx + dLon}`;
            const streetList = state.streetGrid.get(key);
            if (streetList) {
                for (const sId of streetList) {
                    const f = state.streetById.get(sId);
                    if (f && f.geometry && f.geometry.coordinates) {
                        for (const [slon, slat] of f.geometry.coordinates) {
                            if (Math.abs(lat - slat) > 0.001 || Math.abs(lon - slon) > 0.0015) continue;
                            const d = getDistanceMeters(lat, lon, slat, slon);
                            if (d < closestDist) {
                                closestDist = d;
                                closestId = sId;
                            }
                        }
                    }
                }
            }
        }

        if (closestId) {
            const val = (state.streetCrimeCounts.get(closestId) || 0) + 1;
            state.streetCrimeCounts.set(closestId, val);
            if (val > state.streetMaxCrime) state.streetMaxCrime = val;
        }
    });

    // Also update intersection max
    state.intersections.forEach(i => {
        if (i.count > state.streetMaxCrime) state.streetMaxCrime = i.count;
    });
}

// Generate Leaflet GeoJSON layer
function generateLayer(key, color, filterFn = null) {
    let datasetKey = key;
    let data;

    // Handle crime subsets
    if (key.startsWith('crime-')) {
        datasetKey = 'crimes';
        const crimeType = key.replace('crime-', '');

        if (!state.data.crimes) return null;

        // Filter features for specific crime
        const features = state.data.crimes.features.filter(f => f.properties.TYPE === crimeType);
        data = { type: 'FeatureCollection', features };
    } else {
        // Fix data mapping bug for street lights
        if (key === 'lights') datasetKey = 'street_lights';
        data = state.data[datasetKey];
    }

    if (!data) return null;

    let featuresToRender = data.features;
    if (filterFn) {
        featuresToRender = featuresToRender.filter(filterFn);
    }
    const filteredData = { type: 'FeatureCollection', features: featuresToRender };

    // Update specific stat card for this layer
    updateStatCard(key, featuresToRender.length, filteredData);

    return L.geoJSON(filteredData, {
        style: function (feature) {
            // Do not override pointToLayer attributes for Points
            if (feature.geometry && feature.geometry.type === 'Point') {
                return {};
            }

            let finalColor = color;
            let finalWeight = datasetKey === 'street_network' ? 1 : 2;

            if (datasetKey === 'street_network' && state.filters.streetColorMode === 'crime') {
                const count = state.streetCrimeCounts.get(feature.properties.id) || 0;
                if (count === 0) {
                    finalColor = '#334155';
                } else {
                    finalColor = getStreetCrimeColor(count, state.streetMaxCrime);
                    finalWeight = 1.5 + (count / state.streetMaxCrime) * 3; // Thinner segments
                }
            }

            let fillColor = color;
            if (datasetKey === 'blocks') {
                fillColor = state.filters.blockColorMode === 'value' ? getBlockValueColor(feature.properties.avg_value) : getBlockAgeColor(feature.properties.avg_age);
            }

            return {
                color: datasetKey === 'blocks' ? '#000' : finalColor, // Default color for lines/polygons
                weight: datasetKey === 'blocks' ? 1 : finalWeight,
                opacity: datasetKey === 'blocks' ? parseFloat(document.getElementById('blocks-opacity')?.value || 0.6) : 0.8,
                fillColor: fillColor,
                fillOpacity: datasetKey === 'blocks' ? 0.35 : 0.2
            };
        },
        pointToLayer: function (feature, latlng) {
            // Use meaningful icon for transit stations
            if (datasetKey === 'transit') {
                const transitIcon = L.divIcon({
                    html: '<div style="background-color: #10b981; color: white; border-radius: 50%; width: 24px; height: 24px; display: flex; align-items: center; justify-content: center; border: 2px solid white; box-shadow: 0 0 5px rgba(0,0,0,0.5); font-size: 14px;">🚆</div>',
                    className: 'custom-transit-icon',
                    iconSize: [24, 24],
                    iconAnchor: [12, 12]
                });
                return L.marker(latlng, { icon: transitIcon });
            }

            // Beautiful Street Light visualization: adjustable glow + center bulb
            if (datasetKey === 'street_lights') {
                const glow = L.circle(latlng, {
                    radius: state.filters.lightRadius,
                    stroke: false,
                    fillColor: '#fef08a',
                    fillOpacity: 0.15,
                    interactive: false // Don't block clicks on the map underneath
                });

                const bulb = L.circleMarker(latlng, {
                    radius: 1.5, // Pixels
                    fillColor: '#ffffff',
                    color: '#fef08a',
                    weight: 1,
                    opacity: 1,
                    fillOpacity: 1,
                    interactive: true // Allow tooltip hovering
                });

                return L.layerGroup([glow, bulb]);
            }

            let dotColor = color;
            let dotRadius = 8; // Meters! Not pixels!
            let strokeColor = '#fff';
            let strokeWidth = 0.5;
            let pointOpacity = 0.8;

            if (datasetKey === 'properties') {
                const props = feature.properties;

                // Prevent shifting/jumping by exclusively using L.circle instead of switching to L.divIcon
                if (state.filters.propertyColorMode === 'value' && props.is_value_outlier) {
                    dotRadius = 14; // Reduced from 20 based on feedback
                    strokeColor = '#ef4444'; // Red Glow
                    strokeWidth = 2; // Thinner stroke
                    pointOpacity = 1;
                } else if (state.filters.propertyColorMode === 'age' && props.is_age_outlier) {
                    dotRadius = 14;
                    strokeColor = '#a855f7'; // Slightly softer purple
                    strokeWidth = 2;
                    pointOpacity = 1;
                }

                if (state.filters.propertyColorMode === 'value') {
                    dotColor = getValueColor(props.property_value || 0);
                } else if (state.filters.propertyColorMode === 'age') {
                    dotColor = getAgeColor(props.building_age || 0);
                }
            }

            // Using L.circle instead of L.circleMarker ensures points scale proportionally with the map zoom
            return L.circle(latlng, {
                radius: dotRadius,
                fillColor: dotColor,
                color: strokeColor,
                weight: strokeWidth,
                opacity: 1,
                fillOpacity: pointOpacity
            });
        },
        onEachFeature: function (feature, layer) {
            // Street network doesn't need detailed popups, just a simple tooltip
            if (datasetKey === 'street_network') {
                if (feature.properties.name && feature.properties.name !== 'Unknown Street') {
                    layer.bindTooltip(feature.properties.name, { sticky: true });
                }
                return;
            }

            let popupContent = '<div style="color: #333">';
            const p = feature.properties;

            // Safety check for geometry
            if (!feature.geometry || feature.geometry.type !== 'Point') return;

            const coords = feature.geometry.coordinates; // [lon, lat]
            const lon = coords[0].toFixed(5);
            const lat = coords[1].toFixed(5);

            // Format Property Tooltip
            if (p.PID !== undefined) {
                // It's a property layer
                const hNum = p.FROM_CIVIC_NUMBER ? Math.floor(p.FROM_CIVIC_NUMBER) : '';
                const street = p.STREET_NAME || '';
                const address = `${hNum} ${street}`.trim() || 'Address Unknown';

                popupContent += `<h4 style="margin:0 0 5px; color:#2563eb">${address}</h4>`;

                if (p.is_value_outlier) popupContent += `<span style="display:inline-block;background:#ef4444;color:white;padding:2px 6px;border-radius:4px;font-size:0.75rem;margin-bottom:6px;">Value Outlier (Z: ${p.value_z_score})</span><br>`;
                if (p.is_age_outlier) popupContent += `<span style="display:inline-block;background:#9333ea;color:white;padding:2px 6px;border-radius:4px;font-size:0.75rem;margin-bottom:6px;">Age Outlier (Z: ${p.age_z_score})</span><br>`;

                if (p.is_value_outlier || p.is_age_outlier) {
                    popupContent += `<span style="font-size: 0.75rem; color: var(--text-muted); display:block; margin-bottom: 6px;"><i>*Z-score denotes standard deviations from the block average.</i></span>`;
                }

                if (p.property_value) popupContent += `<strong>Value:</strong> $${p.property_value.toLocaleString()} <span style="font-size: 0.8em; color: gray;">(Block Avg: $${p.block_avg_val ? p.block_avg_val.toLocaleString() : 'N/A'})</span><br>`;
                if (p.property_type) popupContent += `<strong>Type:</strong> ${p.property_type}<br>`;
                if (p.building_age) popupContent += `<strong>Age:</strong> ${p.building_age} years <span style="font-size: 0.8em; color: gray;">(Block Avg: ${p.block_avg_age ? p.block_avg_age : 'N/A'})</span><br>`;
                if (p.ZONING_DISTRICT) popupContent += `<strong>Zoning:</strong> ${p.ZONING_DISTRICT}<br>`;
                popupContent += `<strong>Lat/Lon:</strong> ${lat}, ${lon}<br>`;
            }
            // Format Crime Tooltip
            else if (p.CRIME_CATEGORY !== undefined) {
                popupContent += `<h4 style="margin:0 0 5px; color:#dc2626">${p.TYPE}</h4>`;
                if (p.HUNDRED_BLOCK) popupContent += `<strong>Address:</strong> ${p.HUNDRED_BLOCK}<br>`;
                if (p.NEIGHBOURHOOD) popupContent += `<strong>Neighborhood:</strong> ${p.NEIGHBOURHOOD}<br>`;
                if (p.YEAR) popupContent += `<strong>Year:</strong> ${p.YEAR}<br>`;
                popupContent += `<strong>Lat/Lon:</strong> ${lat}, ${lon}<br>`;
            }
            // Format Blocks Tooltip
            else if (datasetKey === 'blocks') {
                popupContent += `<h4 style="margin:0 0 5px; color:#f59e0b">Spatial Block #${p.block_id}</h4>`;

                // Add Property Count calculation dynamically if it isn't in JSON
                // Defaulting to "Multiple" if count isn't exported, but let's try to export it from python next
                const propCount = p.property_count || 'Detailed';

                popupContent += `<strong>Properties Present:</strong> ${propCount}<br>`;

                if (p.avg_value) popupContent += `<strong>Avg Property Value:</strong> $${Math.round(p.avg_value).toLocaleString()}<br>`;
                if (p.avg_age) popupContent += `<strong>Avg Building Age:</strong> ${Math.round(p.avg_age)} years<br>`;

                popupContent += `<strong>Total Crimes:</strong> ${p.crime_count || 0}<br>`;
            }
            // Generic fallback for others (Parks, Transit, etc)
            else {
                for (let prop in p) {
                    if (p[prop] && prop !== 'Status') { // Ignore boring internal fields
                        popupContent += `<strong>${prop}:</strong> ${p[prop]}<br>`;
                    }
                }
                popupContent += `<strong>Lat/Lon:</strong> ${lat}, ${lon}<br>`;
            }

            popupContent += '</div>';
            layer.bindPopup(popupContent);
        }
    });
}

function renderActiveLayers() {
    // Clear existing
    Object.values(state.mapLayers).forEach(layer => map.removeLayer(layer));
    state.mapLayers = {};

    // Clear stats container to redraw them based on selected items
    statsContainer.innerHTML = '';

    // Update street crime stats if active
    if (state.activeLayers.has('street_network') && state.filters.streetColorMode === 'crime') {
        updateStreetCrimeStats();
        const streetGradEnd = document.getElementById('street-grad-end');
        if (streetGradEnd) {
            streetGradEnd.innerText = `${state.streetMaxCrime} Crimes`;
        }
    }

    // Define a discrete Z-Index ordering so polygons don't cover lines, and lines don't cover points
    const zOrder = {
        'blocks': 10,
        'street_network': 20,
        'intersection_hotspots': 25,
        'properties': 30,
        'lights': 35,
        'parks': 40,
        'businesses': 45,
        'transit': 60
    };

    const sortedLayers = Array.from(state.activeLayers).sort((a, b) => {
        const orderA = a.startsWith('crime-') ? 50 : (zOrder[a] || 0);
        const orderB = b.startsWith('crime-') ? 50 : (zOrder[b] || 0);
        return orderA - orderB;
    });

    // Render layers in defined z-order
    sortedLayers.forEach(layerKey => {
        let filterFn = null;

        // Apply property slider filters if this is the property layer
        if (layerKey === 'properties') {
            filterFn = (feature) => {
                const props = feature.properties;
                // If slider is NOT maxed out, filter out values above the slider. 
                // If it is exactly 10,000,000, we treat it as "$10M+" and let everything through.
                if (state.filters.propMaxValue < 10000000 && props.property_value > state.filters.propMaxValue) return false;

                if (props.building_age > state.filters.propMaxAge) return false;
                return true;
            };
        }

        const l = generateLayer(layerKey, COLORS[layerKey] || '#ffffff', filterFn);
        if (l) {
            l.addTo(map);
            state.mapLayers[layerKey] = l;
        }
    });

    // Calculate dynamic cross-layer stats and inject into UI
    updateIlluminationStats();

    // Render Intersection Hotspots if active
    if (state.activeLayers.has('street_network') && state.filters.streetColorMode === 'crime') {
        const hotspotsGrp = L.featureGroup();
        state.intersections.forEach(intObj => {
            if (intObj.count > 0) {
                const hColor = getStreetCrimeColor(intObj.count, state.streetMaxCrime);
                const circle = L.circleMarker([intObj.lat, intObj.lon], {
                    radius: 6 + (intObj.count / state.streetMaxCrime) * 12,
                    fillColor: hColor,
                    color: '#ffffff',
                    weight: 2,
                    opacity: 1,
                    fillOpacity: 0.9,
                    className: 'intersection-hotspot'
                });
                circle.bindPopup(`<h4 style="margin:0;color:#ef4444">Intersection Hotspot</h4><strong>Intersection Crimes:</strong> ${intObj.count}`);
                circle.addTo(hotspotsGrp);
            }
        });
        hotspotsGrp.addTo(map);
        state.mapLayers['intersection_hotspots'] = hotspotsGrp;
    }
}

// Stats UI Logic
// Calculate Crimes vs Illumination Stats
function updateIlluminationStats() {
    // Only calculate if BOTH lights and at least one crime layer are active
    const hasLights = state.activeLayers.has('lights');
    const crimeLayers = Array.from(state.activeLayers).filter(k => k.startsWith('crime-'));

    // Remove existing card if any
    const existingCard = document.getElementById('stat-illumination');
    if (existingCard) existingCard.remove();

    if (!hasLights || crimeLayers.length === 0 || state.lightGrid.size === 0) return;

    let unlitCrimes = 0;
    let totalActiveCrimes = 0;
    const radiusMeters = state.filters.lightRadius;

    // Collect all currently active crimes
    const activeCrimeFeatures = [];
    crimeLayers.forEach(layerKey => {
        const crimeType = layerKey.replace('crime-', '');
        if (state.data.crimes) {
            const filtered = state.data.crimes.features.filter(f => f.properties.TYPE === crimeType);
            activeCrimeFeatures.push(...filtered);
        }
    });

    totalActiveCrimes = activeCrimeFeatures.length;
    if (totalActiveCrimes === 0) return;

    // The grid cells to check for each crime (current cell + 8 immediate neighbors)
    const offsets = [
        [0, 0], [-1, -1], [-1, 0], [-1, 1], [0, -1], [0, 1], [1, -1], [1, 0], [1, 1]
    ];

    activeCrimeFeatures.forEach(crime => {
        if (!crime.geometry || !crime.geometry.coordinates) return;
        const [lon, lat] = crime.geometry.coordinates;

        const latIdx = Math.floor(lat / state.gridSizeDeg);
        const lonIdx = Math.floor(lon / state.gridSizeDeg);

        let isIlluminated = false;

        // Check neighboring grid cells
        for (const [dLat, dLon] of offsets) {
            if (isIlluminated) break;
            const key = `${latIdx + dLat},${lonIdx + dLon}`;
            const lightsInCell = state.lightGrid.get(key);

            if (lightsInCell) {
                for (const [lLat, lLon] of lightsInCell) {
                    // Quick bounding box check before expensive haversine
                    // 1 degree lat is ~111km, so 1 meter is roughly 0.000009 degrees
                    const approxRadiusDeg = radiusMeters * 0.00001;
                    if (Math.abs(lat - lLat) > approxRadiusDeg || Math.abs(lon - lLon) > approxRadiusDeg * 1.5) {
                        continue;
                    }

                    const dist = getDistanceMeters(lat, lon, lLat, lLon);
                    if (dist <= radiusMeters) {
                        isIlluminated = true;
                        break;
                    }
                }
            }
        }

        if (!isIlluminated) {
            unlitCrimes++;
        }
    });

    // Calculate percentage
    const unlitPercent = ((unlitCrimes / totalActiveCrimes) * 100).toFixed(1);

    const cardHtml = `
        <div class="stat-card glass-panel illumination-stat" id="stat-illumination" style="border-left: 4px solid #fef08a;">
            <div class="stat-title">Unilluminated Crimes</div>
            <div class="stat-value" style="color: #fef08a;">${unlitCrimes.toLocaleString()}</div>
            <div class="stat-title" style="margin-top: 5px;">${unlitPercent}% of active crimes occurred outside the ${radiusMeters}m light radius</div>
        </div>
    `;
    statsContainer.insertAdjacentHTML('afterbegin', cardHtml); // Put it first
}

function getStatTitle(layerKey) {
    if (layerKey.startsWith('crime-')) return layerKey.replace('crime-', '');
    switch (layerKey) {
        case 'properties': return 'Real Estate Properties';
        case 'transit': return 'Transit Stations';
        case 'lights': return 'Street Lights';
        case 'parks': return 'City Parks';
        case 'businesses': return 'Active Businesses';
        case 'street_network': return 'Street Network Segments';
        case 'blocks': return 'Spatial Blocks';
        default: return layerKey;
    }
}

function updateStatCard(layerKey, count, geojsonData) {
    const title = getStatTitle(layerKey);
    let extraStat = '';

    // If it's properties, calculate Average Value dynamically based on current slider inputs
    if (layerKey === 'properties' && geojsonData.features.length > 0) {
        const sum = geojsonData.features.reduce((acc, f) => acc + (f.properties.property_value || 0), 0);
        const avg = sum / geojsonData.features.length;
        extraStat = `<div class="stat-title" style="margin-top: 10px;">Avg Value</div><div class="stat-value" style="font-size: 1.1rem;">$${(avg / 1000000).toFixed(2)}M</div>`;
    }

    const cardHtml = `
        <div class="stat-card glass-panel" id="stat-${layerKey.replace(/[ /]/g, '-')}">
            <div class="stat-title">${title} (Total)</div>
            <div class="stat-value">${count.toLocaleString()}</div>
            ${extraStat}
        </div>
    `;
    statsContainer.insertAdjacentHTML('beforeend', cardHtml);
}

// User Interactions
function setupEventListeners() {
    // Checkboxes
    document.querySelectorAll('.layer-toggle').forEach(checkbox => {
        checkbox.addEventListener('change', (e) => {
            const layerKey = e.target.dataset.layer;

            if (e.target.checked) {
                state.activeLayers.add(layerKey);
                // Reveal property sliders if properties toggled
                if (layerKey === 'properties') document.getElementById('property-filters').classList.remove('hidden');
                if (layerKey === 'blocks') document.getElementById('block-filters').classList.remove('hidden');
                if (layerKey === 'lights') document.getElementById('light-filters').classList.remove('hidden');
                if (layerKey === 'street_network') {
                    const el = document.getElementById('street-filters');
                    if (el) el.classList.remove('hidden');
                }
            } else {
                state.activeLayers.delete(layerKey);
                if (layerKey === 'properties') document.getElementById('property-filters').classList.add('hidden');
                if (layerKey === 'blocks') document.getElementById('block-filters').classList.add('hidden');
                if (layerKey === 'lights') document.getElementById('light-filters').classList.add('hidden');
                if (layerKey === 'street_network') {
                    const el = document.getElementById('street-filters');
                    if (el) el.classList.add('hidden');
                }
            }

            renderActiveLayers();
        });
    });

    // property sliders
    const propValSlider = document.getElementById('prop-value');
    const propValDisplay = document.getElementById('val-display');
    const propAgeSlider = document.getElementById('prop-age');
    const propAgeDisplay = document.getElementById('age-display');

    propValSlider.addEventListener('input', (e) => {
        state.filters.propMaxValue = Number(e.target.value);
        if (state.filters.propMaxValue >= 10000000) {
            propValDisplay.innerText = `$10M+`;
        } else {
            propValDisplay.innerText = `< $${(state.filters.propMaxValue / 1000000).toFixed(1)}M`;
        }
    });

    propAgeSlider.addEventListener('input', (e) => {
        state.filters.propMaxAge = Number(e.target.value);
        propAgeDisplay.innerText = `< ${state.filters.propMaxAge} yrs`;
    });

    // on mouse up, trigger re-render to avoid lag while dragging
    propValSlider.addEventListener('change', () => {
        if (state.activeLayers.has('properties')) renderActiveLayers();
    });

    propAgeSlider.addEventListener('change', () => {
        if (state.activeLayers.has('properties')) renderActiveLayers();
    });

    // Street Light slider
    const lightRadiusSlider = document.getElementById('light-radius');
    const lightDisplay = document.getElementById('light-display');

    // Property Gradient Radio Buttons
    const gradLegend = document.getElementById('gradient-legend');
    const gradBar = document.getElementById('gradient-bar');
    const gradStart = document.getElementById('grad-start');
    const gradEnd = document.getElementById('grad-end');

    document.querySelectorAll('input[name="propColor"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            state.filters.propertyColorMode = e.target.value;

            if (state.filters.propertyColorMode === 'default') {
                gradLegend.classList.add('hidden');
            } else if (state.filters.propertyColorMode === 'value') {
                gradLegend.classList.remove('hidden');
                gradBar.style.background = 'linear-gradient(to right, rgb(94,79,162), rgb(50,136,189), rgb(102,194,165), rgb(171,221,164), rgb(230,245,152), rgb(254,224,139), rgb(253,174,97), rgb(244,109,67), rgb(213,62,79), rgb(158,1,66))';
                gradStart.innerText = '$0';
                gradEnd.innerText = '$5M+';
            } else if (state.filters.propertyColorMode === 'age') {
                gradLegend.classList.remove('hidden');
                gradBar.style.background = 'linear-gradient(to right, rgb(252,253,191), rgb(254,159,109), rgb(222,73,104), rgb(140,41,129), rgb(59,15,112), rgb(0,0,4))';
                gradStart.innerText = '0 yrs';
                gradEnd.innerText = '100+ yrs';
            }

            // Immediately re-render properties to show updated colors
            if (state.activeLayers.has('properties')) {
                renderActiveLayers();
            }
        });
    });

    lightRadiusSlider.addEventListener('input', (e) => {
        state.filters.lightRadius = Number(e.target.value);
        lightDisplay.innerText = `${state.filters.lightRadius}m`;
        // Since we only change radius, we don't need to completely redraw the map layers,
        // we just need to update the illumination stats math if and only if both layers are active
        if (state.activeLayers.has('lights') && Array.from(state.activeLayers).some(k => k.startsWith('crime-'))) {
            updateIlluminationStats();
        }
    });

    lightRadiusSlider.addEventListener('change', () => {
        if (state.activeLayers.has('lights')) renderActiveLayers();
    });

    // Block Color Radio Buttons
    const blockGradLegend = document.getElementById('block-gradient-legend');
    const blockGradBar = document.getElementById('block-gradient-bar');
    const blockGradStart = document.getElementById('block-grad-start');
    const blockGradEnd = document.getElementById('block-grad-end');

    // Set initial block gradient state based on default value ('value')
    if (blockGradBar) {
        blockGradBar.style.background = 'linear-gradient(to right, rgb(94,79,162), rgb(50,136,189), rgb(102,194,165), rgb(171,221,164), rgb(230,245,152), rgb(254,224,139), rgb(253,174,97), rgb(244,109,67), rgb(213,62,79), rgb(158,1,66))';
        blockGradStart.innerText = '$1M';
        blockGradEnd.innerText = '$3.5M+';
    }

    document.querySelectorAll('input[name="blockColor"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            state.filters.blockColorMode = e.target.value;

            if (state.filters.blockColorMode === 'value') {
                blockGradBar.style.background = 'linear-gradient(to right, rgb(94,79,162), rgb(50,136,189), rgb(102,194,165), rgb(171,221,164), rgb(230,245,152), rgb(254,224,139), rgb(253,174,97), rgb(244,109,67), rgb(213,62,79), rgb(158,1,66))';
                // Update to dynamic text next
            } else if (state.filters.blockColorMode === 'age') {
                blockGradBar.style.background = 'linear-gradient(to right, rgb(252,253,191), rgb(254,159,109), rgb(222,73,104), rgb(140,41,129), rgb(59,15,112), rgb(0,0,4))';
            }
            updateGradientLegends();

            if (state.activeLayers.has('blocks')) {
                renderActiveLayers();
            }
        });
    });

    // Street Color Radio Buttons
    const streetGradLegend = document.getElementById('street-gradient-legend');
    const streetGradBar = document.getElementById('street-gradient-bar');
    if (streetGradBar) {
        streetGradBar.style.background = 'linear-gradient(to right, rgb(255,237,160), rgb(254,178,76), rgb(240,59,32), rgb(189,0,38), rgb(100,0,38))';
    }

    document.querySelectorAll('input[name="streetColor"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            state.filters.streetColorMode = e.target.value;
            if (state.filters.streetColorMode === 'crime') {
                streetGradLegend.classList.remove('hidden');
            } else {
                streetGradLegend.classList.add('hidden');
            }
            if (state.activeLayers.has('street_network')) {
                renderActiveLayers();
            }
        });
    });
}

function updateGradientLegends() {
    const blockGradStart = document.getElementById('block-grad-start');
    const blockGradEnd = document.getElementById('block-grad-end');

    if (!blockGradStart || !blockGradEnd) return;

    if (state.filters.blockColorMode === 'value') {
        blockGradStart.innerText = `$${(state.dynamicLimits.blockValMin / 1000000).toFixed(1)}M`;
        blockGradEnd.innerText = `$${(state.dynamicLimits.blockValMax / 1000000).toFixed(1)}M`;
    } else {
        blockGradStart.innerText = `${Math.round(state.dynamicLimits.blockAgeMin)} yrs`;
        blockGradEnd.innerText = `${Math.round(state.dynamicLimits.blockAgeMax)} yrs`;
    }
}

// Init
window.addEventListener('DOMContentLoaded', loadDatasets);
