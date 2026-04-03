const ACTIVE_BOUNDARY_BUFFER_M = 50;
const PERMUTATION_ITERATIONS = 1000;  // Increased for SE ≈ 0.016 at p=0.05
const METERS_PER_DEG_LAT = 111000;
const METERS_PER_DEG_LON = 72800;     // at 49°N Vancouver

// Hardcoded crime filter – Break & Enter only
const BE_CRIME_TYPES = ['Break and Enter Residential/Other', 'Break and Enter Commercial'];

const phState = {
    adjacency: null,
    persistence: null,
    blocks: null,
    crimes: null,
    mapLayers: {},
    analysisBase: null,
    analysisCache: new Map(),
    activeAnalysis: null,
    activeModal: null,
};

// Make recomputeTopology available globally immediately
window.recomputeTopology = null;

const map = L.map('map', { preferCanvas: true, zoomControl: false })
    .setView([49.26, -123.12], 12);
L.control.zoom({ position: 'bottomright' }).addTo(map);

const darkMap = L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; CartoDB', subdomains: 'abcd', maxZoom: 20
});
const lightMap = L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; CartoDB', subdomains: 'abcd', maxZoom: 20
});
const osmMap = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors', maxZoom: 20
});

darkMap.addTo(map);

// Track current map mode
let currentMapMode = 'dark';
let eps2State = 'AUTO'; // Can be 'AUTO' or 'MANUAL'
const layerControl = L.control.layers({
    "Dark Mode": darkMap,
    "Light Mode": lightMap,
    "Standard (OSM)": osmMap
}, null, { position: 'bottomright' }).addTo(map);

// Listen for layer changes
map.on('baselayerchange', function (e) {
    if (e.name === 'Light Mode' || e.name === 'Standard (OSM)') {
        currentMapMode = 'light';
    } else {
        currentMapMode = 'dark';
    }
    // Redraw layers with adapted colors for new basemap
    if (phState.mapLayers.centroids) {
        map.removeLayer(phState.mapLayers.centroids);
        drawCentroids();
    }
    if (phState.mapLayers.sharpness) {
        map.removeLayer(phState.mapLayers.sharpness);
        drawSharpnessLayer();
    }
    if (phState.mapLayers.blocks) {
        map.removeLayer(phState.mapLayers.blocks);
        drawBlocks();
    }
});

async function loadAll() {
    const timeStr = '?t=' + new Date().getTime();
    const files = [
        { key: 'blocks', url: './public/data/blocks.json' + timeStr },
        { key: 'properties', url: './public/data/properties.json' + timeStr },
        { key: 'crimes', url: './public/data/crimes.json' + timeStr },
        { key: 'sharpStreets', url: './public/data/sharp_street_segments.json' + timeStr },
    ];

    let loaded = 0;
    const loadingText = document.getElementById('loading-text');

    for (const file of files) {
        try {
            loadingText.textContent = `Loading ${file.key}…`;
            const res = await fetch(file.url);
            if (!res.ok) throw new Error(`${file.key}: ${res.status}`);
            phState[file.key] = await res.json();
        } catch (error) {
            console.error(`Failed: ${file.key}`, error);
        }
        loaded += 1;
    }

    loadingText.textContent = 'Computing PH from server…';

    // Safety timeout to ensure we don't get stuck
    const safetyTimeout = setTimeout(() => {
        console.log('[PH] Safety timeout - showing UI anyway');
        const overlay = document.getElementById('loading-overlay');
        if (overlay) overlay.classList.add('hidden');
    }, 20000);

    populateCrimeRadios();

    // Load initial PH data from server with timeout
    try {
        const eps1Slider = document.getElementById('epsilon1-threshold');
        const eps2Slider = document.getElementById('epsilon2-threshold');
        const eps1_m = eps1Slider ? parseFloat(eps1Slider.value) : 200;
        const eps2_threshold = eps2Slider ? parseFloat(eps2Slider.value) : 0.75;

        const controller = new AbortController();
        const fetchTimeout = setTimeout(() => controller.abort(), 15000);

        const alphaSlider = document.getElementById('alpha-slider');
        const betaSlider = document.getElementById('beta-slider');
        const gammaSlider = document.getElementById('gamma-slider');
        const alpha = alphaSlider ? parseFloat(alphaSlider.value) : 0.333;
        const beta = betaSlider ? parseFloat(betaSlider.value) : 0.333;
        const gamma = gammaSlider ? parseFloat(gammaSlider.value) : 0.334;

        const res = await fetch('http://127.0.0.1:8001/api/compute-ph', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                epsilon1_m: eps1_m,
                epsilon2_threshold: eps2_threshold,
                alpha: alpha,
                beta: beta,
                gamma: gamma
            }),
            signal: controller.signal
        });

        clearTimeout(fetchTimeout);

        if (res.ok) {
            const data = await res.json();
            phState.adjacency = data.adjacency;
            phState.persistence = data.persistence;
            console.log('[PH] Initial PH computed:', phState.adjacency?.stats);
        }
    } catch (error) {
        console.error('[PH] Failed to load initial PH data:', error);
        // Fallback: load from precomputed files
        try {
            phState.adjacency = await fetch('./public/data/ph_adjacency.json').then(r => r.json());
            phState.persistence = await fetch('./public/data/ph_persistence.json').then(r => r.json());
        } catch (e) {
            console.error('[PH] Fallback also failed:', e);
        }
    }

    clearTimeout(safetyTimeout);
    loadingText.textContent = 'Processing data…';

    try {
        console.log('[PH] buildDerivedAnalysis starting...');
        buildDerivedAnalysis();
        console.log('[PH] buildDerivedAnalysis done, analysisBase:', phState.analysisBase !== null);
        console.log('[PH] computeActiveAnalysis starting...');
        computeActiveAnalysis();
        console.log('[PH] computeActiveAnalysis done, activeAnalysis:', phState.activeAnalysis !== null);
    } catch (error) {
        console.error('[PH] CRITICAL Error in analysis:', error);
        console.error('[PH] Stack:', error.stack);
    }

    const loadingOverlay = document.getElementById('loading-overlay');
    if (loadingOverlay) {
        loadingOverlay.classList.add('hidden');
        console.log('[DEBUG] Loading overlay hidden');
    }

    try {
        console.log('[PH] init() starting...');
        init();
        console.log('[PH] init() done');
    } catch (error) {
        console.error('[PH] CRITICAL Error in init:', error);
        console.error('[PH] Stack:', error.stack);
    }

    // Expose for debugging
    window.__phState = phState;
}

function sharpnessColor(weight, maxWeight) {
    const safeMax = maxWeight || 1;
    // Map weight (epsilon) to [0, 1]
    const t = Math.min(1, Math.max(0, weight / safeMax));

    // Multi-Epsilon Colour Scale (Plasma/Magma-like)
    // Low epsilon (gradual change): Pale Yellow -> Orange
    // Mid epsilon: Red -> Crimson
    // High epsilon (sharp change): Deep Magenta -> Purple

    let r, g, b;
    if (t < 0.33) {
        // Yellow (254, 240, 138) to Orange (249, 115, 22)
        const p = t / 0.33;
        r = Math.round(254 - p * (254 - 249));
        g = Math.round(240 - p * (240 - 115));
        b = Math.round(138 - p * (138 - 22));
    } else if (t < 0.66) {
        // Orange (249, 115, 22) to Crimson (190, 18, 60)
        const p = (t - 0.33) / 0.33;
        r = Math.round(249 - p * (249 - 190));
        g = Math.round(115 - p * (115 - 18));
        b = Math.round(22 - p * (22 - 60));
    } else {
        // Crimson (190, 18, 60) to Deep Purple (76, 29, 149)
        const p = (t - 0.66) / 0.34;
        r = Math.round(190 - p * (190 - 76));
        g = Math.round(18 + p * (29 - 18));
        b = Math.round(60 + p * (149 - 60));
    }
    return `rgb(${r},${g},${b})`;
}

function sharpnessOpacity(weight, maxWeight) {
    const safeMax = maxWeight || 1;
    const t = Math.min(1, Math.max(0, weight / safeMax));
    // Low epsilon = highly transparent (0.2), High epsilon = opaque (0.9)
    return 0.2 + 0.7 * t;
}

function sharpnessWeight(weight, maxWeight) {
    const safeMax = maxWeight || 1;
    const t = Math.min(1, Math.max(0, weight / safeMax));
    // Low epsilon = thin (1px), High epsilon = thick (4px)
    return 1 + 3 * t;
}

function percentile(arr, p) {
    if (!arr || arr.length === 0) return 0;
    const sorted = [...arr].sort((a, b) => a - b);
    const idx = (p / 100) * (sorted.length - 1);
    const lo = Math.floor(idx);
    const hi = Math.ceil(idx);
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (idx - lo);
}

function mean(values) {
    if (!values || values.length === 0) return 0;
    return values.reduce((sum, value) => sum + value, 0) / values.length;
}

// Distance from point (px,py) to line segment (x1,y1)-(x2,y2)
function pointToSegmentDistance(px, py, x1, y1, x2, y2) {
    const dx = x2 - x1;
    const dy = y2 - y1;
    const len2 = dx * dx + dy * dy;
    if (len2 === 0) return Math.sqrt((px - x1) ** 2 + (py - y1) ** 2);

    let t = ((px - x1) * dx + (py - y1) * dy) / len2;
    t = Math.max(0, Math.min(1, t));

    const nearX = x1 + t * dx;
    const nearY = y1 + t * dy;
    return Math.sqrt((px - nearX) ** 2 + (py - nearY) ** 2);
}

// Minimum distance between two line segments
function lineToLineDistance(x1a, y1a, x2a, y2a, x1b, y1b, x2b, y2b) {
    // Check all 4 combinations of endpoints
    const d1 = pointToSegmentDistance(x1a, y1a, x1b, y1b, x2b, y2b);
    const d2 = pointToSegmentDistance(x2a, y2a, x1b, y1b, x2b, y2b);
    const d3 = pointToSegmentDistance(x1b, y1b, x1a, y1a, x2a, y2a);
    const d4 = pointToSegmentDistance(x2b, y2b, x1a, y1a, x2a, y2a);
    return Math.min(d1, d2, d3, d4);
}

function pearsonCorrelation(xs, ys) {
    if (!xs.length || xs.length !== ys.length) return 0;
    const meanX = mean(xs);
    const meanY = mean(ys);
    let numerator = 0;
    let denomX = 0;
    let denomY = 0;

    for (let i = 0; i < xs.length; i += 1) {
        const dx = xs[i] - meanX;
        const dy = ys[i] - meanY;
        numerator += dx * dy;
        denomX += dx * dx;
        denomY += dy * dy;
    }

    if (denomX === 0 || denomY === 0) return 0;
    return numerator / Math.sqrt(denomX * denomY);
}

