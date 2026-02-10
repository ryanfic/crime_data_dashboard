#!/bin/bash

# Installation script for Vancouver Crime Analysis Dashboard
# Run this script to install all required dependencies

echo "🚀 Installing Vancouver Crime Analysis Dashboard Dependencies"
echo "=============================================================="
echo ""

# Check if running in virtual environment
if [[ "$VIRTUAL_ENV" != "" ]]; then
    echo "✅ Virtual environment detected: $VIRTUAL_ENV"
else
    echo "⚠️  WARNING: Not in a virtual environment"
    echo "   Consider activating venv first: source ../venv/bin/activate"
    echo ""
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo ""
echo "📦 Installing Python packages..."
echo ""

# Install packages
pip install -U streamlit plotly pandas geopandas shapely pyproj scikit-learn numpy scipy gudhi folium

echo ""
echo "✅ Installation complete!"
echo ""
echo "🎯 Next step: Run the dashboard"
echo "   cd /Users/tanyaaggarwal/Desktop/A_research/dashboard"
echo "   streamlit run app.py"
echo ""
