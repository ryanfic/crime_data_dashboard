import 'leaflet/dist/leaflet.css';
import L from 'leaflet';

// State
const state = {
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
        propertyColorMode: 'default' // 'default', 'value', 'age'
    },
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

function getValueColor(value) {
    const factor = Math.min(1, value / 5000000); // 0 to $5M
    return multiInterpolateColor(valueStops, factor);
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
        { key: 'properties', url: '/data/properties.json' },
        { key: 'crimes', url: '/data/crimes.json' },
        { key: 'transit', url: '/data/transit.json' },
        { key: 'street_lights', url: '/data/street_lights.json' },
        { key: 'businesses', url: '/data/businesses.json' },
        { key: 'parks', url: '/data/parks.json' },
        { key: 'street_network', url: '/data/street_network.geojson' }
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
        loaded++;
        loadingText.innerText = `Loading Data (${loaded}/${files.length})...`;
    }

    loadingOverlay.classList.add('hidden');
    setupEventListeners();
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
            // Apply line styling specifically for the street network LineStrings
            if (datasetKey === 'street_network') {
                return {
                    color: color,
                    weight: 1.5,
                    opacity: 0.6
                };
            }
            return {};
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
            if (datasetKey === 'properties') {
                if (state.filters.propertyColorMode === 'value') {
                    dotColor = getValueColor(feature.properties.property_value || 0);
                } else if (state.filters.propertyColorMode === 'age') {
                    dotColor = getAgeColor(feature.properties.building_age || 0);
                }
            }

            // Use circle markers for huge performance boost 
            // compared to standard DOM icon markers
            return L.circleMarker(latlng, {
                radius: 4,
                fillColor: dotColor,
                color: '#fff',
                weight: 0.5,
                opacity: 0.8,
                fillOpacity: 0.6
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
                if (p.property_value) popupContent += `<strong>Value:</strong> $${p.property_value.toLocaleString()}<br>`;
                if (p.property_type) popupContent += `<strong>Type:</strong> ${p.property_type}<br>`;
                if (p.building_age) popupContent += `<strong>Age:</strong> ${p.building_age} years<br>`;
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

    // Render layers
    state.activeLayers.forEach(layerKey => {
        let filterFn = null;

        // Apply property slider filters if this is the property layer
        if (layerKey === 'properties') {
            filterFn = (feature) => {
                const props = feature.properties;
                // If it doesn't have value/age, include it OR drop it. We drop it if strictly filtering.
                if (props.property_value > state.filters.propMaxValue) return false;
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
}

// Stats UI Logic
function getStatTitle(layerKey) {
    if (layerKey.startsWith('crime-')) return layerKey.replace('crime-', '');
    switch (layerKey) {
        case 'properties': return 'Real Estate Properties';
        case 'transit': return 'Transit Stations';
        case 'lights': return 'Street Lights';
        case 'parks': return 'City Parks';
        case 'businesses': return 'Active Businesses';
        case 'street_network': return 'Street Network Segments';
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
                if (layerKey === 'lights') document.getElementById('light-filters').classList.remove('hidden');
            } else {
                state.activeLayers.delete(layerKey);
                if (layerKey === 'properties') document.getElementById('property-filters').classList.add('hidden');
                if (layerKey === 'lights') document.getElementById('light-filters').classList.add('hidden');
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
    });

    lightRadiusSlider.addEventListener('change', () => {
        if (state.activeLayers.has('lights')) renderActiveLayers();
    });
}

// Init
window.addEventListener('DOMContentLoaded', loadDatasets);