function mulberry32(seed) {
    let state = seed >>> 0;
    return () => {
        state += 0x6D2B79F5;
        let t = state;
        t = Math.imul(t ^ (t >>> 15), t | 1);
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
}

function projectPoint(lon, lat, metersPerDegLon) {
    return [lon * metersPerDegLon, lat * METERS_PER_DEG_LAT];
}

function cellKey(x, y, cellSize) {
    return `${Math.floor(x / cellSize)},${Math.floor(y / cellSize)}`;
}

function getSharpnessThresholdValue() {
    // Use epsilon2 threshold from server if available
    const stats = phState.adjacency?.stats;
    if (stats?.epsilon2_value !== undefined) {
        return stats.epsilon2_value;
    }
    
    // Fallback if not loaded
    const el = document.getElementById('epsilon2-threshold');
    return el ? parseFloat(el.value) : 0;
}

function getPersistencePercentile() {
    const el = document.getElementById('pers-filter');
    return el ? parseInt(el.value, 10) : 0;
}

// Removed logic that relied on percentile

function getPersistenceCutoff(dim) {
    const diagram = phState.persistence?.diagrams?.[dim] || [];
    if (diagram.length === 0) return 0;
    const persistences = diagram.map(([birth, death]) => death - birth);
    const maxP = Math.max(...persistences, 0.0001);
    // Use slider as percentage of max persistence instead of raw percentile
    return maxP * (getPersistencePercentile() / 100);
}

function getFilteredDiagram(dim) {
    const diagram = phState.persistence?.diagrams?.[dim] || [];
    const cutoff = getPersistenceCutoff(dim);
    return diagram.filter(([birth, death]) => (death - birth) >= cutoff);
}

function getFilteredH1Cycles() {
    const cycles = phState.persistence?.h1_cycles || [];
    const cutoff = getPersistenceCutoff('H1');
    return cycles.filter(cycle => cycle.persistence >= cutoff);
}

function buildDerivedAnalysis() {
    if (!phState.adjacency || !phState.blocks || !phState.crimes) return;

    const edges = phState.adjacency.edges || [];
    const blockCrimeCounts = new Map();
    const blockMaxEdgeWeight = new Map();
    const crimeFeatures = phState.crimes.features || [];
    const edgeCrimeCounts = new Array(edges.length).fill(0);
    const crimeMaxEdgeWeight = new Array(crimeFeatures.length).fill(0);
    const crimeTypes = new Array(crimeFeatures.length).fill('Unknown');

    for (const feature of phState.blocks.features || []) {
        const props = feature.properties || {};
        blockCrimeCounts.set(props.block_id, props.crime_count || 0);
        blockMaxEdgeWeight.set(props.block_id, 0);
    }

    const meanLat = mean(
        crimeFeatures
            .map(feature => feature.geometry?.coordinates?.[1])
            .filter(lat => Number.isFinite(lat))
    ) || 49.26;
    const metersPerDegLon = METERS_PER_DEG_LAT * Math.cos((meanLat * Math.PI) / 180);
    const cellSize = ACTIVE_BOUNDARY_BUFFER_M;
    const radiusSq = ACTIVE_BOUNDARY_BUFFER_M ** 2;
    const edgeGrid = new Map();

    const edgeMeta = edges.map((edge, index) => {
        const midLon = (edge.ax + edge.bx) / 2;
        const midLat = (edge.ay + edge.by) / 2;
        const [px, py] = projectPoint(midLon, midLat, metersPerDegLon);
        const key = cellKey(px, py, cellSize);

        if (!edgeGrid.has(key)) edgeGrid.set(key, []);
        edgeGrid.get(key).push(index);

        blockMaxEdgeWeight.set(edge.a, Math.max(blockMaxEdgeWeight.get(edge.a) || 0, edge.w));
        blockMaxEdgeWeight.set(edge.b, Math.max(blockMaxEdgeWeight.get(edge.b) || 0, edge.w));

        return {
            index,
            a: edge.a,
            b: edge.b,
            w: edge.w,
            midLon,
            midLat,
            px,
            py,
        };
    });

    crimeFeatures.forEach((feature, crimeIndex) => {
        const coords = feature.geometry?.coordinates;
        if (!coords || coords.length < 2) return;

        const [lon, lat] = coords;
        const [px, py] = projectPoint(lon, lat, metersPerDegLon);
        const baseCellX = Math.floor(px / cellSize);
        const baseCellY = Math.floor(py / cellSize);
        let maxNearbyWeight = 0;
        crimeTypes[crimeIndex] = feature.properties?.TYPE || 'Unknown';

        for (let dx = -1; dx <= 1; dx += 1) {
            for (let dy = -1; dy <= 1; dy += 1) {
                const candidates = edgeGrid.get(`${baseCellX + dx},${baseCellY + dy}`);
                if (!candidates) continue;

                for (const edgeIndex of candidates) {
                    const edge = edgeMeta[edgeIndex];
                    const distX = px - edge.px;
                    const distY = py - edge.py;
                    if ((distX * distX) + (distY * distY) > radiusSq) continue;

                    edgeCrimeCounts[edgeIndex] += 1;
                    if (edge.w > maxNearbyWeight) maxNearbyWeight = edge.w;
                }
            }
        }

        crimeMaxEdgeWeight[crimeIndex] = maxNearbyWeight;
    });

    phState.analysisBase = {
        weights: edges.map(edge => edge.w),
        edges,
        edgeMeta,
        edgeCrimeCounts,
        crimeMaxEdgeWeight,
        crimeTypes,
        blockCrimeCounts,
        blockMaxEdgeWeight,
    };
    phState.analysisCache.clear();
}

function computePermutationPValue(boundaryValues, interiorValues, seed) {
    if (!boundaryValues.length || !interiorValues.length) return null;

    const nBoundary = boundaryValues.length;
    const allValues = boundaryValues.concat(interiorValues);
    const shuffled = allValues.slice();
    const totalSum = allValues.reduce((sum, value) => sum + value, 0);
    const observedDiff = mean(boundaryValues) - mean(interiorValues);
    const rng = mulberry32(seed);
    let extremeCount = 0;

    for (let i = 0; i < PERMUTATION_ITERATIONS; i += 1) {
        for (let j = shuffled.length - 1; j > 0; j -= 1) {
            const k = Math.floor(rng() * (j + 1));
            [shuffled[j], shuffled[k]] = [shuffled[k], shuffled[j]];
        }

        let boundarySum = 0;
        for (let j = 0; j < nBoundary; j += 1) {
            boundarySum += shuffled[j];
        }

        const interiorSum = totalSum - boundarySum;
        const permBoundaryMean = boundarySum / nBoundary;
        const permInteriorMean = interiorSum / (shuffled.length - nBoundary);
        if ((permBoundaryMean - permInteriorMean) >= observedDiff) {
            extremeCount += 1;
        }
    }

    return Number((extremeCount / PERMUTATION_ITERATIONS).toFixed(4));
}

function computeActiveAnalysis() {
    if (!phState.analysisBase) return null;

    const thresholdValue = getSharpnessThresholdValue();
    const cacheKey = String(thresholdValue);
    if (phState.analysisCache.has(cacheKey)) {
        phState.activeAnalysis = phState.analysisCache.get(cacheKey);
        return phState.activeAnalysis;
    }

    const {
        edges,
        edgeCrimeCounts,
        crimeMaxEdgeWeight,
        crimeTypes,
        blockCrimeCounts,
        blockMaxEdgeWeight,
    } = phState.analysisBase;

    const activeEdgeIndices = [];
    const activeSharpBlockIds = new Set();

    edges.forEach((edge, index) => {
        if (edge.w < thresholdValue) return;
        activeEdgeIndices.push(index);
        activeSharpBlockIds.add(edge.a);
        activeSharpBlockIds.add(edge.b);
    });

    let boundaryCrimes = 0;
    const boundaryCrimeTypes = {};
    const interiorCrimeTypes = {};

    crimeMaxEdgeWeight.forEach((maxWeight, index) => {
        const type = crimeTypes[index] || 'Unknown';
        if (maxWeight >= thresholdValue) {
            boundaryCrimes += 1;
            boundaryCrimeTypes[type] = (boundaryCrimeTypes[type] || 0) + 1;
        } else {
            interiorCrimeTypes[type] = (interiorCrimeTypes[type] || 0) + 1;
        }
    });

    const totalCrimes = crimeMaxEdgeWeight.length;
    const interiorCrimes = totalCrimes - boundaryCrimes;
    const boundaryBlockCrimes = [];
    const interiorBlockCrimes = [];

    for (const [blockId, crimeCount] of blockCrimeCounts.entries()) {
        if ((blockMaxEdgeWeight.get(blockId) || 0) >= thresholdValue) {
            boundaryBlockCrimes.push(crimeCount);
        } else {
            interiorBlockCrimes.push(crimeCount);
        }
    }

    const selectedWeights = activeEdgeIndices.map(index => edges[index].w);
    const selectedEdgeCrimeCounts = activeEdgeIndices.map(index => edgeCrimeCounts[index]);
    const boundaryMean = mean(boundaryBlockCrimes);
    const interiorMean = mean(interiorBlockCrimes);
    const sharpPct = getPersistencePercentile();
    const result = {
        thresholdPercentile: sharpPct,
        thresholdValue,
        activeEdgeIndices,
        activeSharpBlockIds,
        boundaryCrimeTypes,
        interiorCrimeTypes,
        summary: {
            totalCrimes,
            boundaryCrimes,
            interiorCrimes,
            boundaryPct: totalCrimes ? Number((100 * boundaryCrimes / totalCrimes).toFixed(1)) : 0,
            interiorPct: totalCrimes ? Number((100 * interiorCrimes / totalCrimes).toFixed(1)) : 0,
            boundaryMeanCrimesPerBlock: Number(boundaryMean.toFixed(4)),
            interiorMeanCrimesPerBlock: Number(interiorMean.toFixed(4)),
            meanDiff: Number((boundaryMean - interiorMean).toFixed(4)),
            permutationPValue: computePermutationPValue(
                boundaryBlockCrimes,
                interiorBlockCrimes,
                42 + sharpPct
            ),
            sharpnessCrimeCorrelation: Number(
                pearsonCorrelation(selectedWeights, selectedEdgeCrimeCounts).toFixed(4)
            ),
            sharpEdgeCount: activeEdgeIndices.length,
            sharpBlockCount: activeSharpBlockIds.size,
            totalBlocks: blockCrimeCounts.size,
            bufferRadiusM: ACTIVE_BOUNDARY_BUFFER_M,
        },
    };

    phState.analysisCache.set(cacheKey, result);
    phState.activeAnalysis = result;
    return result;
}

function init() {
    renderSummary();
    drawSharpnessLayer();
    drawBlocks();
    setupControls();
    setupModals();
    // Draw sharp streets after a slight delay to prevent blocking
    setTimeout(() => drawSharpStreets(), 100);
}

function computeCrimeStatsByType() {
    // Get selected crime types
    const selectedTypes = window.getSelectedCrimeTypes ? window.getSelectedCrimeTypes() : [];

    if (!phState.crimes?.features || selectedTypes.length === 0) {
        return null;
    }

    const totalSelectedCrimes = phState.crimes.features.filter(f =>
        selectedTypes.includes(f.properties?.TYPE)
    ).length;

    if (totalSelectedCrimes === 0) return null;

    let boundaryCrimes = 0;
    let interiorCrimes = 0;

    // Use actual PH-computed boundary edges from current adjacency
    const adjacency = phState.adjacency;
    const boundaryEdges = adjacency?.boundary_edges || [];

    // If no boundary edges, all crimes are interior
    if (boundaryEdges.length === 0) {
        return {
            boundaryCrimes: 0,
            interiorCrimes: totalSelectedCrimes,
            totalCrimes: totalSelectedCrimes,
            boundaryPct: '0.0',
            interiorPct: '100.0',
            selectedTypes: selectedTypes.length,
        };
    }

    // Build boundary edge segments
    const boundaryEdgeSegments = boundaryEdges.map(e => ({
        x1: e.ax, y1: e.ay,
        x2: e.bx, y2: e.by,
    }));

    const PROXIMITY_THRESHOLD = 0.0005;

    // Count crimes based on proximity to boundary edges
    let actualBoundaryCrimes = 0;

    phState.crimes.features.forEach(feature => {
        const crimeType = feature.properties?.TYPE;
        if (!selectedTypes.includes(crimeType)) return;

        const coords = feature.geometry?.coordinates;
        if (!coords) return;

        // Check if near any boundary edge
        let minDist = Infinity;
        for (const be of boundaryEdgeSegments) {
            const dist = pointToSegmentDistance(coords[0], coords[1], be.x1, be.y1, be.x2, be.y2);
            if (dist < minDist) minDist = dist;
        }

        if (minDist < PROXIMITY_THRESHOLD) {
            actualBoundaryCrimes++;
        }
    });

    boundaryCrimes = actualBoundaryCrimes;
    interiorCrimes = totalSelectedCrimes - actualBoundaryCrimes;

    return {
        boundaryCrimes,
        interiorCrimes,
        totalCrimes: totalSelectedCrimes,
        boundaryPct: (100 * boundaryCrimes / totalSelectedCrimes).toFixed(1),
        interiorPct: (100 * interiorCrimes / totalSelectedCrimes).toFixed(1),
        selectedTypes: selectedTypes.length,
    };
}

function renderSummary() {
    const el = document.getElementById('ph-summary-stats');
    const persistence = phState.persistence;
    const analysis = computeActiveAnalysis();
    if (!persistence || !analysis) {
        el.innerHTML = '<em>No data loaded.</em>';
        return;
    }

    const stats = persistence.stats;
    const summary = analysis.summary;
    const h0Visible = getFilteredDiagram('H0').length;
    const persPct = getPersistencePercentile();

    // Compute dynamic stats based on selected crime types
    const dynamicStats = computeCrimeStatsByType();

    // Use dynamic stats if available, otherwise use pre-computed
    const displayStats = dynamicStats || summary;
    const boundaryPct = displayStats.boundaryPct;
    const interiorPct = displayStats.interiorPct;
    const crimeCountText = dynamicStats
        ? `(${displayStats.totalCrimes.toLocaleString()} selected types)`
        : '(all types)';

    el.innerHTML =
        '<div style="margin-bottom:8px;"><b style="color:#c084fc;">Method:</b> ' + (persistence.method || 'Single-Linkage H₀ (Union-Find)') + '</div>' +
        '<div style="margin-bottom:8px;">' +
        'Boundary threshold: <b>ε₂ = ' + analysis.thresholdValue.toFixed(3) + '</b>' +
        '<span style="color:#94a3b8;"> (auto-derived from persistence gap)</span>' +
        '</div>' +
        '<div style="background:rgba(255,255,255,0.04); padding:10px; border-radius:6px; text-align:center; margin-bottom:10px;">' +
        '<div style="font-size:1.5rem; font-weight:700; color:#c084fc;">' + h0Visible + '</div>' +
        '<div style="font-size:0.75rem; color:#94a3b8;">Visible Components (H0)</div>' +
        '</div>' +
        '<div style="font-size:0.75rem; border-top:1px solid rgba(255,255,255,0.1); padding-top:8px; margin-top:8px;">' +
        '<div style="display:flex; justify-content:space-between; margin-bottom:4px;">' +
        '<span>Total Crimes:</span> ' +
        '<span style="color:#f8fafc; font-weight:600;">' + displayStats.totalCrimes.toLocaleString() + '</span>' +
        '</div>' +
        '<div style="display:flex; justify-content:space-between; margin-bottom:4px;">' +
        '<span style="color:#f472b6;">On Boundary (>ε):</span> ' +
        '<span style="color:#f8fafc; font-weight:600;">' + boundaryPct + '%</span>' +
        '</div>' +
        '<div style="display:flex; justify-content:space-between; margin-bottom:8px;">' +
        '<span style="color:#94a3b8;">Interior (<ε):</span> ' +
        '<span style="color:#f8fafc; font-weight:600;">' + interiorPct + '%</span>' +
        '</div>' +
        '<div style="margin-top:4px; font-size:0.65rem; color:#64748b; text-align:right;">' + crimeCountText + '</div>' +
        '</div>';

    // Update Epsilon Crime Comparison Stats Panel
    const epsPanel = document.getElementById('epsilon-crime-stats');
    if (epsPanel) {
        epsPanel.style.display = 'block';
        document.getElementById('stat-bound-crimes').textContent = displayStats.boundaryCrimes.toLocaleString();
        document.getElementById('stat-inter-crimes').textContent = displayStats.interiorCrimes.toLocaleString();

        const boundBlockPct = summary.totalBlocks ? Math.round((summary.sharpBlockCount / summary.totalBlocks) * 100) : 0;
        const boundCrimePct = displayStats.totalCrimes ? Math.round((displayStats.boundaryCrimes / displayStats.totalCrimes) * 100) : 0;

        const epsSummary = document.getElementById('stat-eps-summary');
        if (epsSummary) {
            epsSummary.innerHTML = `Boundaries (>ε) make up <b>${boundBlockPct}%</b> of blocks but contain <b>${boundCrimePct}%</b> of selected crimes.`;
        }
    }
}



/**
 * drawSharpnessLayer()
 * Renders the ABSTRACT topological boundary edges — the connections between
 * pairs of spatially adjacent city blocks that were identified as
 * socioeconomically contrasting (sharp) by the PH pipeline.
 *
 * Design rationale:
 *   • These edges are mathematical constructs (they connect block centroids),
 *     not physical streets. They must not dominate the map visually.
 *   • Color = neutral gray, very low opacity, thin dashed stroke.
 *   • Thickness encodes sharpness weight w so the sharpest connections are
 *     slightly more visible, but still clearly secondary to the street layer.
 *   • No triangle fills, no interior edges, no decorative colors.
 *
 * What each line means for reviewers:
 *   A line between two block centroids = those two blocks were identified
 *   by the PH filtration as forming a sharp socioeconomic discontinuity
 *   (w ≥ ε₂).  The line itself crosses the boundary between them.
 */
function drawSharpnessLayer() {
    if (phState.mapLayers.sharpness) map.removeLayer(phState.mapLayers.sharpness);
    if (!phState.adjacency) return;

    const isDark = (currentMapMode === 'dark');
    const group = L.featureGroup();

    // Only show SHARP boundary edges (the PH-identified contrasting pairs)
    const boundaryEdges = phState.adjacency.boundary_edges || [];
    if (!boundaryEdges.length) {
        phState.mapLayers.sharpness = group;
        if (document.getElementById('layer-sharpness')?.checked) group.addTo(map);
        return;
    }

    const maxW = Math.max(...boundaryEdges.map(e => e.w), 1e-9);

    // ── 1. Interior / Non-sharp edges: faint gray background network ────────────
    const interiorEdges = phState.adjacency.interior_edges || [];
    const interiorColor = isDark ? 'rgba(148,163,184,0.15)' : 'rgba(71,85,105,0.12)';
    interiorEdges.forEach(edge => {
        L.polyline([[edge.ay, edge.ax], [edge.by, edge.bx]], {
            color: interiorColor, weight: 0.8, opacity: 1, interactive: false
        }).addTo(group);
    });

    // ── 2. Sharp Boundary Edges ───────────────────────────────────────────────
    // Crime-count color scale (same as drawSharpStreets)
    // Color answers: "how many [selected] crimes occurred near this PH boundary?"
    function crimeColorEdge(count) {
        if (count === 0) return isDark ? 'rgba(148,163,184,0.25)' : 'rgba(100,116,139,0.20)';
        if (count <= 2) return '#4ade80';   // green  — low
        if (count <= 6) return '#facc15';   // amber  — moderate
        if (count <= 14) return '#f97316';   // orange — high
        return '#ef4444';   // red    — very high
    }

    // Build per-edge crime counts filtered by selected crime types
    const edgeCrimeLookup = new Map();
    const selectedCrimeTypes = phState.selectedCrimeTypes || [];
    const filterByCrimeType = selectedCrimeTypes.length > 0;
    (phState.boundaryCrimes?.edge_crime_counts || []).forEach(ec => {
        let count = 0;
        if (filterByCrimeType) {
            const ct = ec.crime_types || {};
            selectedCrimeTypes.forEach(t => { count += ct[t] || 0; });
        } else {
            count = ec.crime_count || 0;
        }
        edgeCrimeLookup.set(`${ec.a}-${ec.b}`, count);
        edgeCrimeLookup.set(`${ec.b}-${ec.a}`, count);
    });

    const crimeLabel = filterByCrimeType ? selectedCrimeTypes.join(', ') : 'All crime types';

    boundaryEdges.forEach(edge => {
        const norm = edge.w / maxW;
        const edgeCrime = edgeCrimeLookup.get(`${edge.a}-${edge.b}`) ?? 0;
        const color = crimeColorEdge(edgeCrime);
        const wt = 0.8 + norm * 1.2;   // 0.8–2px — thinner than street segments
        const opacity = edgeCrime === 0 ? 0.30 : 0.70;

        const line = L.polyline([[edge.ay, edge.ax], [edge.by, edge.bx]], {
            color, weight: wt, opacity, interactive: true
        });

        const dv = edge.dv !== undefined ? (edge.dv * 100).toFixed(1) + '%' : 'n/a';
        const da = edge.da !== undefined ? (edge.da * 100).toFixed(1) + '%' : 'n/a';
        const dz = edge.dz !== undefined ? (edge.dz * 100).toFixed(1) + '%' : 'n/a';

        const tip = `
            <div style="font-family:'Outfit',sans-serif;min-width:230px;padding:4px">
              <div style="font-size:0.62rem;font-weight:700;letter-spacing:1px;
                          color:#64748b;margin-bottom:5px">SHARP BOUNDARY EDGE (PH)</div>
              <div style="display:flex;align-items:center;gap:8px;
                          background:rgba(0,0,0,0.25);border-radius:6px;
                          padding:7px;margin-bottom:8px">
                <div style="width:10px;height:10px;border-radius:50%;
                             background:${color};flex-shrink:0"></div>
                <div>
                  <div style="font-size:1rem;font-weight:700;color:${color}">${edgeCrime}</div>
                  <div style="font-size:0.62rem;color:#94a3b8">${crimeLabel}</div>
                </div>
                <div style="margin-left:auto;font-size:0.75rem;font-weight:600;color:#a78bfa">
                  w = ${edge.w.toFixed(3)}
                </div>
              </div>
              <div style="font-size:0.68rem;color:#64748b;margin-bottom:6px">
                w = √(α·Δv² + β·Δa² + γ·Δz²) — socioeconomic discontinuity
              </div>
              <table style="font-size:0.7rem;width:100%;border-collapse:collapse">
                <tr><td style="color:#94a3b8;padding-right:8px">Value contribution</td>
                    <td style="text-align:right;font-weight:600">${dv}</td></tr>
                <tr><td style="color:#94a3b8">Age contribution</td>
                    <td style="text-align:right;font-weight:600">${da}</td></tr>
                <tr><td style="color:#94a3b8">Zoning contribution</td>
                    <td style="text-align:right;font-weight:600">${dz}</td></tr>
              </table>
            </div>`;
        line.bindTooltip(tip, { maxWidth: 270, className: 'ph-tooltip' });
        line.on({
            mouseover: e => e.target.setStyle({ weight: wt + 1.5, opacity: 1 }),
            mouseout: e => e.target.setStyle({ weight: wt, opacity })
        });
        line.addTo(group);
    });

    phState.mapLayers.sharpness = group;
    if (document.getElementById('layer-sharpness')?.checked) group.addTo(map);
}



/**
 * drawSharpStreets()
 * Renders the PHYSICAL STREET SEGMENTS that run along PH-identified sharp
 * socioeconomic boundaries.  These are the primary result layer.
 *
 * Color encoding (crime count within 50m buffer):
 *   0 crimes      : #94a3b8  slate    — no signal
 *   1–2 crimes    : #4ade80  green    — low
 *   3–6 crimes    : #facc15  amber    — moderate
 *   7–14 crimes   : #f97316  orange   — high
 *   15+ crimes    : #ef4444  red      — very high
 */
function drawSharpStreets() {
    if (phState.mapLayers.sharpStreets) map.removeLayer(phState.mapLayers.sharpStreets);
    if (!phState.sharpStreets?.features) return;
    if (!phState.adjacency?.boundary_edges) return;

    const boundaryEdges = phState.adjacency.boundary_edges;
    const allEdges = phState.adjacency.edges || [];

    // ── Crime-count color scale ────────────────────────────────────────────
    function crimeColor(count) {
        if (count === 0) return '#cbd5e1';  // slate  — no crimes recorded
        if (count <= 2) return '#4ade80';  // green  — low
        if (count <= 6) return '#facc15';  // amber  — moderate
        if (count <= 14) return '#f97316';  // orange — high
        return '#ef4444';  // red    — very high
    }
    function crimeWeight(count, maxC) {
        const norm = Math.min(count / Math.max(maxC, 1), 1);
        return 1.5 + norm * 3.0;   // 1.5–4.5 px
    }

    // Segments of boundary edges (centroid-to-centroid paths between blocks)
    const boundaryEdgeSegments = boundaryEdges.map(e => ({
        x1: e.ax, y1: e.ay, x2: e.bx, y2: e.by,
        sharpness: e.w
    }));

    const features = phState.sharpStreets.features;
    const selectedCrimeTypes = phState.selectedCrimeTypes || [];
    const filterByCrimeType = selectedCrimeTypes.length > 0;

    const PROXIMITY_THRESHOLD = 0.0005;  // ≈ 50m at 49°N — same as buffer radius

    // Filter: keep only streets physically close to a boundary edge
    const filtered = features.filter(f => {
        const coords = f.geometry?.coordinates;
        if (!coords || coords.length < 2) return false;
        for (let i = 0; i < coords.length - 1; i++) {
            for (const be of boundaryEdgeSegments) {
                if (lineToLineDistance(
                    coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1],
                    be.x1, be.y1, be.x2, be.y2
                ) < PROXIMITY_THRESHOLD) return true;
            }
        }
        return false;
    });

    // Compute effective crime count per feature (respects crime type filter)
    const withCounts = filtered.map(f => {
        const props = f.properties;
        let count = 0;
        if (filterByCrimeType) {
            const ct = props.crime_types || {};
            selectedCrimeTypes.forEach(t => { count += ct[t] || 0; });
        } else {
            count = props.crime_count || 0;
        }
        return { feature: f, count };
    }).filter(d => !filterByCrimeType || d.count > 0);

    // Sort descending by crime count so high-crime streets render on top
    withCounts.sort((a, b) => b.count - a.count);
    const top = withCounts.slice(0, 1500);

    const maxCrime = top.length ? top[0].count : 1;
    const group = L.featureGroup();

    top.forEach(({ feature, count }, idx) => {
        const props = feature.properties;
        const coords = feature.geometry.coordinates;
        const latlngs = coords.map(c => [c[1], c[0]]);

        const color = crimeColor(count);
        const weight = crimeWeight(count, maxCrime);

        // Top-10 highest-crime streets get a soft glow (extra shadow layer)
        if (idx < 10 && count > 0) {
            L.polyline(latlngs, {
                color, weight: weight + 4, opacity: 0.15, interactive: false
            }).addTo(group);
        }

        const line = L.polyline(latlngs, {
            color,
            weight,
            opacity: count === 0 ? 0.35 : 0.88,
            interactive: true
        });

        // ── Tooltip ────────────────────────────────────────────────────────
        const topCrimes = Object.entries(props.crime_types || {})
            .sort((a, b) => b[1] - a[1]).slice(0, 3);

        const crimeRows = topCrimes.map(([type, n]) =>
            `<tr>
               <td style="color:#94a3b8;padding-right:8px">${type}</td>
               <td style="font-weight:600;text-align:right">${n}</td>
             </tr>`
        ).join('');

        const colorLabel =
            count === 0 ? 'No crimes recorded' :
                count <= 2 ? 'Low crime' :
                    count <= 6 ? 'Moderate crime' :
                        count <= 14 ? 'High crime' :
                            'Very high crime';

        const tip = `
            <div style="font-family:'Outfit',sans-serif;min-width:230px;padding:4px">
              <div style="font-size:0.62rem;font-weight:700;letter-spacing:1px;
                          color:#64748b;margin-bottom:5px">SHARP BOUNDARY STREET</div>
              <div style="font-size:0.92rem;font-weight:700;margin-bottom:2px">
                ${props.hblock || 'Unknown block'}
              </div>
              <div style="font-size:0.72rem;color:#64748b;margin-bottom:8px">
                ${props.street_type || ''} &nbsp;·&nbsp; sharpness w = ${(props.sharpness || 0).toFixed(3)}
              </div>
              <div style="display:flex;align-items:center;gap:8px;
                          background:rgba(0,0,0,0.3);border-radius:6px;padding:8px;margin-bottom:8px">
                <div style="width:12px;height:12px;border-radius:50%;
                             background:${color};flex-shrink:0"></div>
                <div>
                  <div style="font-size:1.1rem;font-weight:800;color:${color}">${count}</div>
                  <div style="font-size:0.65rem;color:#94a3b8">crimes within 50m buffer</div>
                </div>
                <div style="margin-left:auto;font-size:0.7rem;
                             color:${color};font-weight:600">${colorLabel}</div>
              </div>
              ${topCrimes.length ? `
                <table style="font-size:0.7rem;width:100%;border-collapse:collapse">
                  ${crimeRows}
                </table>` : ''}
            </div>`;

        line.bindTooltip(tip, { maxWidth: 280, className: 'ph-tooltip', sticky: true });

        line.on({
            mouseover: e => e.target.setStyle({ weight: weight + 2, opacity: 1 }),
            mouseout: e => e.target.setStyle({ weight, opacity: count === 0 ? 0.35 : 0.88 })
        });

        group.addLayer(line);
    });

    phState.mapLayers.sharpStreets = group;
    if (document.getElementById('layer-sharp-streets').checked) group.addTo(map);

    // Update Street Segment Display
    const streetTotalDisplay = document.getElementById('street-total-display');
    const streetSharpDisplay = document.getElementById('street-sharp-display');
    if (streetTotalDisplay) streetTotalDisplay.textContent = features.length.toLocaleString();
    if (streetSharpDisplay) streetSharpDisplay.textContent = top.length.toLocaleString();

    console.log(`[Sharp Streets] Drawn ${top.length} segments. Max crimes on one segment: ${maxCrime}`);
}



function drawCrimeHeat() {

    if (phState.mapLayers.crimeHeat) map.removeLayer(phState.mapLayers.crimeHeat);
    if (!phState.crimes?.features) return;

    const points = phState.crimes.features
        .filter(feature => feature.geometry?.coordinates)
        .map(feature => [feature.geometry.coordinates[1], feature.geometry.coordinates[0], 0.5]);

    phState.mapLayers.crimeHeat = L.heatLayer(points, {
        radius: 18,
        blur: 22,
        maxZoom: 16,
        gradient: { 0.2: '#1e293b', 0.4: '#3b82f6', 0.6: '#a855f7', 0.8: '#e11d48', 1: '#ef4444' },
    });

    if (document.getElementById('layer-crime-heat').checked) {
        phState.mapLayers.crimeHeat.addTo(map);
    }
}

function drawBlocks() {
    if (phState.mapLayers.blocks) map.removeLayer(phState.mapLayers.blocks);
    if (!phState.blocks) return;

    const analysis = computeActiveAnalysis();
    const sharpBlocks = analysis?.activeSharpBlockIds || new Set();

    phState.mapLayers.blocks = L.geoJSON(phState.blocks, {
        style: feature => {
            const blockId = feature.properties?.block_id;
            const isSharp = sharpBlocks.has(blockId);
            return {
                color: isSharp ? '#e11d48' : '#cbd5e1',
                weight: isSharp ? 1.5 : 0.5,
                opacity: isSharp ? 0.7 : 0.3,
                fillColor: isSharp ? '#e11d48' : '#1e293b',
                fillOpacity: isSharp ? 0.1 : 0.02,
            };
        },
        onEachFeature: (feature, layer) => {
            const props = feature.properties || {};
            layer.bindTooltip(
                `<div style="font-family:Outfit; max-width:220px;">
                    <div style="background:#334155; color:white; padding:3px 8px; border-radius:4px; margin-bottom:6px; font-size:0.75rem; display:inline-block;">
                        CITY BLOCK (Area)
                    </div>
                    <div style="font-size:1rem; font-weight:600; margin-bottom:4px;">Block #${props.block_id}</div>
                    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; font-size:0.85rem; margin:8px 0;">
                        <div style="background:rgba(255,255,255,0.05); padding:6px; border-radius:4px;">
                            <div style="color:#94a3b8; font-size:0.7rem;">Avg Value</div>
                            <div style="color:#e2e8f0;">$${((props.avg_value || 0) / 1e6).toFixed(2)}M</div>
                        </div>
                        <div style="background:rgba(255,255,255,0.05); padding:6px; border-radius:4px;">
                            <div style="color:#94a3b8; font-size:0.7rem;">Avg Age</div>
                            <div style="color:#e2e8f0;">${Math.round(props.avg_age || 0)} yrs</div>
                        </div>
                    </div>
                    <div style="background:rgba(239,68,68,0.1); border:1px solid rgba(239,68,68,0.3); padding:8px; border-radius:4px; margin-top:6px;">
                        <div style="color:#94a3b8; font-size:0.75rem;">Crimes in this block area</div>
                        <div style="color:#ef4444; font-size:1.2rem; font-weight:700;">${props.crime_count || 0}</div>
                    </div>
                    <div style="font-size:0.7rem; color:#64748b; margin-top:6px; font-style:italic;">
                        Crimes are counted within this block's polygon area
                    </div>
                </div>`,
                {
                    sticky: true,
                    className: 'block-tooltip'
                }
            );
        },
    });

    if (document.getElementById('layer-blocks').checked) phState.mapLayers.blocks.addTo(map);
    drawCentroids();
}

function drawCentroids() {
    if (phState.mapLayers.centroids) map.removeLayer(phState.mapLayers.centroids);
    if (!phState.blocks || !phState.blocks.features || !phState.adjacency || !phState.adjacency.edges) return;

    // Build a true centroid lookup from the pre-calculated adjacency edges (ax, ay, bx, by)
    const centroidLookup = new Map();
    phState.adjacency.edges.forEach(edge => {
        if (!centroidLookup.has(edge.a)) centroidLookup.set(edge.a, { cx: edge.ax, cy: edge.ay });
        if (!centroidLookup.has(edge.b)) centroidLookup.set(edge.b, { cx: edge.bx, cy: edge.by });
    });

    const markers = [];
    phState.blocks.features.forEach(feature => {
        const props = feature.properties || {};

        let cx = props.cx;
        let cy = props.cy;

        if (cx === undefined || cy === undefined) {
            const exactCentroid = centroidLookup.get(props.block_id);
            if (exactCentroid) {
                cx = exactCentroid.cx;
                cy = exactCentroid.cy;
            } else {
                // Fallback only if block has no edges
                let coords = feature.geometry.coordinates[0];
                if (Array.isArray(coords[0][0])) coords = coords[0];
                let sumX = 0, sumY = 0;
                coords.forEach(pt => { sumX += pt[0]; sumY += pt[1]; });
                cx = sumX / coords.length;
                cy = sumY / coords.length;
            }
        }

        if (!cx || !cy) return;

        const valLabel = props.avg_value ? `$${(props.avg_value / 1e6).toFixed(2)}M` : 'N/A';
        const ageLabel = props.avg_age ? `${Math.round(props.avg_age)} yrs` : 'N/A';
        const propCount = props.property_count || 0;

        let zoningHtml = '<div style="color:#94a3b8; font-style:italic;">No zoning data</div>';
        if (props.zoning_percentages && Object.keys(props.zoning_percentages).length > 0) {
            zoningHtml = Object.entries(props.zoning_percentages)
                .filter(([cat, pct]) => pct > 0)
                .sort((a, b) => b[1] - a[1])
                .map(([cat, pct]) => `<div style="display:flex; justify-content:space-between; border-bottom:1px solid rgba(255,255,255,0.05); padding:3px 0;"><span>${cat}</span><span style="font-weight:600; color:#38bdf8;">${pct}%</span></div>`)
                .join('');
        }

        const marker = L.circleMarker([cy, cx], {
            radius: 1.0,
            fillColor: currentMapMode === 'light' ? '#1e293b' : '#cbd5e1',
            color: 'transparent',
            weight: 0,
            fillOpacity: 0.6
        });

        marker.bindPopup(
            `<div style="font-family:Outfit; min-width:220px;">
                <div style="background:#0284c7; color:white; padding:3px 8px; border-radius:4px; margin-bottom:6px; font-size:0.75rem; display:inline-block; letter-spacing:0.5px;">
                    BLOCK CENTROID (Simplex Node)
                </div>
                <div style="font-size:1rem; font-weight:600; margin-bottom:6px; color:#1e293b;">Block #${props.block_id}</div>
                
                <div style="background:rgba(0,0,0,0.05); padding:8px; border-radius:6px; margin-bottom:8px;">
                    <div style="display:flex; justify-content:space-between; margin-bottom:4px; color:#334155; font-size:0.85rem;"><span style="color:#64748b;">Avg Value:</span> <span style="font-weight:600;">${valLabel}</span></div>
                    <div style="display:flex; justify-content:space-between; color:#334155; font-size:0.85rem;"><span style="color:#64748b;">Avg Age:</span> <span style="font-weight:600;">${ageLabel}</span></div>
                </div>

                <div style="background:rgba(56, 189, 248, 0.1); border:1px solid rgba(56, 189, 248, 0.3); padding:8px; border-radius:6px; margin-bottom:8px;">
                    <div style="color:#0284c7; font-size:0.7rem; font-weight:700; margin-bottom:6px; text-transform:uppercase; letter-spacing:0.5px;">Zoning Breakdown (Area %)</div>
                    <div style="font-size:0.8rem; color:#0f172a;">
                        ${zoningHtml.replace(/rgba\(255,255,255,0\.05\)/g, 'rgba(0,0,0,0.05)').replace(/color:#f1f5f9/g, 'color:#0f172a')}
                    </div>
                </div>

                <div style="font-size:0.75rem; color:#64748b; text-align:center; background:#f1f5f9; border-radius:4px; padding:6px; margin-bottom:4px;">
                    Matched <b>${propCount}</b> properties
                </div>
            </div>`,
            {
                className: 'block-popup'
            }
        );

        markers.push(marker);
    });

    phState.mapLayers.centroids = L.layerGroup(markers);
    const cb = document.getElementById('layer-centroids');
    if (cb && cb.checked) {
        phState.mapLayers.centroids.addTo(map);
    }
}

function refreshOpenModal() {
    if (!phState.activeModal) return;
    const modal = document.getElementById('analysis-modal');
    if (modal.style.display === 'none') return;
    const type = phState.activeModal;
    const config = getModalConfig(type);
    document.getElementById('analysis-modal-title').textContent = config.title;
    document.getElementById('analysis-modal-body').innerHTML = config.html;
    requestAnimationFrame(() => {
        const body = document.getElementById('analysis-modal-body');
        body.querySelectorAll('canvas[data-chart]').forEach(renderChart);
        // Plotly-based modals need a slight delay for DOM to be ready
        if (type === 'spatial-crime-correlation') setTimeout(renderSpatialCorrelationPlots, 50);
        if (type === 'edge-crime-correlation') setTimeout(renderEdgeCrimeCorrelation, 50);
        if (type === 'weights-optimization') setTimeout(renderWeightsOptimizationPlots, 50);
    });
}

function refreshSharpnessViews() {
    computeActiveAnalysis();
    renderSummary();
    drawSharpnessLayer();
    drawBlocks();
    drawSharpStreets();  // Sharp streets also depend on sharpness threshold
    refreshOpenModal();
}

function refreshPersistenceViews() {
    renderSummary();
    refreshOpenModal();
}

async function recomputeTopology() {
    console.log('[DEBUG] recomputeTopology called');
    const eps1Slider = document.getElementById('epsilon1-threshold');
    const eps2Slider = document.getElementById('epsilon2-threshold');
    const alphaSlider = document.getElementById('alpha-slider');
    const betaSlider = document.getElementById('beta-slider');
    const gammaSlider = document.getElementById('gamma-slider');
    const btn = document.getElementById('recompute-ph-btn');
    if (!eps1Slider || !btn) {
        console.log('[DEBUG] Missing elements - eps1Slider:', !!eps1Slider, 'btn:', !!btn);
        return;
    }

    const eps1_m = eps1Slider ? parseFloat(eps1Slider.value) : 0;
    const eps2_raw = eps2Slider ? parseFloat(eps2Slider.value) : 0;
    const isManual = eps2State === 'MANUAL';
    
    const alpha = alphaSlider ? parseFloat(alphaSlider.value) : 0.333;
    const beta = betaSlider ? parseFloat(betaSlider.value) : 0.333;
    const gamma = gammaSlider ? parseFloat(gammaSlider.value) : 0.334;

    const payload = {
        epsilon1_m: eps1_m,
        alpha: alpha,
        beta: beta,
        gamma: gamma,
        crime_types: window.getSelectedCrimeTypes ? window.getSelectedCrimeTypes() : BE_CRIME_TYPES
    };
    
    if (isManual) {
        payload.override_eps2 = eps2_raw;
    } else {
        payload.epsilon2_threshold = 0.75; // Ignored effectively by backend for auto, but keep format
    }

    console.log('[DEBUG] Sending request - payload:', payload);

    btn.disabled = true;
    const originalText = btn.innerHTML;
    btn.innerHTML = 'Computing... <div class="spinner" style="width:14px;height:14px;border-width:2px;display:inline-block;vertical-align:middle;margin-left:8px;"></div>';

    try {
        const serverUrl = 'http://127.0.0.1:8001';
        console.log('[DEBUG] Making fetch request to:', serverUrl);
        const res = await fetch(serverUrl + '/api/compute-ph', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        console.log('[DEBUG] Response status:', res.status);

        if (!res.ok) throw new Error(`Server returned ${res.status}`);

        const data = await res.json();

        // Update loaded state with new data
        phState.adjacency = data.adjacency;
        phState.persistence = data.persistence;

        // Store selected crime types
        phState.selectedCrimeTypes = window.getSelectedCrimeTypes ? window.getSelectedCrimeTypes() : BE_CRIME_TYPES;

        // Clear caches and force recalculation of derived data
        phState.analysisCache.clear();
        buildDerivedAnalysis();

        // Update display with new stats
        updateStatsDisplay();
        updateCrimeStatsDisplay();

        // Log after recompute to confirm
        const adj = phState.adjacency;
        console.log('=== RECOMPUTE COMPLETE ===');
        console.log('Epsilon:', adj?.stats?.epsilon1_m, 'm');
        console.log('Boundary edges:', adj?.boundary_edges?.length || 0);
        console.log('Using these edges for crime assignment');

        // Re-render everything
        refreshSharpnessViews();
        // Auto-refresh any open modal so it reflects new ε values
        refreshOpenModal();

    } catch (err) {
        console.error('Failed to recompute topology:', err);
        alert('Error: ' + err.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
}

// Make function globally accessible
window.recomputeTopology = recomputeTopology;
console.log('[DEBUG] window.recomputeTopology set');

function updateStatsDisplay() {
    const stats = phState.adjacency?.stats || {};
    const eps1Display = document.getElementById('eps1-stats-display');
    const eps2Display = document.getElementById('eps2-stats-display');
    const outlierDisplay = document.getElementById('outlier-count-display');
    const edgeCountDisplay = document.getElementById('edge-count-display'); // Kept for backwards compat if needed, but we don't update it here.
    const boundaryCountDisplay = document.getElementById('boundary-count-display');

    if (eps1Display) eps1Display.textContent = stats.epsilon1_m + 'm';
    
    if (stats.epsilon2_value !== undefined) {
        // Sync Slider UI to state
        const slider = document.getElementById('epsilon2-threshold');
        const minL = document.getElementById('eps2-min-label');
        const maxL = document.getElementById('eps2-max-label');
        const headerDisp = document.getElementById('eps2-display');
        const resetBtn = document.getElementById('eps2-reset-btn');
        const icon = document.getElementById('eps2-lock-icon');
        const warn = document.getElementById('eps2-state-warning');
        
        if (slider) {
            slider.min = stats.min_meaningful || 0;
            slider.max = stats.max_dist || 1;
            
            if (minL) minL.textContent = stats.min_meaningful?.toFixed(3) || '0';
            if (maxL) maxL.textContent = stats.max_dist?.toFixed(3) || '1';
            
            if (eps2State === 'AUTO') {
                slider.value = stats.auto_epsilon2;
                eps2Display.textContent = 'Auto (' + stats.auto_epsilon2?.toFixed(3) + ')';
                if (headerDisp) headerDisp.textContent = 'Auto';
                if (resetBtn) resetBtn.style.display = 'none';
                if (icon) icon.textContent = '🔒';
                if (warn) {
                    warn.textContent = 'Auto-derived from H0 persistence gap.';
                    warn.style.color = '#c084fc';
                }
            } else {
                // MANUAL
                slider.value = stats.epsilon2_value;
                eps2Display.textContent = 'Manual (' + stats.epsilon2_value?.toFixed(3) + ')';
                if (headerDisp) headerDisp.textContent = 'Manual';
                if (resetBtn) resetBtn.style.display = 'block';
                if (icon) icon.textContent = '✏️';
                if (warn) {
                    warn.textContent = 'Manual mode — primary results use auto-derived threshold';
                    warn.style.color = '#f59e0b';
                }
            }
        }
        
        if (outlierDisplay) outlierDisplay.textContent = stats.trim_count || 0;
    }
}

function updateCrimeStatsDisplay() {
    // Get fresh data from current adjacency state
    const adjacency = phState.adjacency;
    const selectedTypes = phState.selectedCrimeTypes || [];

    if (!adjacency) {
        console.log('[DEBUG] No adjacency data');
        return;
    }

    const boundaryEdges = adjacency.boundary_edges || [];
    const allEdges = adjacency.edges || [];

    console.log('[DEBUG] updateCrimeStatsDisplay START:');
    console.log('  - boundaryEdges:', boundaryEdges.length);
    console.log('  - allEdges:', allEdges.length);
    console.log('  - epsilon from stats:', adjacency.stats?.epsilon1_m);
    console.log('  - selectedTypes:', selectedTypes);

    if (!phState.crimes?.features) {
        console.log('[DEBUG] No crimes data - returning early');
        return;
    }
    if (boundaryEdges.length === 0) {
        console.log('[DEBUG] No boundary edges yet');
    }

    // Build spatial index for boundary edges
    const boundaryEdgeSegments = boundaryEdges.map(e => ({
        x1: e.ax, y1: e.ay,
        x2: e.bx, y2: e.by,
        sharpness: e.w
    }));

    const PROXIMITY_THRESHOLD = 0.0005; // ~50m

    // Count crimes by type and location (street-based)
    let boundaryCrimes = 0;
    let interiorCrimes = 0;

    phState.crimes.features.forEach(feature => {
        const crimeType = feature.properties?.TYPE;
        if (!selectedTypes.includes(crimeType)) return;

        const coords = feature.geometry?.coordinates;
        if (!coords) return;

        // Check if crime location is near any boundary edge
        let minDistToBoundary = Infinity;

        for (const be of boundaryEdgeSegments) {
            // Crime is a point, check distance to boundary edge segment
            const dist = pointToSegmentDistance(coords[0], coords[1], be.x1, be.y1, be.x2, be.y2);
            if (dist < minDistToBoundary) {
                minDistToBoundary = dist;
            }
        }

        if (minDistToBoundary < PROXIMITY_THRESHOLD) {
            boundaryCrimes++;
        } else {
            interiorCrimes++;
        }
    });

    console.log('[DEBUG] Street-based crime counts - boundary:', boundaryCrimes, 'interior:', interiorCrimes);

    const totalCrimes = boundaryCrimes + interiorCrimes;
    const boundaryPct = totalCrimes > 0 ? Math.round((boundaryCrimes / totalCrimes) * 100) : 0;

    // Update UI
    const boundCrimesEl = document.getElementById('stat-bound-crimes');
    const interCrimesEl = document.getElementById('stat-inter-crimes');
    const summaryEl = document.getElementById('stat-eps-summary');

    if (boundCrimesEl) boundCrimesEl.textContent = boundaryCrimes.toLocaleString();
    if (interCrimesEl) interCrimesEl.textContent = interiorCrimes.toLocaleString();
    if (summaryEl) {
        summaryEl.innerHTML = `Boundary: <b>${boundaryPct}%</b> of ${totalCrimes.toLocaleString()} selected crimes`;
    }
}

function setupWeightSliders() {
    const sAlpha = document.getElementById('alpha-slider');
    const sBeta = document.getElementById('beta-slider');
    const sGamma = document.getElementById('gamma-slider');
    const dAlpha = document.getElementById('alpha-thresh-display');
    const dBeta = document.getElementById('beta-thresh-display');
    const dGamma = document.getElementById('gamma-thresh-display');
    const dSum = document.getElementById('weight-sum-display');

    if (!sAlpha || !sBeta || !sGamma) return;

    function updateDisplays() {
        dAlpha.textContent = parseFloat(sAlpha.value).toFixed(2);
        dBeta.textContent = parseFloat(sBeta.value).toFixed(2);
        dGamma.textContent = parseFloat(sGamma.value).toFixed(2);
        const sum = parseFloat(sAlpha.value) + parseFloat(sBeta.value) + parseFloat(sGamma.value);
        if (dSum) dSum.textContent = Math.abs(1.0 - sum) < 0.02 ? '1.0' : sum.toFixed(2);
    }

    const sliders = [sAlpha, sBeta, sGamma];
    let isUpdating = false;

    sliders.forEach(slider => {
        slider.addEventListener('input', (e) => {
            if (isUpdating) return;
            isUpdating = true;

            const changed = e.target;
            const others = sliders.filter(s => s !== changed);
            let val = parseFloat(changed.value);

            if (val > 1.0) { val = 1.0; }
            if (val < 0.0) { val = 0.0; }
            changed.value = val;

            const remainder = 1.0 - val;
            const currentSumOthers = parseFloat(others[0].value) + parseFloat(others[1].value);

            if (currentSumOthers < 0.001) {
                const half = remainder / 2.0;
                others[0].value = half.toFixed(3);
                others[1].value = half.toFixed(3);
            } else {
                const prop0 = parseFloat(others[0].value) / currentSumOthers;
                const prop1 = parseFloat(others[1].value) / currentSumOthers;
                others[0].value = (remainder * prop0).toFixed(3);
                others[1].value = (remainder * prop1).toFixed(3);
            }

            updateDisplays();
            isUpdating = false;
        });
    });
}

function setupWeightPresetButtons() {
    const presetBtns = document.querySelectorAll('.weight-preset-btn');
    if (!presetBtns.length) return;

    presetBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const alphaInput = document.getElementById('alpha-slider');
            const betaInput  = document.getElementById('beta-slider');
            const gammaInput = document.getElementById('gamma-slider');
            if (alphaInput) alphaInput.value = btn.dataset.alpha;
            if (betaInput)  betaInput.value  = btn.dataset.beta;
            if (gammaInput) gammaInput.value = btn.dataset.gamma;

            presetBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            recomputeTopology();
        });
    });
}

function setupControls() {
    setupWeightPresetButtons();
    setupWeightSliders();

    const toggles = [
        { id: 'layer-sharpness', key: 'sharpness', draw: drawSharpnessLayer },
        { id: 'layer-crime-heat', key: 'crimeHeat', draw: drawCrimeHeat },
        { id: 'layer-blocks', key: 'blocks', draw: drawBlocks },
        { id: 'layer-centroids', key: 'centroids', draw: drawCentroids },
        { id: 'layer-sharp-streets', key: 'sharpStreets', draw: drawSharpStreets },
    ];

    toggles.forEach(({ id, key, draw }) => {
        const el = document.getElementById(id);
        if (!el) return;
        if (!phState.mapLayers[key]) {
            try { draw(); } catch (err) { console.warn(`[PH] draw ${key} failed:`, err); }
        }

        el.addEventListener('change', () => {
            if (!phState.mapLayers[key]) {
                try { draw(); } catch (err) { console.warn(`[PH] draw ${key} failed:`, err); }
            }
            if (el.checked && phState.mapLayers[key]) phState.mapLayers[key].addTo(map);
            if (!el.checked && phState.mapLayers[key]) map.removeLayer(phState.mapLayers[key]);
        });
    });

    const eps1Slider = document.getElementById('epsilon1-threshold');
    const eps1Display = document.getElementById('eps1-thresh-display');
    if (eps1Slider) {
        eps1Slider.addEventListener('input', () => {
            const val = parseInt(eps1Slider.value, 10);
            eps1Display.textContent = val === 0 ? 'Polygon Adjacency' : val + 'm';
        });
    }

    const eps2Slider = document.getElementById('epsilon2-threshold');
    const eps2ResetBtn = document.getElementById('eps2-reset-btn');
    if (eps2Slider) {
        eps2Slider.addEventListener('input', () => {
            eps2State = 'MANUAL';
            const stats = phState.adjacency?.stats || {};
            // Temporarily store manual value in stats payload for display consistency
            stats.epsilon2_value = parseFloat(eps2Slider.value);
            updateStatsDisplay();
        });
    }

    if (eps2ResetBtn) {
        eps2ResetBtn.addEventListener('click', () => {
            eps2State = 'AUTO';
            // Snap back visually immediately
            const stats = phState.adjacency?.stats || {};
            if (stats.auto_epsilon2 !== undefined) {
                stats.epsilon2_value = stats.auto_epsilon2;
            }
            updateStatsDisplay();
            // Recompute on backend to clear any manual override cache if necessary
            recomputeTopology();
        });
    }

    const recomputeBtn = document.getElementById('recompute-ph-btn');
    if (recomputeBtn) {
        console.log('[DEBUG] Adding click listener to recomputeBtn');
        recomputeBtn.addEventListener('click', () => {
            console.log('[DEBUG] Button clicked, calling recomputeTopology');
            recomputeTopology();
        });
    } else {
        console.log('[DEBUG] recomputeBtn not found');
    }

    const persSlider = document.getElementById('pers-filter');
    const persDisplay = document.getElementById('pers-filter-display');
    if (persSlider) {
        persSlider.addEventListener('input', () => {
            if (persDisplay) persDisplay.textContent = `p${persSlider.value}`;
            refreshPersistenceViews();
        });
    }

    // Dynamic Crime Filter Logic
    window.getSelectedCrimeTypes = function () {
        const checked = document.querySelector('input[name="crime-filter-radio"]:checked');
        if (!checked) return ['Break and Enter Residential/Other', 'Break and Enter Commercial']; // fallback

        if (checked.value === 'Break and Enter') {
            return ['Break and Enter Residential/Other', 'Break and Enter Commercial'];
        }
        return [checked.value];
    };
}

function populateCrimeRadios() {
    const container = document.getElementById('crime-type-radios');
    if (!container || !phState.crimes || !phState.crimes.features) return;

    // Extract unique types
    const types = new Set();
    phState.crimes.features.forEach(f => {
        if (f.properties && f.properties.TYPE) {
            types.add(f.properties.TYPE);
        }
    });

    // We want to combine B&E into one radio, and list the rest
    const typeList = Array.from(types).filter(t => !t.startsWith('Break and Enter'));
    typeList.sort();

    // The combined category
    const finalTypes = ['Break and Enter', ...typeList];

    container.innerHTML = '';

    finalTypes.forEach(type => {
        const isChecked = type === 'Break and Enter' ? 'checked' : '';
        const html = `
            <label style="display:flex;align-items:center;gap:6px;cursor:pointer;">
                <input type="radio" name="crime-filter-radio" value="${type}" ${isChecked} style="accent-color:#c084fc;">
                <span>${type}</span>
            </label>
        `;
        container.insertAdjacentHTML('beforeend', html);
    });

    // Attach listener to redraw map labels and stats on change
    const radios = container.querySelectorAll('input[type="radio"]');
    radios.forEach(radio => {
        radio.addEventListener('change', () => {
            // Recompute dynamic stats, update maps and open modal
            console.log("Crime filter changed to:", radio.value);

            // Only update visualizations that depend on crimes
            renderSummary();
            if (phState.mapLayers.blocks) {
                map.removeLayer(phState.mapLayers.blocks);
                drawBlocks(); // This will regenerate tooltips with the new crime type
            }

            // Refresh any open modal that depends on crime type selection
            refreshOpenModal();
        });
    });
}

/**
 * Returns an HTML banner showing the current ε₁ / ε₂ parameters.
 * @param {string} dataSource - 'live' | 'recompute'
 *   'live'      = always reflects the current slider values (Crime Stats, Graph Stats, Dendrogram)
 *   'recompute' = reflects the last Recompute PH run (PH Diagram, Betti, Barcode, Raster Info)
 */
function getEpsContextBanner(dataSource = 'live') {
    const adj = phState.adjacency;
    const stats = adj?.stats || {};
    const eps1 = stats.epsilon1_m ?? document.getElementById('epsilon1-threshold')?.value ?? '—';
    const eps2Display = stats.epsilon2_value != null
        ? `w ≥ ${stats.epsilon2_value.toFixed(3)}`
        : 'Auto';
    const eps2Mode = stats.is_manual_override ? 'Manual' : 'Auto (gap-derived)';
    const totalEdges = stats.total_edges != null ? stats.total_edges.toLocaleString() : '—';
    const boundaryEdges = adj?.boundary_edges?.length ?? stats.boundary_edges ?? '—';

    const isLive = dataSource === 'live';
    const badgeColor = isLive ? '#22c55e' : '#7c3aed';
    const badgeLabel = isLive ? '● Live' : '● Updated on Recompute PH';

    return `
        <div style="background:rgba(15,23,42,0.9);border:1px solid rgba(148,163,184,0.15);
                    border-radius:8px;padding:10px 14px;margin-bottom:14px;
                    display:flex;flex-wrap:wrap;gap:16px;align-items:center;">
            <div style="display:flex;flex-direction:column;gap:3px;flex:1;min-width:200px;">
                <div style="font-size:0.62rem;font-weight:700;letter-spacing:1px;color:#64748b;margin-bottom:2px;">
                    ACTIVE PARAMETERS
                </div>
                <div style="display:flex;gap:18px;flex-wrap:wrap;">
                    <div>
                        <span style="font-size:0.7rem;color:#94a3b8;">ε₁ Spatial Distance: </span>
                        <b style="color:#e2e8f0;">${eps1}m</b>
                    </div>
                    <div>
                        <span style="font-size:0.7rem;color:#94a3b8;">ε₂ Boundary Threshold: </span>
                        <b style="color:#e2e8f0;">${eps2Display} <span style="font-size:0.6rem;color:#94a3b8;">(${eps2Mode})</span></b>
                    </div>
                    <div>
                        <span style="font-size:0.7rem;color:#94a3b8;">Edges: </span>
                        <b style="color:#e2e8f0;">${totalEdges} total · <span style="color:#ef4444;">${boundaryEdges}</span> sharp</b>
                    </div>
                </div>
            </div>
            <div style="font-size:0.7rem;font-weight:600;color:${badgeColor};white-space:nowrap;">
                ${badgeLabel}
            </div>
        </div>`;
}

function getModalConfig(type) {

    if (type === 'persistence-diagram') {
        return { title: 'H₀ Persistence Distribution', html: buildPersistenceDiagramHTML() };
    }
    if (type === 'betti-curves') {
        return { title: 'Betti Curve — β₀(α) Connected Components', html: buildBettiCurvesHTML() };
    }
    if (type === 'barcode') {
        return { title: 'H₀ Persistence Barcode', html: buildBarcodeHTML() };
    }
    if (type === 'boundary-stats') {
        return { title: 'Boundary Crime Statistics', html: buildBoundaryStatsHTML() };
    }
    if (type === 'spatial-crime-correlation') {
        return { title: 'Crime vs. Sharpness — Scatter, Box & Quintile', html: buildSpatialCorrelationHTML() };
    }
    if (type === 'edge-crime-correlation') {
        return { title: 'Edge Sharpness vs. Crime (HUNDRED_BLOCK segments)', html: buildEdgeCrimeCorrelationHTML() };
    }
    if (type === 'weights-optimization') {
        return { title: 'Weight Sensitivity — Simplex Grid', html: buildWeightsOptimizationHTML() };
    }
    return { title: 'Unknown', html: '<p>Unknown panel.</p>' };
}

function openModal(type) {
    phState.activeModal = type;
    const config = getModalConfig(type);
    document.getElementById('analysis-modal-title').textContent = config.title;
    document.getElementById('analysis-modal-body').innerHTML = config.html;
    document.getElementById('analysis-modal').style.display = '';
    requestAnimationFrame(() => {
        const body = document.getElementById('analysis-modal-body');
        body.querySelectorAll('canvas[data-chart]').forEach(renderChart);
        if (type === 'spatial-crime-correlation') renderSpatialCorrelationPlots();
        if (type === 'edge-crime-correlation') renderEdgeCrimeCorrelation();
        if (type === 'weights-optimization') renderWeightsOptimizationPlots();
    });
}

function closeModal() {
    phState.activeModal = null;
    document.getElementById('analysis-modal').style.display = 'none';
}

function setupModals() {
    document.getElementById('analysis-modal-close').addEventListener('click', closeModal);
    document.getElementById('analysis-modal').addEventListener('click', event => {
        if (event.target === document.getElementById('analysis-modal')) closeModal();
    });
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape') closeModal();
    });

    // Per-modal Save PNG button
    document.getElementById('analysis-modal-save').addEventListener('click', () => {
        if (!phState.activeModal) return;
        const type = phState.activeModal;
        const body = document.getElementById('analysis-modal-body');

        // Export all canvas charts in the modal
        const canvases = body.querySelectorAll('canvas[data-chart]');
        canvases.forEach(canvas => {
            const chartType = canvas.dataset.chart;
            downloadCanvasAsPNG(canvas, `PH_${chartType}.png`);
        });

        // Export all Plotly charts in the modal
        const plotlyDivs = {
            'spatial-crime-correlation': ['plotly-scatter', 'plotly-boxplot', 'plotly-quintile'],
            'edge-crime-correlation': ['plotly-edge-scatter'],
            'weights-optimization': ['plotly-ternary', 'plotly-crime-comparison', 'plotly-ratio-comparison'],
        };
        const ids = plotlyDivs[type] || [];
        ids.forEach((id, idx) => {
            setTimeout(() => downloadPlotlyAsPNG(id, `PH_${id}`), idx * 400);
        });

        if (canvases.length === 0 && ids.length === 0) {
            // For HTML-only modals (boundary-stats), use html2canvas fallback or alert
            alert('This panel contains tables/text only. Use browser Print (Ctrl+P) to save as PDF.');
        }
    });

    document.querySelectorAll('.analysis-btn[data-modal]').forEach(button => {
        button.addEventListener('click', () => openModal(button.dataset.modal));
    });
}

function renderChart(canvas) {
    const type = canvas.dataset.chart;
    const ctx = canvas.getContext('2d');
    const W = canvas.width = canvas.clientWidth * 2;
    const H = canvas.height = canvas.clientHeight * 2;
    ctx.scale(2, 2);
    const w = W / 2;
    const h = H / 2;

    if (type === 'persistence-diagram') drawPersistenceDiagram(ctx, w, h);
    else if (type === 'betti-curves') drawBettiCurves(ctx, w, h);
    else if (type === 'barcode-h0') drawBarcode(ctx, w, h, 'H0');
    else if (type === 'barcode-h1') drawBarcode(ctx, w, h, 'H1');
    else if (type === 'persistence-landscape') drawPersistenceLandscape(ctx, w, h);
    else if (type === 'persistence-image') drawPersistenceImage(ctx, w, h);
    else if (type === 'euler-curve') drawEulerCurve(ctx, w, h);
}

function drawEmptyChart(ctx, w, h, message) {
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = '#cbd5e1';
    ctx.font = '14px Outfit';
    ctx.fillText(message, w / 2 - (message.length * 3.2), h / 2);
}

function drawPersistenceDiagram(ctx, w, h) {
    const persistence = phState.persistence;
    if (!persistence) { drawEmptyChart(ctx, w, h, 'No persistence data loaded.'); return; }

    const h0 = getFilteredDiagram('H0');
    if (!h0.length) {
        drawEmptyChart(ctx, w, h, 'No H₀ features pass the current persistence filter.');
        return;
    }

    const analysis = phState.activeAnalysis || computeActiveAnalysis();
    const eps2 = analysis?.thresholdValue ?? null;

    // In single-linkage (Union-Find), all births = 0, so death = persistence.
    // Show a histogram of death values to reveal the gap that determines ε₂.
    const deaths = h0.map(([, d]) => d);
    const maxDeath = Math.max(...deaths) * 1.08 || 1;

    // Find the largest gap within the H₀ death distribution to use as the
    // color split. The global ε₂ is based on raw edge weights and may fall
    // outside the range of H₀ deaths (all deaths could be above ε₂).
    // A gap-based local split produces a meaningful blue/red split within
    // the actual persistence histogram.
    const sortedDeaths = [...deaths].sort((a, b) => a - b);
    let localSplit = null;
    if (sortedDeaths.length >= 4) {
        let maxGap = -Infinity, gapIdx = -1;
        for (let i = 1; i < sortedDeaths.length; i++) {
            const gap = sortedDeaths[i] - sortedDeaths[i - 1];
            if (gap > maxGap) { maxGap = gap; gapIdx = i; }
        }
        if (gapIdx > 0) {
            localSplit = (sortedDeaths[gapIdx - 1] + sortedDeaths[gapIdx]) / 2;
        }
    }
    // Color threshold: use localSplit if available, fall back to eps2
    const colorThreshold = localSplit ?? eps2;

    const N_BINS = 35;
    const binWidth = maxDeath / N_BINS;
    const binCounts = new Array(N_BINS).fill(0);
    deaths.forEach(d => {
        const bin = Math.min(Math.floor(d / binWidth), N_BINS - 1);
        binCounts[bin]++;
    });
    const maxCount = Math.max(...binCounts, 1);

    const pad = { t: 56, r: 24, b: 56, l: 62 };
    const plotW = w - pad.l - pad.r;
    const plotH = h - pad.t - pad.b;

    const toX = v => pad.l + (v / maxDeath) * plotW;
    const toY = n => h - pad.b - (n / maxCount) * plotH;

    // Background
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, w, h);

    // Title
    ctx.fillStyle = '#1e293b';
    ctx.font = 'bold 13px Outfit';
    ctx.textAlign = 'center';
    ctx.fillText('H₀ Persistence Distribution — Sharpness Weight Histogram', w / 2, 24);

    // Subtitle
    ctx.fillStyle = '#64748b';
    ctx.font = '9px Outfit';
    ctx.fillText('Bars colored by the largest gap in H₀ deaths (local split). Orange dashed line = global ε₂ (auto-derived from persistence gap).', w / 2, 39);
    ctx.textAlign = 'left';

    // Grid lines
    ctx.strokeStyle = 'rgba(148,163,184,0.4)';
    ctx.lineWidth = 0.5;
    for (let i = 0; i <= 5; i++) {
        const n = maxCount * i / 5;
        const gy = toY(n);
        ctx.beginPath(); ctx.moveTo(pad.l, gy); ctx.lineTo(w - pad.r, gy); ctx.stroke();
    }
    for (let i = 0; i <= 5; i++) {
        const v = maxDeath * i / 5;
        const gx = toX(v);
        ctx.beginPath(); ctx.moveTo(gx, pad.t); ctx.lineTo(gx, h - pad.b); ctx.stroke();
    }

    // Draw histogram bars — colored by largest-gap local split within H₀ deaths
    const barW = Math.max(1, (plotW / N_BINS) - 1);
    binCounts.forEach((count, bin) => {
        if (count === 0) return;
        const binStart = bin * binWidth;
        const isBoundary = colorThreshold !== null && binStart >= colorThreshold;
        const x = toX(binStart);
        const barH = (count / maxCount) * plotH;
        const y = h - pad.b - barH;
        ctx.fillStyle = isBoundary ? 'rgba(239,68,68,0.72)' : 'rgba(59,130,246,0.62)';
        ctx.fillRect(x, y, barW, barH);
        ctx.strokeStyle = isBoundary ? 'rgba(185,28,28,0.5)' : 'rgba(29,78,216,0.4)';
        ctx.lineWidth = 0.5;
        ctx.strokeRect(x, y, barW, barH);
    });

    // Local split line (largest gap in H₀ deaths) — teal dashed
    if (localSplit !== null) {
        const splitX = toX(localSplit);
        ctx.strokeStyle = '#0d9488';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([5, 3]);
        ctx.beginPath(); ctx.moveTo(splitX, pad.t); ctx.lineTo(splitX, h - pad.b); ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = '#0d9488';
        ctx.font = 'bold 9px Outfit';
        ctx.textAlign = 'center';
        ctx.fillText(`gap = ${localSplit.toFixed(3)}`, splitX, pad.t + 10);
        ctx.textAlign = 'left';
    }

    // Global ε₂ line (edge weight p75) — orange dashed
    if (eps2 !== null) {
        const eps2X = toX(eps2);
        ctx.strokeStyle = '#b45309';
        ctx.lineWidth = 2;
        ctx.setLineDash([6, 4]);
        ctx.beginPath(); ctx.moveTo(eps2X, pad.t); ctx.lineTo(eps2X, h - pad.b); ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = '#b45309';
        ctx.font = 'bold 9px Outfit';
        ctx.textAlign = 'center';
        ctx.fillText(`ε₂ = ${eps2.toFixed(3)}`, eps2X, pad.t - 6);
        ctx.textAlign = 'left';
    }

    // Axes
    ctx.strokeStyle = '#cbd5e1';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(pad.l, pad.t); ctx.lineTo(pad.l, h - pad.b); ctx.lineTo(w - pad.r, h - pad.b);
    ctx.stroke();

    // X tick labels
    ctx.fillStyle = '#64748b';
    ctx.font = '10px Outfit';
    ctx.textAlign = 'center';
    for (let i = 0; i <= 5; i++) {
        const v = maxDeath * i / 5;
        ctx.fillText(v.toFixed(3), toX(v), h - pad.b + 14);
    }
    // Y tick labels
    ctx.textAlign = 'right';
    for (let i = 0; i <= 5; i++) {
        const n = Math.round(maxCount * i / 5);
        ctx.fillText(n.toString(), pad.l - 6, toY(maxCount * i / 5) + 4);
    }
    ctx.textAlign = 'left';

    // Axis labels
    ctx.fillStyle = '#cbd5e1';
    ctx.font = '11px Outfit';
    ctx.textAlign = 'center';
    ctx.fillText('Sharpness weight w (= persistence, since birth = 0)', w / 2, h - 6);
    ctx.save();
    ctx.translate(13, h / 2 + 20);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText('Number of H₀ components', 0, 0);
    ctx.restore();

    // Legend — use localSplit (gap-based) for counts when available
    const splitForCount = colorThreshold;
    const highCount = splitForCount !== null ? deaths.filter(d => d >= splitForCount).length : 0;
    const lowCount = h0.length - highCount;
    const splitLabel = localSplit !== null ? `gap (${localSplit.toFixed(3)})` : `ε₂ (${eps2?.toFixed(3) ?? '—'})`;
    const lx = pad.l + 8, ly = pad.t + 22;
    ctx.fillStyle = 'rgba(255,255,255,0.93)';
    ctx.strokeStyle = '#cbd5e1';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.roundRect(lx, ly, 230, 72, 4); ctx.fill(); ctx.stroke();

    ctx.fillStyle = 'rgba(239,68,68,0.72)';
    ctx.fillRect(lx + 8, ly + 8, 14, 10);
    ctx.fillStyle = '#b91c1c';
    ctx.font = '10px Outfit';
    ctx.textAlign = 'left';
    ctx.fillText(`High persistence (w ≥ ${splitLabel}): ${highCount}`, lx + 28, ly + 18);

    ctx.fillStyle = 'rgba(59,130,246,0.62)';
    ctx.fillRect(lx + 8, ly + 28, 14, 10);
    ctx.fillStyle = '#1d4ed8';
    ctx.fillText(`Low persistence  (w < ${splitLabel}): ${lowCount}`, lx + 28, ly + 38);

    // Reference line note
    ctx.fillStyle = '#64748b';
    ctx.font = '9px Outfit';
    ctx.fillText(`Orange dashed = global ε₂ (persistence gap)`, lx + 8, ly + 58);

    ctx.textAlign = 'left';
}


function drawBettiCurves(ctx, w, h) {
    const persistence = phState.persistence;
    if (!persistence?.betti_curves) { drawEmptyChart(ctx, w, h, 'No Betti curve data.'); return; }

    const thresholds = persistence.betti_curves.thresholds || [];
    const h0F = getFilteredDiagram('H0');
    if (!thresholds.length || !h0F.length) {
        drawEmptyChart(ctx, w, h, 'No H₀ features available for Betti curve.');
        return;
    }

    const beta0 = thresholds.map(a => h0F.filter(([b, d]) => b <= a && a < d).length);
    // H1 is not computed by this dashboard (single-linkage H0 only); omit beta1.

    const pad = { t: 46, r: 22, b: 56, l: 62 };
    const plotW = w - pad.l - pad.r;
    const plotH = h - pad.t - pad.b;
    const maxX = Math.max(...thresholds) || 1;
    const maxY = Math.max(...beta0, 1) * 1.15;

    const toX = v => pad.l + (v / maxX) * plotW;
    const toYB = n => h - pad.b - (n / maxY) * plotH;

    // Background
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, w, h);

    // Title
    ctx.fillStyle = '#1e293b';
    ctx.font = 'bold 13px Outfit';
    ctx.textAlign = 'center';
    ctx.fillText('Betti Curve — β₀(α): Connected Components vs. Sharpness Threshold', w / 2, 26);
    ctx.textAlign = 'left';

    // Fine grid
    ctx.strokeStyle = 'rgba(148,163,184,0.5)';
    ctx.lineWidth = 0.5;
    for (let i = 0; i <= 8; i++) {
        const gx = pad.l + (plotW * i / 8);
        const gy = pad.t + (plotH * i / 8);
        ctx.beginPath(); ctx.moveTo(gx, pad.t); ctx.lineTo(gx, h - pad.b); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(pad.l, gy); ctx.lineTo(w - pad.r, gy); ctx.stroke();
    }

    // Axes
    ctx.strokeStyle = '#cbd5e1';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(pad.l, pad.t); ctx.lineTo(pad.l, h - pad.b); ctx.lineTo(w - pad.r, h - pad.b);
    ctx.stroke();

    // ── Filled area under β₀ ─────────────────────────────────────────────────
    ctx.beginPath();
    ctx.moveTo(toX(thresholds[0]), h - pad.b);
    thresholds.forEach((t, i) => ctx.lineTo(toX(t), toYB(beta0[i])));
    ctx.lineTo(toX(thresholds[thresholds.length - 1]), h - pad.b);
    ctx.closePath();
    ctx.fillStyle = 'rgba(109,40,217,0.12)';
    ctx.fill();

    // β₀ line
    ctx.strokeStyle = '#7c3aed';
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    thresholds.forEach((t, i) => {
        const x = toX(t), y = toYB(beta0[i]);
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.stroke();

    // H1 is not computed — only β₀ is plotted.

    // ── ε₂ threshold marker ───────────────────────────────────────────────────
    const analysis = phState.activeAnalysis || computeActiveAnalysis();
    if (analysis?.thresholdValue) {
        const thVal = analysis.thresholdValue;
        const mx = toX(thVal);
        ctx.strokeStyle = '#b45309';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([6, 4]);
        ctx.beginPath(); ctx.moveTo(mx, pad.t); ctx.lineTo(mx, h - pad.b); ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = '#b45309';
        ctx.font = 'bold 9px Outfit';
        ctx.textAlign = 'center';
        ctx.fillText(`ε₂ = ${thVal.toFixed(3)}`, mx, pad.t - 4);
        ctx.textAlign = 'left';
    }

    // ── Tick labels ───────────────────────────────────────────────────────────
    ctx.fillStyle = '#64748b';
    ctx.font = '10px Outfit';
    ctx.textAlign = 'center';
    for (let i = 0; i <= 5; i++) {
        ctx.fillText((maxX * i / 5).toFixed(2), toX(maxX * i / 5), h - pad.b + 14);
    }
    ctx.textAlign = 'right';
    for (let i = 0; i <= 5; i++) {
        const y = Math.round(maxY * i / 5);
        ctx.fillText(y, pad.l - 6, toYB(maxY * i / 5) + 4);
    }
    ctx.textAlign = 'left';

    // Axis labels
    ctx.fillStyle = '#cbd5e1';
    ctx.font = '11px Outfit';
    ctx.textAlign = 'center';
    ctx.fillText('Filtration parameter α (sharpness)', w / 2, h - 4);
    ctx.save();
    ctx.translate(13, h / 2 + 30);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText('β₀(α) — active components', 0, 0);
    ctx.restore();
    ctx.textAlign = 'left';

    // ── PH entropy computed from diagram ──────────────────────────────────────
    const persistences = h0F.map(([b, d]) => d - b).filter(p => p > 0);
    let entrH0 = '—';
    if (persistences.length > 0) {
        const totalP = persistences.reduce((s, p) => s + p, 0);
        const entropy = -persistences.reduce((s, p) => {
            const pi = p / totalP;
            return s + pi * Math.log(pi);
        }, 0);
        entrH0 = entropy.toFixed(3);
    }

    // ── Legend box ────────────────────────────────────────────────────────────
    const lx = w - 148, ly = pad.t + 4;
    ctx.fillStyle = 'rgba(255,255,255,0.95)';
    ctx.strokeStyle = '#cbd5e1';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.roundRect(lx, ly, 140, 50, 4); ctx.fill(); ctx.stroke();

    ctx.strokeStyle = '#7c3aed'; ctx.lineWidth = 2.5;
    ctx.beginPath(); ctx.moveTo(lx + 8, ly + 16); ctx.lineTo(lx + 28, ly + 16); ctx.stroke();
    ctx.fillStyle = '#6d28d9'; ctx.font = '10px Outfit';
    ctx.fillText(`β₀ (H₀): ${h0F.length} features`, lx + 32, ly + 20);
    ctx.fillStyle = '#5b21b6'; ctx.font = '9px Outfit';
    ctx.fillText(`Entropy H₀ = ${entrH0}`, lx + 32, ly + 32);

    ctx.fillStyle = '#b45309'; ctx.font = '9px Outfit';
    ctx.fillText('── ε₂ threshold', lx + 8, ly + 46);

    // Formula caption
    ctx.fillStyle = 'rgba(51,65,85,0.9)';
    ctx.font = '9px Outfit';
    ctx.fillText('β₀(α) = #{(b,d) ∈ Dgm₀ : b ≤ α < d}.  Shows how many sharp boundary components exist at each threshold α.', pad.l, h - 2);
}

function drawBarcode(ctx, w, h, dim) {
    const diagram = getFilteredDiagram(dim);
    if (!diagram.length) {
        drawEmptyChart(ctx, w, h, 'No features pass the current persistence filter.');
        return;
    }

    const isH1 = (dim === 'H1');
    const pad = { t: 46, r: 18, b: 46, l: 62 };
    const plotW = w - pad.l - pad.r;
    const plotH = h - pad.t - pad.b;

    const sorted = [...diagram]
        .sort((a, b) => (b[1] - b[0]) - (a[1] - a[0]))
        .slice(0, 60);

    const maxFilt = (Math.max(...sorted.flat()) || 1) * 1.06;
    const maxPers = Math.max(...sorted.map(([b, d]) => d - b), 0.001);
    const barH = Math.max(2, (plotH / sorted.length) - 1);

    const toX = v => pad.l + (v / maxFilt) * plotW;

    // Color per bar = viridis-inspired: low pers = cool blue, high = warm yellow
    function barColor(norm) {
        if (isH1) {
            // pink→magenta scale for H1
            const r = Math.round(214 + norm * 41);
            const g = Math.round(68 - norm * 68);
            const b = Math.round(148 + norm * 34);
            return `rgb(${r},${g},${b})`;
        } else {
            // lavender→deep purple scale for H0
            const r = Math.round(167 + norm * 20);
            const g = Math.round(139 - norm * 139);
            const b = Math.round(250 - norm * 80);
            return `rgb(${r},${g},${b})`;
        }
    }

    // Background
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, w, h);

    // Title
    ctx.fillStyle = '#1e293b';
    ctx.font = 'bold 13px Outfit';
    ctx.textAlign = 'center';
    const dimLabel = isH1
        ? 'H₁ Barcode — Topological Loops'
        : 'H₀ Barcode — Connected Components';
    ctx.fillText(dimLabel, w / 2, 28);
    ctx.textAlign = 'left';

    // Subtitle
    ctx.fillStyle = '#64748b';
    ctx.font = '9px Outfit';
    ctx.textAlign = 'center';
    ctx.fillText(isH1
        ? 'Each bar = one H₁ loop.  Width = persistence Δ = death − birth'
        : 'Each bar = one H₀ component.  Width = persistence Δ = death − birth',
        w / 2, 41);
    ctx.textAlign = 'left';

    // Fine grid
    ctx.strokeStyle = 'rgba(148,163,184,0.5)';
    ctx.lineWidth = 0.5;
    for (let i = 0; i <= 6; i++) {
        const gx = pad.l + (plotW * i / 6);
        ctx.beginPath(); ctx.moveTo(gx, pad.t); ctx.lineTo(gx, h - pad.b); ctx.stroke();
    }

    // Axis
    ctx.strokeStyle = '#cbd5e1';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(pad.l, pad.t); ctx.lineTo(pad.l, h - pad.b); ctx.lineTo(w - pad.r, h - pad.b);
    ctx.stroke();

    // Draw bars
    sorted.forEach(([birth, death], index) => {
        const norm = (death - birth) / maxPers;
        const x1 = toX(birth);
        const x2 = toX(death);
        const y = pad.t + (index / sorted.length) * plotH;

        // Bar background
        ctx.fillStyle = 'rgba(226,232,240,0.6)';
        ctx.fillRect(pad.l, y, plotW, barH);

        // Bar fill — color encodes persistence
        ctx.fillStyle = barColor(norm);
        ctx.globalAlpha = 0.75 + norm * 0.25;
        ctx.fillRect(x1, y + 0.5, Math.max(2, x2 - x1), barH - 1);
        ctx.globalAlpha = 1;

        // Birth tick
        ctx.strokeStyle = 'rgba(0,0,0,0.2)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x1, y); ctx.lineTo(x1, y + barH);
        ctx.stroke();
    });

    // Tick labels
    ctx.fillStyle = '#64748b';
    ctx.font = '10px Outfit';
    ctx.textAlign = 'center';
    for (let i = 0; i <= 5; i++) {
        const v = maxFilt * i / 5;
        ctx.fillText(v.toFixed(2), toX(v), h - pad.b + 14);
    }
    ctx.textAlign = 'left';

    // Axis labels
    ctx.fillStyle = '#cbd5e1';
    ctx.font = '11px Outfit';
    ctx.textAlign = 'center';
    ctx.fillText('Filtration value α (sharpness)', w / 2, h - 4);
    ctx.save();
    ctx.translate(13, h / 2 + 20);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText('Features (sorted by persistence Δ)', 0, 0);
    ctx.restore();
    ctx.textAlign = 'left';

    // Color bar legend
    const cbX = w - 16, cbY = pad.t, cbH = plotH;
    const grad = ctx.createLinearGradient(0, cbY, 0, cbY + cbH);
    if (isH1) {
        grad.addColorStop(0, 'rgb(255,36,182)');
        grad.addColorStop(1, 'rgb(214,68,148)');
    } else {
        grad.addColorStop(0, 'rgb(187,0,170)');
        grad.addColorStop(1, 'rgb(167,139,250)');
    }
    ctx.fillStyle = grad;
    ctx.fillRect(cbX, cbY, 10, cbH);
    ctx.fillStyle = '#64748b';
    ctx.font = '8px Outfit';
    ctx.fillText('high Δ', cbX - 5, cbY - 2);
    ctx.fillText('low Δ', cbX - 3, cbY + cbH + 10);

    // ── formula caption already done inside; close function ─────────────
}


function buildPersistenceDiagramHTML() {
    return getEpsContextBanner('recompute') + `
        <div class="math-panel">
            <div class="math-title">H₀ Persistence Distribution</div>
            <div class="math-body">
                This dashboard computes <strong>H₀ (connected components)</strong> only, using single-linkage
                clustering (Union-Find) on the block adjacency graph. Because components are created at filtration
                value 0, <strong>all births = 0</strong> and <em>death = persistence</em> for every feature.
                <br><br>
                The histogram shows the distribution of H₀ death values (sharpness weights at which each
                connected component merges). Bars are split by the <strong>largest gap in the H₀ death
                distribution</strong> (teal dashed line):
                <span style="color:#ef4444;">■ Red bars</span> = high-persistence components that required
                crossing a sharp boundary to merge.
                <span style="color:#3b82f6;">■ Blue bars</span> = low-persistence components that merged across
                gentle transitions.
                <br><br>
                The <span style="color:#b45309;font-weight:bold;">orange dashed line</span> shows the global ε₂
                (auto-derived from the largest topological gap in the H₀ death distribution, with top 2%
                outliers trimmed). Note: all H₀ deaths may lie above ε₂ if the spanning-tree merges all
                occur at high sharpness — that itself is a meaningful finding.
            </div>
        </div>
        <canvas data-chart="persistence-diagram" class="ph-chart-canvas" style="height:400px;"></canvas>
    `;
}

function buildBettiCurvesHTML() {
    return getEpsContextBanner('recompute') + `
        <div class="math-panel">
            <div class="math-title">Betti Curve — β₀(α)</div>
            <div class="math-body">
                β₀(α) = #{(b, d) ∈ Dgm₀ : b ≤ α &lt; d} — the number of
                distinct connected clusters still alive at sharpness threshold α.
                <br><br>
                <span style="color:#a78bfa">■</span> <strong>β₀(α)</strong>: as α increases, more blocks merge into fewer clusters.
                A <strong>rapid drop</strong> in β₀ signals that many components merge at similar sharpness levels —
                indicating a coherent boundary structure.
                The curve reaches 1 when all blocks form a single connected component.
                <br><br>
                The vertical dashed line marks the ε₂ boundary threshold. Features to the right of ε₂
                are the persistent boundary components relevant to the Brantingham crime-gradient hypothesis.
            </div>
        </div>
        <canvas data-chart="betti-curves" class="ph-chart-canvas" style="height:400px;"></canvas>
    `;
}

function buildBarcodeHTML() {
    return getEpsContextBanner('recompute') + `
        <div class="math-panel">
            <div class="math-title">H₀ Persistence Barcode</div>
            <div class="math-body">
                Each bar represents one H₀ connected component (cluster of blocks).
                Since all births = 0 in single-linkage clustering, <strong>bar length = death = persistence</strong>.
                Bars are sorted longest-to-shortest and coloured by persistence magnitude.
                <br><br>
                <strong>Long bars</strong> (high sharpness) = clusters separated by strong socio-economic contrasts — the sharp boundaries.
                <strong>Short bars</strong> (low sharpness) = components that merge early — interior blocks with weak contrasts.
                The top-60 most persistent features are shown.
            </div>
        </div>
        <canvas data-chart="barcode-h0" class="ph-chart-canvas" style="height:340px;"></canvas>
    `;
}


function buildBoundaryStatsHTML() {
    const analysis = computeActiveAnalysis();
    if (!analysis) return '<p>No data.</p>';

    const epsBanner = getEpsContextBanner('live');
    const summary = analysis.summary;
    const allTypes = Array.from(new Set([
        ...Object.keys(analysis.boundaryCrimeTypes),
        ...Object.keys(analysis.interiorCrimeTypes),
    ])).sort();

    let typeRows = '';
    allTypes.forEach(type => {
        const boundaryCount = analysis.boundaryCrimeTypes[type] || 0;
        const interiorCount = analysis.interiorCrimeTypes[type] || 0;
        typeRows += `
            <tr>
                <td style="padding:4px 8px;">${type}</td>
                <td style="text-align:right; color:#ef4444; padding:4px 8px;">${boundaryCount.toLocaleString()}</td>
                <td style="text-align:right; color:#3b82f6; padding:4px 8px;">${interiorCount.toLocaleString()}</td>
            </tr>
        `;
    });

    const interiorBlockCount = summary.totalBlocks - summary.sharpBlockCount;

    const selectedTypes = window.getSelectedCrimeTypes ? window.getSelectedCrimeTypes() : [];
    const dynamicStats = computeCrimeStatsByType() || summary;

    let crimeLabel = selectedTypes[0];
    if (selectedTypes.includes('Break and Enter Residential/Other') && selectedTypes.includes('Break and Enter Commercial')) {
        crimeLabel = 'Break and Enter';
    } else if (selectedTypes.length > 2) {
        crimeLabel = 'Multiple Types';
    }

    return epsBanner + `
        <p style="margin-bottom:12px; color:#94a3b8;">
            A crime is classified as <b>boundary</b> if it falls within <b>${summary.bufferRadiusM} m</b> of
            any sharp edge midpoint (w ≥ ε₂); otherwise it is classified as <b>interior</b>.
            A block is boundary if its maximum adjacent edge weight ≥ ε₂.
            Use the <b>Crime Filter Radio buttons in the left sidebar</b> to change the analyzed crime type.
        </p>

        <!-- Block counts context -->
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:16px;">
            <div style="background:rgba(239,68,68,0.07); border:1px solid rgba(239,68,68,0.25); border-radius:8px; padding:12px; text-align:center;">
                <div style="font-size:1.6rem; font-weight:700; color:#ef4444;">${summary.sharpBlockCount.toLocaleString()}</div>
                <div style="font-size:0.72rem; color:#fca5a5; margin-top:2px;">Sharp boundary blocks</div>
                <div style="font-size:0.65rem; color:#94a3b8; margin-top:2px;">${Math.round(summary.sharpBlockCount / summary.totalBlocks * 100)}% of ${summary.totalBlocks.toLocaleString()} total blocks</div>
            </div>
            <div style="background:rgba(59,130,246,0.07); border:1px solid rgba(59,130,246,0.25); border-radius:8px; padding:12px; text-align:center;">
                <div style="font-size:1.6rem; font-weight:700; color:#3b82f6;">${interiorBlockCount.toLocaleString()}</div>
                <div style="font-size:0.72rem; color:#93c5fd; margin-top:2px;">Interior blocks</div>
                <div style="font-size:0.65rem; color:#94a3b8; margin-top:2px;">${Math.round(interiorBlockCount / summary.totalBlocks * 100)}% of ${summary.totalBlocks.toLocaleString()} total blocks</div>
            </div>
        </div>

        <div style="font-size:0.8rem; color:#64748b; margin-bottom:16px;">
            Active threshold: <b style="color:#e2e8f0;">p${analysis.thresholdPercentile}</b> (w ≥ ${analysis.thresholdValue.toFixed(3)}).
            &nbsp;|&nbsp; Sharpness–crime correlation: <span style="color:#a78bfa;">${summary.sharpnessCrimeCorrelation}</span>
        </div>

        <h4 style="margin:0 0 8px; color:#e2e8f0;">Full Breakdown — All Crime Types</h4>
        <table style="width:100%; font-size:0.82rem; border-collapse:collapse;">
            <tr style="border-bottom:1px solid rgba(255,255,255,0.1);">
                <th style="text-align:left; padding:4px 8px; color:#94a3b8;">Type</th>
                <th style="text-align:right; padding:4px 8px; color:#ef4444;">Boundary (${summary.sharpBlockCount.toLocaleString()} blocks)</th>
                <th style="text-align:right; padding:4px 8px; color:#3b82f6;">Interior (${interiorBlockCount.toLocaleString()} blocks)</th>
            </tr>
            ${typeRows}
        </table>
    `;
}

// ═══════════════════════════════════════════════════════════════════════════
// NEW TDA PANELS — Persistence Landscape, Persistence Image, Euler χ
// ═══════════════════════════════════════════════════════════════════════════

// ── Persistence Landscape λₖ(t) ──────────────────────────────────────────
function buildPersistenceLandscapeHTML() {
    return getEpsContextBanner('recompute') + `
        <div class="math-panel">
            <div class="math-title">Persistence Landscape — λ<sub>k</sub>(t)</div>
            <div class="math-body">
                The persistence landscape converts a persistence diagram into a sequence of
                piecewise-linear functions λ<sub>1</sub> ≥ λ<sub>2</sub> ≥ … that live in a
                <strong>Banach space</strong>, enabling rigorous statistical analysis
                (means, confidence intervals, hypothesis tests).
                <br><br>
                For each feature [b, d], define a tent function
                <em>Λ(t) = min(t − b, d − t)</em> when b ≤ t ≤ d, else 0.
                <strong>λ<sub>k</sub>(t)</strong> is the k-th largest tent value at each t.
                <br><br>
                <strong>Tall peaks = persistent (significant) features.</strong>
                The landscape integral ∫λ<sub>k</sub>(t)dt measures total topological complexity.
            </div>
        </div>
        <h4 style="color:#a78bfa; margin:10px 0 6px;">H₀ Landscape — Connected Components</h4>
        <canvas data-chart="persistence-landscape" class="ph-chart-canvas" style="height:380px;"></canvas>
    `;
}

function drawPersistenceLandscape(ctx, w, h) {
    const persistence = phState.persistence;
    if (!persistence) { drawEmptyChart(ctx, w, h, 'No persistence data loaded.'); return; }

    const h0 = persistence.diagrams?.H0 || [];
    const h1 = persistence.diagrams?.H1 || [];
    if (!h0.length && !h1.length) {
        drawEmptyChart(ctx, w, h, 'No PH features available for landscape.');
        return;
    }

    const pad = { t: 40, r: 22, b: 56, l: 62 };
    const plotW = w - pad.l - pad.r;
    const plotH = h - pad.t - pad.b;

    // Compute landscape for a diagram
    function computeLandscape(diagram, numLayers) {
        if (!diagram.length) return [];
        const allVals = diagram.flat();
        const minV = Math.min(...allVals);
        const maxV = Math.max(...allVals);
        const nSteps = 200;
        const dt = (maxV - minV) / nSteps;
        const layers = [];

        for (let step = 0; step <= nSteps; step++) {
            const t = minV + step * dt;
            // Compute tent values for all features at this t
            const tents = diagram.map(([b, d]) => {
                if (t < b || t > d) return 0;
                return Math.min(t - b, d - t);
            }).sort((a, b) => b - a);

            for (let k = 0; k < Math.min(numLayers, tents.length); k++) {
                if (!layers[k]) layers[k] = [];
                layers[k].push({ t, value: tents[k] });
            }
        }
        return layers;
    }

    const NUM_LAYERS = 5;
    const h0Layers = computeLandscape(h0, NUM_LAYERS);
    const h1Layers = computeLandscape(h1, NUM_LAYERS);
    const allLayers = [...h0Layers, ...h1Layers];

    const allT = allLayers.flatMap(l => l.map(p => p.t));
    const allV = allLayers.flatMap(l => l.map(p => p.value));
    const minT = Math.min(...allT, 0);
    const maxT = Math.max(...allT, 1);
    const maxV = Math.max(...allV, 0.001) * 1.1;

    const toX = t => pad.l + ((t - minT) / (maxT - minT)) * plotW;
    const toY = v => h - pad.b - (v / maxV) * plotH;

    // Background
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, w, h);

    // Title
    ctx.fillStyle = '#1e293b';
    ctx.font = 'bold 13px Outfit';
    ctx.textAlign = 'center';
    ctx.fillText('Persistence Landscape — λₖ(t)', w / 2, 24);
    ctx.textAlign = 'left';

    // Grid
    ctx.strokeStyle = 'rgba(148,163,184,0.5)';
    ctx.lineWidth = 0.5;
    for (let i = 0; i <= 8; i++) {
        const gx = pad.l + (plotW * i / 8);
        const gy = pad.t + (plotH * i / 8);
        ctx.beginPath(); ctx.moveTo(gx, pad.t); ctx.lineTo(gx, h - pad.b); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(pad.l, gy); ctx.lineTo(w - pad.r, gy); ctx.stroke();
    }

    // Axes
    ctx.strokeStyle = '#cbd5e1';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(pad.l, pad.t); ctx.lineTo(pad.l, h - pad.b); ctx.lineTo(w - pad.r, h - pad.b);
    ctx.stroke();

    // Draw H0 layers (purple tones)
    const h0Colors = ['rgba(109,40,217,0.85)', 'rgba(167,139,250,0.6)', 'rgba(167,139,250,0.4)',
        'rgba(167,139,250,0.25)', 'rgba(109,40,217,0.12)'];
    h0Layers.forEach((layer, k) => {
        if (!layer.length) return;
        // Filled area
        ctx.beginPath();
        ctx.moveTo(toX(layer[0].t), h - pad.b);
        layer.forEach(p => ctx.lineTo(toX(p.t), toY(p.value)));
        ctx.lineTo(toX(layer[layer.length - 1].t), h - pad.b);
        ctx.closePath();
        ctx.fillStyle = h0Colors[k] ? h0Colors[k].replace('0.9', '0.12').replace('0.6', '0.08').replace('0.4', '0.05') : 'rgba(167,139,250,0.03)';
        ctx.fill();

        // Line
        ctx.strokeStyle = h0Colors[k] || 'rgba(167,139,250,0.1)';
        ctx.lineWidth = Math.max(0.8, 2.5 - k * 0.4);
        ctx.beginPath();
        layer.forEach((p, i) => {
            const x = toX(p.t), y = toY(p.value);
            i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        });
        ctx.stroke();
    });

    // Draw H1 layers (pink tones)
    const h1Colors = ['rgba(225,29,72,0.85)', 'rgba(244,114,182,0.6)', 'rgba(244,114,182,0.4)',
        'rgba(244,114,182,0.25)', 'rgba(225,29,72,0.12)'];
    h1Layers.forEach((layer, k) => {
        if (!layer.length) return;
        ctx.strokeStyle = h1Colors[k] || 'rgba(244,114,182,0.1)';
        ctx.lineWidth = Math.max(0.8, 2.5 - k * 0.4);
        ctx.setLineDash([4, 2]);
        ctx.beginPath();
        layer.forEach((p, i) => {
            const x = toX(p.t), y = toY(p.value);
            i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        });
        ctx.stroke();
        ctx.setLineDash([]);
    });

    // ε₂ threshold marker
    const analysis = phState.activeAnalysis || computeActiveAnalysis();
    if (analysis?.thresholdValue) {
        const mx = toX(analysis.thresholdValue);
        ctx.strokeStyle = '#b45309';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([6, 4]);
        ctx.beginPath(); ctx.moveTo(mx, pad.t); ctx.lineTo(mx, h - pad.b); ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = '#b45309';
        ctx.font = 'bold 9px Outfit';
        ctx.textAlign = 'center';
        ctx.fillText(`ε₂ = ${analysis.thresholdValue.toFixed(3)}`, mx, pad.t - 4);
        ctx.textAlign = 'left';
    }

    // Compute landscape integrals for display
    function landscapeIntegral(layers) {
        if (!layers.length || !layers[0].length) return 0;
        let integral = 0;
        const layer = layers[0];
        for (let i = 1; i < layer.length; i++) {
            integral += (layer[i].value + layer[i - 1].value) / 2 * (layer[i].t - layer[i - 1].t);
        }
        return integral;
    }
    const h0Integral = landscapeIntegral(h0Layers);
    const h1Integral = landscapeIntegral(h1Layers);

    // Legend box
    const lx = w - 170, ly = pad.t + 4;
    ctx.fillStyle = 'rgba(255,255,255,0.95)';
    ctx.strokeStyle = '#cbd5e1';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.roundRect(lx, ly, 162, 74, 4); ctx.fill(); ctx.stroke();

    ctx.strokeStyle = '#7c3aed'; ctx.lineWidth = 2.5;
    ctx.beginPath(); ctx.moveTo(lx + 8, ly + 16); ctx.lineTo(lx + 28, ly + 16); ctx.stroke();
    ctx.fillStyle = '#6d28d9'; ctx.font = '10px Outfit';
    ctx.fillText(`H₀ λₖ (${h0.length} feat)  ∫=${h0Integral.toFixed(2)}`, lx + 32, ly + 20);

    ctx.strokeStyle = '#e11d48'; ctx.lineWidth = 2.5;
    ctx.setLineDash([4, 2]);
    ctx.beginPath(); ctx.moveTo(lx + 8, ly + 36); ctx.lineTo(lx + 28, ly + 36); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = '#be123c'; ctx.font = '10px Outfit';
    ctx.fillText(`H₁ λₖ (${h1.length} feat)  ∫=${h1Integral.toFixed(2)}`, lx + 32, ly + 40);

    ctx.fillStyle = '#b45309'; ctx.font = '9px Outfit';
    ctx.fillText('── ε₂ threshold', lx + 8, ly + 56);
    ctx.fillStyle = '#64748b'; ctx.font = '9px Outfit';
    ctx.fillText(`k = 1..${NUM_LAYERS} layers shown`, lx + 8, ly + 70);

    // Tick labels
    ctx.fillStyle = '#64748b';
    ctx.font = '10px Outfit';
    ctx.textAlign = 'center';
    for (let i = 0; i <= 5; i++) {
        const tv = minT + (maxT - minT) * i / 5;
        ctx.fillText(tv.toFixed(2), toX(tv), h - pad.b + 14);
    }
    ctx.textAlign = 'right';
    for (let i = 0; i <= 4; i++) {
        const v = maxV * i / 4;
        ctx.fillText(v.toFixed(3), pad.l - 6, toY(v) + 4);
    }
    ctx.textAlign = 'left';

    // Axis labels
    ctx.fillStyle = '#cbd5e1';
    ctx.font = '11px Outfit';
    ctx.textAlign = 'center';
    ctx.fillText('Filtration parameter t (sharpness)', w / 2, h - 4);
    ctx.save();
    ctx.translate(13, h / 2 + 20);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText('λₖ(t) = k-th largest tent value', 0, 0);
    ctx.restore();
    ctx.textAlign = 'left';

    // Caption
    ctx.fillStyle = 'rgba(51,65,85,0.9)';
    ctx.font = '9px Outfit';
    ctx.fillText('Λ(t) = min(t−b, d−t).  λₖ = k-th order statistic.  Integral = ∫λ₁(t)dt', pad.l, h - 2);
}


// ── Persistence Image (2D heatmap) ──────────────────────────────────────
function buildPersistenceImageHTML() {
    return getEpsContextBanner('recompute') + `
        <div class="math-panel">
            <div class="math-title">Persistence Image — PI(σ)</div>
            <div class="math-body">
                A persistence image is a <strong>stable, fixed-size vectorisation</strong> of a
                persistence diagram. Each birth-death point (b, d) is mapped to
                <em>(b, d−b)</em> (birth vs persistence), then smoothed with a Gaussian kernel
                of bandwidth σ and weighted by persistence.
                <br><br>
                <strong>Hot regions = clusters of persistent features.</strong>
                The resulting heatmap is integrable with machine learning pipelines
                and provides a visually intuitive "fingerprint" of the topological structure.
            </div>
        </div>
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:14px;">
            <div>
                <h4 style="color:#a78bfa; margin:0 0 6px;">H₀ — Components</h4>
                <canvas data-chart="persistence-image" data-dim="H0" class="ph-chart-canvas" style="height:360px;"></canvas>
            </div>
            <div>
                <h4 style="color:#f472b6; margin:0 0 6px;">H₁ — Loops</h4>
                <canvas data-chart="persistence-image" data-dim="H1" class="ph-chart-canvas" style="height:360px;"></canvas>
            </div>
        </div>
    `;
}

function drawPersistenceImage(ctx, w, h, dimOverride) {
    const persistence = phState.persistence;
    if (!persistence) { drawEmptyChart(ctx, w, h, 'No persistence data loaded.'); return; }

    // Determine dimension from canvas data attribute or fallback
    const canvas = ctx.canvas;
    const dim = dimOverride || canvas?.getAttribute('data-dim') || 'H0';
    const diagram = persistence.diagrams?.[dim] || [];
    const isH1 = (dim === 'H1');

    if (!diagram.length) {
        drawEmptyChart(ctx, w, h, `No ${dim} features for PI.`);
        return;
    }

    // Transform to (birth, persistence) space
    const bdPoints = diagram.map(([b, d]) => ({ birth: b, pers: d - b }));
    const maxBirth = Math.max(...bdPoints.map(p => p.birth), 0.001);
    const maxPers = Math.max(...bdPoints.map(p => p.pers), 0.001);

    // Grid resolution for the persistence image
    const GRID = 40;
    const bw = maxBirth * 1.15; // slight padding
    const pw = maxPers * 1.15;
    const sigma_b = bw / GRID * 2.5;
    const sigma_p = pw / GRID * 2.5;
    const grid = Array.from({ length: GRID }, () => new Float64Array(GRID));

    // Gaussian KDE on (birth, persistence) space, weighted by persistence
    bdPoints.forEach(({ birth, pers }) => {
        const weight = pers / maxPers; // weight by normalised persistence
        for (let r = 0; r < GRID; r++) {
            const py = (r + 0.5) / GRID * pw;
            const dp = (py - pers) / sigma_p;
            if (Math.abs(dp) > 3) continue;
            for (let c = 0; c < GRID; c++) {
                const bx = (c + 0.5) / GRID * bw;
                const db = (bx - birth) / sigma_b;
                if (Math.abs(db) > 3) continue;
                grid[r][c] += weight * Math.exp(-0.5 * (db * db + dp * dp));
            }
        }
    });

    // Normalise grid
    let gMax = 0;
    grid.forEach(row => row.forEach(v => { if (v > gMax) gMax = v; }));
    if (gMax === 0) gMax = 1;

    const pad = { t: 40, r: 20, b: 56, l: 62 };
    const plotW = w - pad.l - pad.r;
    const plotH = h - pad.t - pad.b;
    const cellW = plotW / GRID;
    const cellH = plotH / GRID;

    // Background
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, w, h);

    // Title
    ctx.fillStyle = '#1e293b';
    ctx.font = 'bold 13px Outfit';
    ctx.textAlign = 'center';
    ctx.fillText(`Persistence Image — ${dim}`, w / 2, 24);
    ctx.textAlign = 'left';

    // Draw heatmap cells
    for (let r = 0; r < GRID; r++) {
        for (let c = 0; c < GRID; c++) {
            const norm = grid[r][c] / gMax;
            if (norm < 0.01) continue;
            const x = pad.l + c * cellW;
            const y = pad.t + (GRID - 1 - r) * cellH; // flip Y so persistence increases upward

            if (isH1) {
                // Pink-magenta palette
                const red = Math.round(30 + norm * 225);
                const green = Math.round(15 + norm * 40);
                const blue = Math.round(60 + norm * 140);
                ctx.fillStyle = `rgba(${red},${green},${blue},${0.3 + norm * 0.7})`;
            } else {
                // Purple-blue palette
                const red = Math.round(30 + norm * 167);
                const green = Math.round(20 + norm * 100);
                const blue = Math.round(80 + norm * 170);
                ctx.fillStyle = `rgba(${red},${green},${blue},${0.3 + norm * 0.7})`;
            }
            ctx.fillRect(x, y, cellW + 0.5, cellH + 0.5);
        }
    }

    // Overlay actual diagram points as dots
    bdPoints.forEach(({ birth, pers }) => {
        const x = pad.l + (birth / bw) * plotW;
        const y = pad.t + (1 - pers / pw) * plotH;
        const r = 2 + (pers / maxPers) * 3;
        ctx.beginPath();
        ctx.arc(x, y, r, 0, Math.PI * 2);
        ctx.fillStyle = isH1 ? 'rgba(255,255,255,0.6)' : 'rgba(255,255,255,0.5)';
        ctx.fill();
        ctx.strokeStyle = isH1 ? '#e11d48' : '#7c3aed';
        ctx.lineWidth = 0.6;
        ctx.stroke();
    });

    // Axes
    ctx.strokeStyle = '#cbd5e1';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(pad.l, pad.t); ctx.lineTo(pad.l, h - pad.b); ctx.lineTo(w - pad.r, h - pad.b);
    ctx.stroke();

    // Tick labels
    ctx.fillStyle = '#64748b';
    ctx.font = '10px Outfit';
    ctx.textAlign = 'center';
    for (let i = 0; i <= 4; i++) {
        ctx.fillText((bw * i / 4).toFixed(2), pad.l + plotW * i / 4, h - pad.b + 14);
    }
    ctx.textAlign = 'right';
    for (let i = 0; i <= 4; i++) {
        ctx.fillText((pw * i / 4).toFixed(3), pad.l - 6, pad.t + plotH * (1 - i / 4) + 4);
    }
    ctx.textAlign = 'left';

    // Axis labels
    ctx.fillStyle = '#cbd5e1';
    ctx.font = '11px Outfit';
    ctx.textAlign = 'center';
    ctx.fillText('Birth (sharpness α)', w / 2, h - 4);
    ctx.save();
    ctx.translate(13, h / 2 + 20);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText('Persistence Δ = d − b', 0, 0);
    ctx.restore();
    ctx.textAlign = 'left';

    // Color bar
    const cbX = w - 16, cbY = pad.t, cbH = plotH;
    const grad = ctx.createLinearGradient(0, cbY + cbH, 0, cbY);
    if (isH1) {
        grad.addColorStop(0, '#1e0830'); grad.addColorStop(0.5, '#db2777'); grad.addColorStop(1, '#fff');
    } else {
        grad.addColorStop(0, '#0f1530'); grad.addColorStop(0.5, '#7c3aed'); grad.addColorStop(1, '#fff');
    }
    ctx.fillStyle = grad;
    ctx.fillRect(cbX, cbY, 10, cbH);
    ctx.fillStyle = '#64748b';
    ctx.font = '8px Outfit';
    ctx.fillText('high', cbX - 3, cbY - 2);
    ctx.fillText('low', cbX - 1, cbY + cbH + 10);

    // Stats
    const totalPers = bdPoints.reduce((s, p) => s + p.pers, 0);
    ctx.fillStyle = 'rgba(51,65,85,0.9)';
    ctx.font = '9px Outfit';
    ctx.fillText(`${dim}: ${diagram.length} features | Total persistence = ${totalPers.toFixed(3)} | σ = ${sigma_b.toFixed(4)}`, pad.l, h - 2);
}


// ── Euler Characteristic Curve χ(α) ──────────────────────────────────────
function buildEulerCurveHTML() {
    return getEpsContextBanner('recompute') + `
        <div class="math-panel">
            <div class="math-title">Euler Characteristic Curve — χ(α)</div>
            <div class="math-body">
                χ(α) = β₀(α) − β₁(α) — the alternating sum of Betti numbers at filtration threshold α.
                <br><br>
                This <strong>single scalar curve</strong> compactly summarises the global topological
                complexity of the boundary sharpness field. It is computationally efficient,
                stable under noise, and widely used in TDA-based classification and regression.
                <br><br>
                <strong>High χ:</strong> many isolated sharp regions, few enclosed loops.<br>
                <strong>Low / negative χ:</strong> dominant loop structures encircling interior areas.
            </div>
        </div>
        <canvas data-chart="euler-curve" class="ph-chart-canvas" style="height:380px;"></canvas>
    `;
}

function drawEulerCurve(ctx, w, h) {
    const persistence = phState.persistence;
    if (!persistence?.betti_curves) { drawEmptyChart(ctx, w, h, 'No Betti curve data.'); return; }

    const thresholds = persistence.betti_curves.thresholds || [];
    const h0 = persistence.diagrams?.H0 || [];
    const h1 = persistence.diagrams?.H1 || [];

    if (!thresholds.length) {
        drawEmptyChart(ctx, w, h, 'No filtration thresholds available.');
        return;
    }

    // Compute β₀, β₁, and χ at each threshold
    const beta0 = thresholds.map(a => h0.filter(([b, d]) => b <= a && a < d).length);
    const beta1 = thresholds.map(a => h1.filter(([b, d]) => b <= a && a < d).length);
    const chi = thresholds.map((_, i) => beta0[i] - beta1[i]);

    const pad = { t: 40, r: 22, b: 56, l: 62 };
    const plotW = w - pad.l - pad.r;
    const plotH = h - pad.t - pad.b;
    const maxX = Math.max(...thresholds) || 1;
    const minChi = Math.min(...chi, 0);
    const maxChi = Math.max(...chi, 1);
    const chiRange = Math.max(maxChi - minChi, 1);

    const toX = v => pad.l + (v / maxX) * plotW;
    const toYC = n => h - pad.b - ((n - minChi) / chiRange) * plotH;

    // Background
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, w, h);

    // Title
    ctx.fillStyle = '#1e293b';
    ctx.font = 'bold 13px Outfit';
    ctx.textAlign = 'center';
    ctx.fillText('Euler Characteristic Curve — χ(α) = β₀ − β₁', w / 2, 24);
    ctx.textAlign = 'left';

    // Grid
    ctx.strokeStyle = 'rgba(148,163,184,0.5)';
    ctx.lineWidth = 0.5;
    for (let i = 0; i <= 8; i++) {
        const gx = pad.l + (plotW * i / 8);
        const gy = pad.t + (plotH * i / 8);
        ctx.beginPath(); ctx.moveTo(gx, pad.t); ctx.lineTo(gx, h - pad.b); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(pad.l, gy); ctx.lineTo(w - pad.r, gy); ctx.stroke();
    }

    // Zero line
    if (minChi < 0 && maxChi > 0) {
        const zeroY = toYC(0);
        ctx.strokeStyle = 'rgba(71,85,105,0.4)';
        ctx.lineWidth = 1;
        ctx.setLineDash([5, 5]);
        ctx.beginPath(); ctx.moveTo(pad.l, zeroY); ctx.lineTo(w - pad.r, zeroY); ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = '#64748b';
        ctx.font = '9px Outfit';
        ctx.fillText('χ = 0', w - pad.r + 2, zeroY + 3);
    }

    // Axes
    ctx.strokeStyle = '#cbd5e1';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(pad.l, pad.t); ctx.lineTo(pad.l, h - pad.b); ctx.lineTo(w - pad.r, h - pad.b);
    ctx.stroke();

    // Filled area (positive = teal, negative = red)
    for (let i = 1; i < thresholds.length; i++) {
        const x1 = toX(thresholds[i - 1]);
        const x2 = toX(thresholds[i]);
        const y1 = toYC(chi[i - 1]);
        const y2 = toYC(chi[i]);
        const yBase = toYC(0);

        ctx.beginPath();
        ctx.moveTo(x1, yBase);
        ctx.lineTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.lineTo(x2, yBase);
        ctx.closePath();

        const avgChi = (chi[i - 1] + chi[i]) / 2;
        ctx.fillStyle = avgChi >= 0 ? 'rgba(34,211,238,0.15)' : 'rgba(239,68,68,0.12)';
        ctx.fill();
    }

    // Main line
    ctx.strokeStyle = '#22d3ee';
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    thresholds.forEach((t, i) => {
        const x = toX(t), y = toYC(chi[i]);
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.stroke();

    // ε₂ threshold marker
    const analysis = phState.activeAnalysis || computeActiveAnalysis();
    if (analysis?.thresholdValue) {
        const thVal = analysis.thresholdValue;
        const mx = toX(thVal);
        ctx.strokeStyle = '#b45309';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([6, 4]);
        ctx.beginPath(); ctx.moveTo(mx, pad.t); ctx.lineTo(mx, h - pad.b); ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = '#b45309';
        ctx.font = 'bold 9px Outfit';
        ctx.textAlign = 'center';
        ctx.fillText(`ε₂ = ${thVal.toFixed(3)}`, mx, pad.t - 4);
        ctx.textAlign = 'left';
    }

    // Compute integral of χ
    let chiIntegral = 0;
    for (let i = 1; i < thresholds.length; i++) {
        chiIntegral += (chi[i] + chi[i - 1]) / 2 * (thresholds[i] - thresholds[i - 1]);
    }

    // Legend
    const lx = w - 148, ly = pad.t + 4;
    ctx.fillStyle = 'rgba(255,255,255,0.95)';
    ctx.strokeStyle = '#cbd5e1';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.roundRect(lx, ly, 140, 60, 4); ctx.fill(); ctx.stroke();

    ctx.strokeStyle = '#22d3ee'; ctx.lineWidth = 2.5;
    ctx.beginPath(); ctx.moveTo(lx + 8, ly + 16); ctx.lineTo(lx + 28, ly + 16); ctx.stroke();
    ctx.fillStyle = '#67e8f9'; ctx.font = '10px Outfit';
    ctx.fillText(`χ(α) = β₀ − β₁`, lx + 32, ly + 20);

    ctx.fillStyle = '#cbd5e1'; ctx.font = '9px Outfit';
    ctx.fillText(`∫χ(α)dα = ${chiIntegral.toFixed(2)}`, lx + 12, ly + 36);
    ctx.fillStyle = '#b45309'; ctx.font = '9px Outfit';
    ctx.fillText('── ε₂ threshold', lx + 8, ly + 52);

    // Tick labels
    ctx.fillStyle = '#64748b';
    ctx.font = '10px Outfit';
    ctx.textAlign = 'center';
    for (let i = 0; i <= 5; i++) {
        ctx.fillText((maxX * i / 5).toFixed(2), toX(maxX * i / 5), h - pad.b + 14);
    }
    ctx.textAlign = 'right';
    for (let i = 0; i <= 5; i++) {
        const v = minChi + chiRange * i / 5;
        ctx.fillText(Math.round(v).toString(), pad.l - 6, toYC(v) + 4);
    }
    ctx.textAlign = 'left';

    // Axis labels
    ctx.fillStyle = '#cbd5e1';
    ctx.font = '11px Outfit';
    ctx.textAlign = 'center';
    ctx.fillText('Filtration parameter α (sharpness)', w / 2, h - 4);
    ctx.save();
    ctx.translate(13, h / 2 + 20);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText('χ(α) = β₀(α) − β₁(α)', 0, 0);
    ctx.restore();
    ctx.textAlign = 'left';

    // Caption
    ctx.fillStyle = 'rgba(51,65,85,0.9)';
    ctx.font = '9px Outfit';
    ctx.fillText(`χ(α) = β₀ − β₁.  Positive = component-dominated.  Negative = loop-dominated.`, pad.l, h - 2);
}



// ── Spatial Crime Correlation (Plotly) ──────────────────────────────────────
function buildSpatialCorrelationHTML() {
    return getEpsContextBanner('recompute') + `
        <div class="math-panel">
            <div class="math-title">Crime vs. Boundary Sharpness — Three Views</div>
            <div class="math-body">
                Three complementary views testing whether crimes concentrate at sharp socio-economic boundaries
                (Brantingham &amp; Brantingham 1978).
                <br><br>
                <strong>Scatter:</strong> Block max sharpness vs. total crime count, with OLS trendline.<br>
                <strong>Box plot:</strong> Crime count distribution — boundary segments (w ≥ ε₂) vs. interior segments (w &lt; ε₂). Linear scale, actual counts.<br>
                <strong>Quintile bar chart:</strong> All segments split into 5 equal groups by sharpness. Mean crime count per quintile. A monotone increase from Q1 → Q5 directly supports the boundary effect.
            </div>
        </div>
        
        <div style="display: flex; flex-direction: column; gap: 20px;">
            <div id="plotly-scatter" style="height: 340px; background: rgba(30,41,59,0.5); border-radius: 8px; padding: 10px;"></div>
            <div id="plotly-boxplot" style="height: 320px; background: rgba(30,41,59,0.5); border-radius: 8px; padding: 10px;"></div>
            <div id="boxplot-summary" style="background: rgba(30,41,59,0.6); border: 1px solid rgba(148,163,184,0.15); border-radius: 8px; padding: 12px 16px; font-family: 'Outfit', sans-serif; font-size: 0.85rem; color: #cbd5e1;"></div>
            <div id="plotly-quintile" style="height: 320px; background: rgba(30,41,59,0.5); border-radius: 8px; padding: 10px;"></div>
        </div>
    `;
}

// ── Weights Optimization Simplex ─────────────────────────────────────────────
function buildWeightsOptimizationHTML() {
    return getEpsContextBanner('recompute') + `
        <div class="math-panel">
            <div class="math-title">Weight Sensitivity &amp; Simplex Optimization</div>
            <div class="math-body" id="simplex-math-body">
                This evaluates exact combinations of (α, β, γ) under the constraint α + β + γ = 1 (step 0.1).
                <br>
                The <strong>Optimization Target</strong> is the ratio of normalized boundary crime density to interior crime density,
                calculated <strong>specifically for the currently active crime filter</strong>.
            </div>
        </div>
        <div id="optimization-loading" style="text-align:center; padding: 20px; color:#cbd5e1;">Loading simplex sweep data from server...</div>
        <div id="simplex-results-container" style="display:none; flex-direction: column; gap: 20px;">
            <div style="background: rgba(30,41,59,0.8); border-radius: 8px; border: 1px solid rgba(20,184,166,0.2); padding: 15px;">
                <h4 style="margin-top:0; color:#38bdf8;">Robustness Region (Ternary Sweep)</h4>
                <div id="plotly-ternary" style="height: 400px; padding-bottom: 10px;"></div>
                <div id="robustness-summary" style="margin-top:10px; font-size:0.9rem; color:#cbd5e1; text-align:center; padding: 10px; border-top: 1px solid rgba(255,255,255,0.05); background: rgba(0,0,0,0.2); border-radius: 6px;"></div>
            </div>
            <div style="background: rgba(30,41,59,0.8); border-radius: 8px; border: 1px solid rgba(20,184,166,0.2); padding: 15px; overflow-x: auto;">
                <h4 style="margin-top:0; color:#2dd4bf;">Benchmark Configurations</h4>
                <table style="width:100%; text-align:left; border-collapse: collapse; font-size: 0.85rem;">
                    <thead>
                        <tr style="border-bottom: 1px solid #334155; color:#94a3b8;">
                            <th style="padding: 8px;">Configuration</th>
                            <th style="padding: 8px;">(α, β, γ)</th>
                            <th style="padding: 8px;">Boundary / Interior Blocks</th>
                            <th style="padding: 8px;">Filtered Boundary Crimes</th>
                            <th style="padding: 8px; color: #fbbf24;">Normalized Target Ratio</th>
                        </tr>
                    </thead>
                    <tbody id="benchmark-table-body">

                    </tbody>
                </table>
            </div>
            <div style="background: rgba(30,41,59,0.8); border-radius: 8px; border: 1px solid rgba(251,191,36,0.25); padding: 15px;">
                <h4 style="margin-top:0; color:#fbbf24;">Boundary vs. Interior Crime Rate — By Weight Configuration</h4>
                <p style="font-size:0.82rem; color:#94a3b8; margin: 0 0 12px 0;">
                    Mean crimes per segment for boundary (w ≥ ε₂) vs. interior (w &lt; ε₂), computed independently for each
                    weight configuration. Each configuration uses its own auto-derived ε₂ (largest topological gap in its H₀
                    death distribution). A consistently higher boundary bar across all four cases directly supports the
                    Brantingham &amp; Brantingham (1978) boundary-effect hypothesis.
                </p>
                <div id="plotly-crime-comparison" style="height: 360px;"></div>
                <div id="plotly-ratio-comparison" style="height: 260px; margin-top: 8px;"></div>
            </div>
        </div>
    `;
}


function renderSpatialCorrelationPlots() {
    const analysis = computeActiveAnalysis();
    if (!analysis) return;

    const selectedTypes = window.getSelectedCrimeTypes ? window.getSelectedCrimeTypes() : [];
    if (selectedTypes.length === 0) return;

    // ── Scatter plot data (block-level) ──────────────────────────────
    // Keep block-level scatter for sharpness vs crime visualization
    const dynamicBlockCounts = new Map();
    const centroids = [];

    phState.blocks.features.forEach(b => {
        const id = b.properties.block_id;
        dynamicBlockCounts.set(id, 0);
        let cx = b.properties.cx;
        let cy = b.properties.cy;

        if (cx == null && cy == null) {
            let coords = b.geometry.coordinates[0];
            if (Array.isArray(coords[0][0])) coords = coords[0];
            let sx = 0, sy = 0;
            coords.forEach(p => { sx += p[0]; sy += p[1]; });
            cx = sx / coords.length;
            cy = sy / coords.length;
        }
        centroids.push({ id, cx, cy });
    });

    const activeCrimes = phState.crimes.features.filter(f => selectedTypes.includes(f.properties?.TYPE));
    activeCrimes.forEach(f => {
        const coords = f.geometry?.coordinates;
        if (!coords) return;
        let minDist = Infinity;
        let bestId = null;
        for (let i = 0; i < centroids.length; i++) {
            let dx = centroids[i].cx - coords[0];
            let dy = centroids[i].cy - coords[1];
            let dyScale = dy * 1.5;
            let dist = dx * dx + dyScale * dyScale;
            if (dist < minDist) {
                minDist = dist;
                bestId = centroids[i].id;
            }
        }
        if (bestId) {
            dynamicBlockCounts.set(bestId, dynamicBlockCounts.get(bestId) + 1);
        }
    });

    const blocks = Array.from(dynamicBlockCounts.keys());
    const xSharpness = [];
    const yCrimes = [];
    const labels = [];
    const threshold = analysis.thresholdValue;

    function getBlockName(bId) {
        if (!phState.properties || !phState.properties.features) return `Block: ${bId}`;
        const props = phState.properties.features.filter(f => f.properties && f.properties.block_id === bId);
        if (props.length === 0) return `Block: ${bId}`;
        const streetCounts = {};
        for (const p of props) {
            const sn = p.properties.STREET_NAME;
            if (sn) streetCounts[sn] = (streetCounts[sn] || 0) + 1;
        }
        let bestStreet = null;
        let maxCount = 0;
        for (const [st, count] of Object.entries(streetCounts)) {
            if (count > maxCount) { maxCount = count; bestStreet = st; }
        }
        return bestStreet ? `${bestStreet} (Block ${bId})` : `Block: ${bId}`;
    }

    for (const blockId of blocks) {
        const crimes = dynamicBlockCounts.get(blockId) || 0;
        const sharpness = phState.analysisBase.blockMaxEdgeWeight.get(blockId) || 0;
        xSharpness.push(sharpness);
        yCrimes.push(crimes);
        const blockName = getBlockName(blockId);
        const labelHeader = selectedTypes.includes('Break and Enter Residential/Other') && selectedTypes.includes('Break and Enter Commercial')
            ? 'Break and Enter' : selectedTypes[0];
        labels.push(`<b>${blockName}</b><br>${labelHeader}: ${crimes}<br>Max Sharpness: ${sharpness.toFixed(3)}`);
    }

    // ── Box plot data (edge/segment-level from HUNDRED_BLOCK server join) ──
    const adjacency = phState.adjacency;
    const boundaryCrimesPlot = (adjacency?.boundary_edges || []).map(e => e.crime_count || 0);
    const interiorCrimesPlot = (adjacency?.interior_edges || []).map(e => e.crime_count || 0);

    // ── Scatter Plot ─────────────────────
    const traceScatter = {
        x: xSharpness,
        y: yCrimes,
        mode: 'markers',
        type: 'scatter',
        text: labels,
        marker: {
            size: 6,
            color: xSharpness,
            colorscale: 'Viridis',
            opacity: 0.7,
            line: { width: 0.5, color: '#1e293b' }
        }
    };

    // Trendline
    const meanX = xSharpness.reduce((a, b) => a + b, 0) / xSharpness.length;
    const meanY = yCrimes.reduce((a, b) => a + b, 0) / yCrimes.length;

    // basic linear regression
    let num = 0, den = 0;
    for (let i = 0; i < xSharpness.length; i++) {
        num += (xSharpness[i] - meanX) * (yCrimes[i] - meanY);
        den += (xSharpness[i] - meanX) ** 2;
    }
    const slope = den === 0 ? 0 : num / den;
    const intercept = meanY - slope * meanX;

    let minX = Math.min(...xSharpness);
    let maxX = Math.max(...xSharpness);
    if (!isFinite(minX) || !isFinite(maxX)) { minX = 0; maxX = 1; }

    const traceLine = {
        x: [minX, maxX],
        y: [intercept + slope * minX, intercept + slope * maxX],
        mode: 'lines',
        type: 'scatter',
        name: 'Trend',
        line: { color: '#fbbf24', width: 2, dash: 'dash' }
    };

    const layoutScatter = {
        title: { text: 'Crime Incidence vs. Maximum Boundary Sharpness', font: { color: '#e2e8f0', family: 'Outfit', size: 14 } },
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        margin: { l: 50, r: 20, t: 40, b: 40 },
        xaxis: {
            title: 'Block Max Sharpness (ε)',
            color: '#cbd5e1',
            gridcolor: 'rgba(148,163,184,0.2)'
        },
        yaxis: {
            title: 'Total Crime Count',
            color: '#cbd5e1',
            gridcolor: 'rgba(148,163,184,0.2)'
        },
        showlegend: false
    };

    Plotly.newPlot('plotly-scatter', [traceScatter, traceLine], layoutScatter, { displayModeBar: false });

    // ── Box Plot ───────────────────────
    const boundaryForBox = boundaryCrimesPlot;
    const interiorForBox = interiorCrimesPlot;

    // Compute medians
    function median(arr) {
        if (!arr.length) return 0;
        const sorted = [...arr].sort((a, b) => a - b);
        const mid = Math.floor(sorted.length / 2);
        return sorted.length % 2 !== 0 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
    }
    const medianBoundary = median(boundaryCrimesPlot);
    const medianInterior = median(interiorCrimesPlot);
    const medianRatio = medianInterior > 0 ? (medianBoundary / medianInterior) : 0;

    const traceBoxBoundary = {
        y: boundaryForBox,
        type: 'box',
        name: 'Boundary segments (≥ ε₂)',
        marker: { color: '#ef4444' },
        boxmean: true
    };

    const traceBoxInterior = {
        y: interiorForBox,
        type: 'box',
        name: 'Interior segments (< ε₂)',
        marker: { color: '#3b82f6' },
        boxmean: true
    };

    const boxAnnotations = [
        {
            x: 'Boundary segments (≥ ε₂)',
            y: medianBoundary,
            xref: 'x',
            yref: 'y',
            text: `Median: ${medianBoundary.toFixed(1)}`,
            showarrow: true,
            arrowhead: 0,
            ax: 55,
            ay: -30,
            font: { color: '#fca5a5', size: 11, family: 'Outfit' },
            bgcolor: 'rgba(30,41,59,0.85)',
            borderpad: 3
        },
        {
            x: 'Interior segments (< ε₂)',
            y: medianInterior,
            xref: 'x',
            yref: 'y',
            text: `Median: ${medianInterior.toFixed(1)}`,
            showarrow: true,
            arrowhead: 0,
            ax: 55,
            ay: -30,
            font: { color: '#93c5fd', size: 11, family: 'Outfit' },
            bgcolor: 'rgba(30,41,59,0.85)',
            borderpad: 3
        }
    ];

    const layoutBox = {
        title: { text: 'Crime Distribution: Boundary vs. Interior Segments', font: { color: '#e2e8f0', family: 'Outfit', size: 14 } },
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        margin: { l: 60, r: 20, t: 50, b: 40 },
        yaxis: {
            title: { text: 'Crime Count per Segment', font: { size: 12, color: '#94a3b8' } },
            color: '#cbd5e1',
            gridcolor: 'rgba(148,163,184,0.15)',
            tickfont: { size: 11 },
            rangemode: 'tozero'
        },
        xaxis: {
            color: '#cbd5e1',
            tickfont: { size: 11 }
        },
        annotations: boxAnnotations,
        showlegend: false
    };

    Plotly.newPlot('plotly-boxplot', [traceBoxBoundary, traceBoxInterior], layoutBox, { displayModeBar: false });

    // Populate summary div below the chart
    const summaryEl = document.getElementById('boxplot-summary');
    if (summaryEl) {
        const zeroBCount = boundaryCrimesPlot.filter(v => v === 0).length;
        const zeroICount = interiorCrimesPlot.filter(v => v === 0).length;
        summaryEl.innerHTML = `
            <div style="display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
                <div>
                    <span style="color: #f87171; font-weight: 600;">Boundary median:</span>
                    <span style="color: #f8fafc; font-weight: 700;">${medianBoundary.toFixed(1)}</span> crimes/segment
                </div>
                <div>
                    <span style="color: #60a5fa; font-weight: 600;">Interior median:</span>
                    <span style="color: #f8fafc; font-weight: 700;">${medianInterior.toFixed(1)}</span> crimes/segment
                </div>
                <div>
                    <span style="color: #fbbf24; font-weight: 600;">Median ratio:</span>
                    <span style="color: #f8fafc; font-weight: 700;">${medianRatio.toFixed(2)}×</span>
                </div>
            </div>
            <div style="margin-top: 6px; font-size: 0.75rem; color: #64748b;">
                ${zeroBCount} boundary and ${zeroICount} interior segments have 0 crimes (included as-is).
                Crime counts come from HUNDRED_BLOCK segment-level join (server-computed).
            </div>
        `;
    }

    // ── Sharpness Quintile Chart ─────────────────────────────────────────────
    // Divide all segments by sharpness quintile, show mean crime count per quintile.
    // This directly tests the Brantingham gradient hypothesis.
    const allEdges = [
        ...(adjacency?.boundary_edges || []),
        ...(adjacency?.interior_edges || [])
    ];
    if (allEdges.length >= 5) {
        const sorted = [...allEdges].sort((a, b) => a.w - b.w);
        const N = sorted.length;
        const Q = 5;
        const quintileLabels = ['Q1 (lowest)', 'Q2', 'Q3', 'Q4', 'Q5 (highest)'];
        const quintileMeans = [];
        const quintileCounts = [];
        for (let q = 0; q < Q; q++) {
            const start = Math.floor(N * q / Q);
            const end = Math.floor(N * (q + 1) / Q);
            const slice = sorted.slice(start, end);
            const total = slice.reduce((s, e) => s + (e.crime_count || 0), 0);
            quintileMeans.push(slice.length > 0 ? total / slice.length : 0);
            quintileCounts.push(slice.length);
        }

        const traceQuintile = {
            x: quintileLabels,
            y: quintileMeans,
            type: 'bar',
            marker: {
                color: ['#3b82f6', '#6366f1', '#8b5cf6', '#d97706', '#ef4444'],
                opacity: 0.8
            },
            text: quintileMeans.map((v, i) => `${v.toFixed(2)} crimes<br>(n=${quintileCounts[i]})`),
            textposition: 'outside',
            hoverinfo: 'text'
        };

        const layoutQ = {
            title: { text: 'Mean Crime Count by Sharpness Quintile (Brantingham Gradient Test)', font: { color: '#e2e8f0', family: 'Outfit', size: 13 } },
            paper_bgcolor: 'rgba(0,0,0,0)',
            plot_bgcolor: 'rgba(0,0,0,0)',
            margin: { l: 55, r: 20, t: 50, b: 55 },
            xaxis: {
                title: { text: 'Sharpness Quintile (Q1=lowest, Q5=highest contrast)', font: { size: 11, color: '#94a3b8' } },
                color: '#cbd5e1', tickfont: { size: 11 }
            },
            yaxis: {
                title: { text: 'Mean crimes per segment', font: { size: 11, color: '#94a3b8' } },
                color: '#cbd5e1',
                gridcolor: 'rgba(148,163,184,0.15)',
                tickfont: { size: 11 },
                rangemode: 'tozero'
            },
            showlegend: false
        };

        const qContainer = document.getElementById('plotly-quintile');
        if (qContainer) Plotly.newPlot('plotly-quintile', [traceQuintile], layoutQ, { displayModeBar: false });
    }
}

// ── Edge-Level Sharpness vs Crime Correlation (HUNDRED_BLOCK data) ──────────
function buildEdgeCrimeCorrelationHTML() {
    return getEpsContextBanner('recompute') + `
        <div class="math-panel">
            <div class="math-title">Edge Sharpness vs. Crime Count (Per-Segment, HUNDRED_BLOCK Join)</div>
            <div class="math-body">
                Each point represents a single <strong>street segment (edge)</strong> between two city blocks.
                The x-axis shows the <em>boundary sharpness weight</em> w(A,B) = √(α·Δv² + β·Δa² + γ·Δz²),
                and the y-axis shows the <strong>number of crimes mapped to that segment</strong> via the
                HUNDRED_BLOCK direct join.
                <br><br>
                <strong>Red points</strong> = boundary segments (w ≥ ε₂).
                <strong>Blue points</strong> = interior segments (w < ε₂).
                The dashed line is a linear regression trendline.
            </div>
        </div>
        <div id="plotly-edge-scatter" style="height: 420px; background: rgba(30,41,59,0.5); border-radius: 8px; padding: 10px;"></div>
        <div id="edge-correl-summary" style="background: rgba(30,41,59,0.6); border: 1px solid rgba(148,163,184,0.15); border-radius: 8px; padding: 14px 18px; margin-top: 14px; font-family: 'Outfit', sans-serif; font-size: 0.85rem; color: #cbd5e1;"></div>
    `;
}

function renderEdgeCrimeCorrelation() {
    const adjacency = phState.adjacency;
    if (!adjacency) return;

    const boundaryEdges = adjacency.boundary_edges || [];
    const interiorEdges = adjacency.interior_edges || [];

    // Collect all edges with sharpness + crime count
    const bX = [], bY = [], bText = [];
    const iX = [], iY = [], iText = [];

    boundaryEdges.forEach(e => {
        bX.push(e.w);
        bY.push(e.crime_count || 0);
        bText.push(`Blocks ${e.a}–${e.b}<br>Sharpness: ${e.w.toFixed(4)}<br>Crimes: ${e.crime_count || 0}<br><b>BOUNDARY</b>`);
    });

    interiorEdges.forEach(e => {
        iX.push(e.w);
        iY.push(e.crime_count || 0);
        iText.push(`Blocks ${e.a}–${e.b}<br>Sharpness: ${e.w.toFixed(4)}<br>Crimes: ${e.crime_count || 0}<br>Interior`);
    });

    const allX = [...bX, ...iX];
    const allY = [...bY, ...iY];

    // Linear regression on all edges
    const n = allX.length;
    const meanX = allX.reduce((a, b) => a + b, 0) / n;
    const meanY = allY.reduce((a, b) => a + b, 0) / n;
    let num = 0, denX = 0, denY = 0;
    for (let i = 0; i < n; i++) {
        const dx = allX[i] - meanX;
        const dy = allY[i] - meanY;
        num += dx * dy;
        denX += dx * dx;
        denY += dy * dy;
    }
    const slope = denX === 0 ? 0 : num / denX;
    const intercept = meanY - slope * meanX;
    const pearsonR = (denX > 0 && denY > 0) ? num / Math.sqrt(denX * denY) : 0;

    // Spearman rank correlation
    function rankArray(arr) {
        const indexed = arr.map((v, i) => ({ v, i }));
        indexed.sort((a, b) => a.v - b.v);
        const ranks = new Array(arr.length);
        for (let k = 0; k < indexed.length; k++) {
            ranks[indexed[k].i] = k + 1;
        }
        return ranks;
    }
    const ranksX = rankArray(allX);
    const ranksY = rankArray(allY);
    const rankMeanX = ranksX.reduce((a, b) => a + b, 0) / n;
    const rankMeanY = ranksY.reduce((a, b) => a + b, 0) / n;
    let sNum = 0, sDenX = 0, sDenY = 0;
    for (let i = 0; i < n; i++) {
        const dx = ranksX[i] - rankMeanX;
        const dy = ranksY[i] - rankMeanY;
        sNum += dx * dy;
        sDenX += dx * dx;
        sDenY += dy * dy;
    }
    const spearmanRho = (sDenX > 0 && sDenY > 0) ? sNum / Math.sqrt(sDenX * sDenY) : 0;

    // Boundary vs interior means
    const boundaryMean = bY.length > 0 ? bY.reduce((a, b) => a + b, 0) / bY.length : 0;
    const interiorMean = iY.length > 0 ? iY.reduce((a, b) => a + b, 0) / iY.length : 0;

    // Traces
    const traceBoundary = {
        x: bX, y: bY,
        mode: 'markers',
        type: 'scatter',
        name: `Boundary (${bX.length})`,
        text: bText,
        hoverinfo: 'text',
        marker: {
            size: 5,
            color: '#ef4444',
            opacity: 0.65,
            line: { width: 0.3, color: '#1e293b' }
        }
    };

    const traceInterior = {
        x: iX, y: iY,
        mode: 'markers',
        type: 'scatter',
        name: `Interior (${iX.length})`,
        text: iText,
        hoverinfo: 'text',
        marker: {
            size: 4,
            color: '#3b82f6',
            opacity: 0.45,
            line: { width: 0.3, color: '#1e293b' }
        }
    };

    // Trendline
    let minX = Math.min(...allX);
    let maxX = Math.max(...allX);
    if (!isFinite(minX)) minX = 0;
    if (!isFinite(maxX)) maxX = 1;

    const traceTrend = {
        x: [minX, maxX],
        y: [intercept + slope * minX, intercept + slope * maxX],
        mode: 'lines',
        type: 'scatter',
        name: `Trend (r=${pearsonR.toFixed(3)})`,
        line: { color: '#fbbf24', width: 2.5, dash: 'dash' }
    };

    // ε₂ threshold line
    const eps2Val = adjacency.stats?.epsilon2_value || 0;

    const layout = {
        title: { text: 'Per-Segment Sharpness vs. Crime Count', font: { color: '#e2e8f0', family: 'Outfit', size: 14 } },
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        margin: { l: 60, r: 25, t: 50, b: 55 },
        xaxis: {
            title: { text: 'Edge Sharpness w(A,B)', font: { size: 12, color: '#94a3b8' } },
            color: '#cbd5e1',
            gridcolor: 'rgba(148,163,184,0.12)',
            tickfont: { size: 11 },
            zeroline: false
        },
        yaxis: {
            title: { text: 'HUNDRED_BLOCK Crimes on Segment', font: { size: 12, color: '#94a3b8' } },
            color: '#cbd5e1',
            gridcolor: 'rgba(148,163,184,0.12)',
            tickfont: { size: 11 },
            rangemode: 'tozero'
        },
        legend: {
            x: 0.01, y: 0.99,
            bgcolor: 'rgba(30,41,59,0.8)',
            font: { color: '#cbd5e1', size: 11 }
        },
        shapes: [{
            type: 'line',
            x0: eps2Val, x1: eps2Val,
            y0: 0, y1: 1,
            xref: 'x', yref: 'paper',
            line: { color: '#22c55e', width: 1.5, dash: 'dot' }
        }],
        annotations: [{
            x: eps2Val,
            y: 1.02,
            xref: 'x', yref: 'paper',
            text: `ε₂ = ${eps2Val.toFixed(3)}`,
            showarrow: false,
            font: { color: '#22c55e', size: 10, family: 'Outfit' }
        }]
    };

    Plotly.newPlot('plotly-edge-scatter', [traceInterior, traceBoundary, traceTrend], layout, { displayModeBar: false });

    // Summary
    const summaryEl = document.getElementById('edge-correl-summary');
    if (summaryEl) {
        summaryEl.innerHTML = `
            <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; margin-bottom: 10px;">
                <div style="text-align: center; padding: 10px; background: rgba(239,68,68,0.08); border-radius: 6px; border: 1px solid rgba(239,68,68,0.2);">
                    <div style="font-size: 0.7rem; color: #94a3b8; margin-bottom: 4px;">Boundary Mean</div>
                    <div style="font-size: 1.2rem; font-weight: 700; color: #f87171;">${boundaryMean.toFixed(2)}</div>
                    <div style="font-size: 0.65rem; color: #64748b;">crimes/segment</div>
                </div>
                <div style="text-align: center; padding: 10px; background: rgba(59,130,246,0.08); border-radius: 6px; border: 1px solid rgba(59,130,246,0.2);">
                    <div style="font-size: 0.7rem; color: #94a3b8; margin-bottom: 4px;">Interior Mean</div>
                    <div style="font-size: 1.2rem; font-weight: 700; color: #60a5fa;">${interiorMean.toFixed(2)}</div>
                    <div style="font-size: 0.65rem; color: #64748b;">crimes/segment</div>
                </div>
                <div style="text-align: center; padding: 10px; background: rgba(251,191,36,0.08); border-radius: 6px; border: 1px solid rgba(251,191,36,0.2);">
                    <div style="font-size: 0.7rem; color: #94a3b8; margin-bottom: 4px;">Concentration Ratio</div>
                    <div style="font-size: 1.2rem; font-weight: 700; color: #fbbf24;">${interiorMean > 0 ? (boundaryMean / interiorMean).toFixed(2) : '∞'}x</div>
                    <div style="font-size: 0.65rem; color: #64748b;">boundary / interior</div>
                </div>
            </div>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
                <div style="padding: 8px 12px; background: rgba(255,255,255,0.03); border-radius: 6px;">
                    <span style="color: #94a3b8;">Pearson r:</span>
                    <span style="color: #f8fafc; font-weight: 600; margin-left: 4px;">${pearsonR.toFixed(4)}</span>
                    <span style="color: #64748b; font-size: 0.75rem; margin-left: 4px;">(linear)</span>
                </div>
                <div style="padding: 8px 12px; background: rgba(255,255,255,0.03); border-radius: 6px;">
                    <span style="color: #94a3b8;">Spearman ρ:</span>
                    <span style="color: #f8fafc; font-weight: 600; margin-left: 4px;">${spearmanRho.toFixed(4)}</span>
                    <span style="color: #64748b; font-size: 0.75rem; margin-left: 4px;">(rank)</span>
                </div>
            </div>
            <div style="margin-top: 10px; font-size: 0.75rem; color: #64748b; line-height: 1.4;">
                Total segments: <b style="color:#cbd5e1">${n.toLocaleString()}</b> |
                Boundary: <b style="color:#f87171">${bX.length.toLocaleString()}</b> |
                Interior: <b style="color:#60a5fa">${iX.length.toLocaleString()}</b> |
                Slope: <b style="color:#cbd5e1">${slope.toFixed(3)}</b> crimes per unit sharpness
            </div>
        `;
    }
}

async function renderWeightsOptimizationPlots() {
    // Prefer the already-computed state so we match the current map exactly.
    // Fall back to the slider value only if the state hasn't been loaded yet.
    const stats = phState.adjacency?.stats || {};
    const eps1_m = stats.epsilon1_m
        || parseFloat(document.getElementById('epsilon1-threshold')?.value || 0);
    const eps2_threshold = parseFloat(document.getElementById('epsilon2-threshold')?.value || 0.75);
    const selectedCrimeTypes = typeof window.getSelectedCrimeTypes === 'function'
        ? window.getSelectedCrimeTypes()
        : [];

    if (!eps1_m || eps1_m <= 0) {
        const loadingEl = document.getElementById('optimization-loading');
        if (loadingEl) loadingEl.innerHTML = 'Run a computation first (ε₁ not set).';
        return;
    }

    try {
        const res = await fetch('http://127.0.0.1:8001/api/optimize-weights', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                epsilon1_m: eps1_m,
                epsilon2_threshold: eps2_threshold,
                alpha: 0.33, beta: 0.33, gamma: 0.34,
                crime_types: selectedCrimeTypes
            })
        });

        if (!res.ok) throw new Error("Server response not ok.");
        const data = await res.json();

        const loadingEl = document.getElementById('optimization-loading');
        if (!loadingEl) return; // Modal closed

        loadingEl.style.display = 'none';
        document.getElementById('simplex-results-container').style.display = 'flex';

        // Ternary Plot Data
        const results = data.results || [];
        if (!results.length) return;

        const maxRatio = Math.max(...results.map(r => r.normalized_ratio || 0));
        const robustnessThreshold = maxRatio * 0.75;

        let robustCount = 0;

        const a_vals = [];
        const b_vals = [];
        const c_vals = [];
        const ratios = [];
        const texts = [];

        results.forEach(r => {
            a_vals.push(r.alpha);
            b_vals.push(r.beta);
            c_vals.push(r.gamma);
            const ratio = r.normalized_ratio || 0;
            ratios.push(ratio);

            if (ratio >= robustnessThreshold) {
                robustCount++;
            }

            texts.push(`α: ${r.alpha.toFixed(2)}<br>β: ${r.beta.toFixed(2)}<br>γ: ${r.gamma.toFixed(2)}<br>Ratio: <b>${ratio.toFixed(4)}</b>`);
        });

        document.getElementById('robustness-summary').innerHTML =
            `<b>${robustCount} / ${results.length}</b> iterations (${((robustCount / results.length) * 100).toFixed(1)}%) landed in the Robustness Region (≥ 75% of max target ratio).`;

        const ternaryTrace = {
            type: 'scatterternary',
            mode: 'markers',
            a: a_vals,
            b: b_vals,
            c: c_vals,
            text: texts,
            hoverinfo: 'text',
            marker: {
                symbol: 'circle',
                color: ratios,
                colorscale: 'Plasma', // matches epsilon color concept
                size: 14,
                line: { width: 1, color: 'rgba(255,255,255,0.4)' },
                colorbar: { title: 'Target Ratio' }
            }
        };

        const ternaryLayout = {
            ternary: {
                sum: 1,
                aaxis: { title: 'α (Value)', tickformat: ".1f", titlefont: { color: '#e2e8f0' } },
                baxis: { title: 'β (Age)', tickformat: ".1f", titlefont: { color: '#e2e8f0' } },
                caxis: { title: 'γ (Zoning)', tickformat: ".1f", titlefont: { color: '#e2e8f0' } },
                bgcolor: 'rgba(0,0,0,0)'
            },
            paper_bgcolor: 'rgba(0,0,0,0)',
            plot_bgcolor: 'rgba(0,0,0,0)',
            font: { color: '#cbd5e1', family: 'Outfit' },
            margin: { t: 40, b: 30, l: 30, r: 30 }
        };

        Plotly.newPlot('plotly-ternary', [ternaryTrace], ternaryLayout, { displayModeBar: false });

        // Populate Benchmarks Table
        const tbody = document.getElementById('benchmark-table-body');
        const benchDefs = [
            { name: "Equal Weighting (Baseline)", obj: data.baseline_eq },
            { name: "Property value only", obj: data.prop_val_only },
            { name: "Building age only", obj: data.age_only },
            { name: "Zoning only", obj: data.zone_only }
        ];

        let rowsHtml = '';
        benchDefs.forEach(b => {
            const o = b.obj;
            if (!o) return;
            rowsHtml += `<tr style="border-bottom: 1px solid rgba(255,255,255,0.05);">
                <td style="padding: 10px;"><strong>${b.name}</strong></td>
                <td style="padding: 10px; color: #5eead4;">(${o.alpha.toFixed(2)}, ${o.beta.toFixed(2)}, ${o.gamma.toFixed(2)})</td>
                <td style="padding: 10px; color: #cbd5e1;">${o.boundary_blocks} / ${o.interior_blocks}</td>
                <td style="padding: 10px; color: #f472b6;">${o.raw_boundary_crimes}</td>
                <td style="padding: 10px; color: #fbbf24; font-weight: bold;">${(o.normalized_ratio || 0).toFixed(4)}</td>
             </tr>`;
        });

        tbody.innerHTML = rowsHtml;

        // ── Crime Rate Comparison Chart — Boundary vs Interior per Weight Case ──
        const crimeCompContainer = document.getElementById('plotly-crime-comparison');
        const ratioContainer = document.getElementById('plotly-ratio-comparison');
        if (crimeCompContainer && ratioContainer) {
            const configs = [
                { label: 'Equal (α=β=γ=0.33)', obj: data.baseline_eq },
                { label: 'Value only (α=1)', obj: data.prop_val_only },
                { label: 'Age only (β=1)', obj: data.age_only },
                { label: 'Zone only (γ=1)', obj: data.zone_only }
            ].filter(c => c.obj);

            const labels = configs.map(c => c.label);
            // Use per-segment means: total crimes / segment count
            const boundaryMeans = configs.map(c =>
                c.obj.boundary_blocks > 0 ? c.obj.raw_boundary_crimes / c.obj.boundary_blocks : 0
            );
            const interiorMeans = configs.map(c =>
                c.obj.interior_blocks > 0 ? c.obj.raw_interior_crimes / c.obj.interior_blocks : 0
            );
            // Use the server's normalized_ratio directly (it IS bc/bb / ic/ib)
            const ratios = configs.map(c => c.obj.normalized_ratio || 0);

            const traceBoundary = {
                x: labels,
                y: boundaryMeans,
                name: 'Boundary (mean crimes/segment)',
                type: 'bar',
                marker: { color: 'rgba(239,68,68,0.78)', line: { color: 'rgba(185,28,28,0.8)', width: 1 } },
                text: boundaryMeans.map(v => v.toFixed(3)),
                textposition: 'outside',
                textfont: { color: '#fca5a5', size: 11 },
                customdata: configs.map(c => [c.obj.boundary_blocks, c.obj.raw_boundary_crimes]),
                hovertemplate: '<b>%{x}</b><br>Boundary mean: %{y:.3f} crimes/seg<br>Segments: %{customdata[0]}<br>Total crimes: %{customdata[1]}<extra></extra>'
            };

            const traceInterior = {
                x: labels,
                y: interiorMeans,
                name: 'Interior (mean crimes/segment)',
                type: 'bar',
                marker: { color: 'rgba(59,130,246,0.72)', line: { color: 'rgba(29,78,216,0.8)', width: 1 } },
                text: interiorMeans.map(v => v.toFixed(3)),
                textposition: 'outside',
                textfont: { color: '#93c5fd', size: 11 },
                customdata: configs.map(c => [c.obj.interior_blocks, c.obj.raw_interior_crimes]),
                hovertemplate: '<b>%{x}</b><br>Interior mean: %{y:.3f} crimes/seg<br>Segments: %{customdata[0]}<br>Total crimes: %{customdata[1]}<extra></extra>'
            };

            const layoutComp = {
                barmode: 'group',
                paper_bgcolor: 'rgba(0,0,0,0)',
                plot_bgcolor: 'rgba(0,0,0,0)',
                font: { color: '#cbd5e1', family: 'Outfit', size: 11 },
                margin: { t: 30, b: 80, l: 60, r: 20 },
                yaxis: {
                    title: 'Mean crimes per segment',
                    gridcolor: 'rgba(148,163,184,0.2)',
                    rangemode: 'tozero',
                    titlefont: { color: '#94a3b8' }
                },
                xaxis: { tickfont: { size: 10 } },
                legend: { orientation: 'h', x: 0, y: 1.12, font: { size: 10 } },
                shapes: [{
                    type: 'line', x0: -0.5, x1: labels.length - 0.5,
                    y0: 0, y1: 0, xref: 'x', yref: 'y',
                    line: { color: 'rgba(148,163,184,0.3)', width: 1 }
                }]
            };

            Plotly.newPlot('plotly-crime-comparison', [traceBoundary, traceInterior], layoutComp, { displayModeBar: false });

            // Ratio chart (boundary / interior)
            const traceRatio = {
                x: labels,
                y: ratios,
                type: 'bar',
                marker: {
                    color: ratios.map(r => r >= 1 ? 'rgba(234,179,8,0.78)' : 'rgba(148,163,184,0.5)'),
                    line: { color: ratios.map(r => r >= 1 ? 'rgba(161,98,7,0.9)' : 'rgba(100,116,139,0.6)'), width: 1 }
                },
                text: ratios.map(v => v.toFixed(3) + '×'),
                textposition: 'outside',
                textfont: { color: '#fde68a', size: 11 }
            };

            const layoutRatio = {
                paper_bgcolor: 'rgba(0,0,0,0)',
                plot_bgcolor: 'rgba(0,0,0,0)',
                font: { color: '#cbd5e1', family: 'Outfit', size: 11 },
                margin: { t: 30, b: 80, l: 60, r: 20 },
                yaxis: {
                    title: 'Boundary / Interior ratio',
                    gridcolor: 'rgba(148,163,184,0.2)',
                    rangemode: 'tozero',
                    titlefont: { color: '#94a3b8' }
                },
                xaxis: { tickfont: { size: 10 } },
                shapes: [{
                    type: 'line', x0: -0.5, x1: labels.length - 0.5,
                    y0: 1, y1: 1, xref: 'x', yref: 'y',
                    line: { color: '#22c55e', width: 1.5, dash: 'dot' }
                }],
                annotations: [{
                    x: labels.length - 0.5, y: 1, xref: 'x', yref: 'y',
                    text: 'ratio = 1 (no effect)', showarrow: false,
                    font: { color: '#22c55e', size: 9 }, xanchor: 'right', yanchor: 'bottom'
                }]
            };

            Plotly.newPlot('plotly-ratio-comparison', [traceRatio], layoutRatio, { displayModeBar: false });
        }

    } catch (e) {
        const loadingEl = document.getElementById('optimization-loading');
        if (loadingEl) {
            loadingEl.style.color = '#ef4444';
            loadingEl.innerHTML = `Error: ${e.message}`;
        }
        console.error("Optimization failed:", e);
    }
}

// ═══════════════════════════════════════════════════════════════════════════
// Image Export Utilities
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Download a canvas element as a high-res PNG.
 * @param {HTMLCanvasElement} canvas
 * @param {string} filename - e.g. "ph_diagram.png"
 */
function downloadCanvasAsPNG(canvas, filename) {
    // Create a high-res offscreen canvas (3x for publication quality)
    const scale = 3;
    const offscreen = document.createElement('canvas');
    offscreen.width = canvas.clientWidth * scale;
    offscreen.height = canvas.clientHeight * scale;
    const ctx = offscreen.getContext('2d');
    ctx.scale(scale, scale);

    // Re-render at high resolution
    const chartType = canvas.dataset.chart;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    if (chartType === 'persistence-diagram') drawPersistenceDiagram(ctx, w, h);
    else if (chartType === 'betti-curves') drawBettiCurves(ctx, w, h);
    else if (chartType === 'barcode-h0') drawBarcode(ctx, w, h, 'H0');
    else if (chartType === 'barcode-h1') drawBarcode(ctx, w, h, 'H1');
    else if (chartType === 'persistence-landscape') drawPersistenceLandscape(ctx, w, h);
    else if (chartType === 'persistence-image') drawPersistenceImage(ctx, w, h);
    else if (chartType === 'euler-curve') drawEulerCurve(ctx, w, h);

    const link = document.createElement('a');
    link.download = filename;
    link.href = offscreen.toDataURL('image/png');
    link.click();
}

/**
 * Download a Plotly chart as a high-res PNG.
 * @param {string} divId - ID of the Plotly container div
 * @param {string} filename
 */
function downloadPlotlyAsPNG(divId, filename) {
    const el = document.getElementById(divId);
    if (!el) return;
    Plotly.downloadImage(el, {
        format: 'png',
        width: 1600,
        height: 900,
        filename: filename.replace('.png', ''),
        scale: 3
    });
}

/**
 * Export all currently renderable charts as PNGs (triggers sequential downloads).
 */
function exportAllCharts() {
    const modal = document.getElementById('analysis-modal');
    const wasHidden = modal.style.display === 'none';

    // Export Canvas-based charts by opening each modal temporarily
    const canvasModals = [
        { type: 'persistence-diagram', filename: 'H0_persistence_distribution' },
        { type: 'betti-curves', filename: 'betti_curve_beta0' },
        { type: 'barcode', filename: 'H0_barcode' },
    ];

    const plotlyModals = [
        {
            type: 'spatial-crime-correlation',
            plots: [
                { id: 'plotly-scatter', filename: 'crime_vs_sharpness_scatter' },
                { id: 'plotly-boxplot', filename: 'boundary_vs_interior_boxplot' },
                { id: 'plotly-quintile', filename: 'sharpness_quintile_barchart' },
            ]
        },
        {
            type: 'edge-crime-correlation',
            plots: [
                { id: 'plotly-edge-scatter', filename: 'edge_sharpness_vs_crime' },
            ]
        },
        {
            type: 'weights-optimization',
            plots: [
                { id: 'plotly-ternary', filename: 'weight_sensitivity_ternary' },
                { id: 'plotly-crime-comparison', filename: 'boundary_interior_crime_comparison' },
                { id: 'plotly-ratio-comparison', filename: 'boundary_interior_ratio' },
            ]
        },
    ];

    let delay = 0;
    const STEP = 800;

    // Export canvas charts
    canvasModals.forEach(({ type, filename }) => {
        setTimeout(() => {
            openModal(type);
            setTimeout(() => {
                const canvases = document.querySelectorAll('#analysis-modal-body canvas[data-chart]');
                canvases.forEach(canvas => {
                    downloadCanvasAsPNG(canvas, `${filename}.png`);
                });
            }, 300);
        }, delay);
        delay += STEP;
    });

    // Export plotly charts
    plotlyModals.forEach(({ type, plots }) => {
        setTimeout(() => {
            openModal(type);
            setTimeout(() => {
                plots.forEach(({ id, filename }, idx) => {
                    setTimeout(() => downloadPlotlyAsPNG(id, filename), idx * 500);
                });
            }, 1500); // Plotly needs more time to render
        }, delay);
        delay += 2500 + plots.length * 500;
    });

    // Close modal after all exports
    setTimeout(() => {
        if (wasHidden) closeModal();
    }, delay + 500);
}

// Expose globally
window.exportAllCharts = exportAllCharts;

// ═══════════════════════════════════════════════════════════════════════════
// App Startup
// ═══════════════════════════════════════════════════════════════════════════
function startApp() {
    loadAll();
}
if (document.readyState === 'loading') {
    window.addEventListener('DOMContentLoaded', startApp);
} else {
    startApp();
}

