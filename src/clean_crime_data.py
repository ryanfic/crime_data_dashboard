"""
Data Cleaning Script for Break and Enter Crimes
================================================
This script loads crime data from all Vancouver neighborhoods (2020),
filters for break and enter crimes only, and cleans the data by removing
invalid coordinates and handling missing values.

Author: Data Analysis Pipeline
Date: 2026-02-01
"""

import pandas as pd
import numpy as np

# ============================================================================
# CONFIGURATION
# ============================================================================

# Input file path
INPUT_FILE = '../crimedata_csv_AllNeighbourhoods_2020/crimedata_csv_AllNeighbourhoods_2020.csv'

# Output file path for cleaned data
OUTPUT_FILE = '../outputs/processed/cleaned_break_enter_data.csv'

# Crime types we're interested in
BREAK_ENTER_TYPES = [
    'Break and Enter Commercial',
    'Break and Enter Residential/Other'
]


# ============================================================================
# DATA LOADING
# ============================================================================

def load_crime_data(filepath):
    """
    Load crime data from CSV file.
    
    Args:
        filepath (str): Path to the CSV file
        
    Returns:
        pd.DataFrame: Raw crime data
    """
    print(f"\n{'='*70}")
    print("LOADING DATA")
    print(f"{'='*70}")
    
    df = pd.read_csv(filepath)
    print(f"✓ Loaded {len(df):,} total crime records")
    print(f"✓ Columns: {', '.join(df.columns.tolist())}")
    
    return df


# ============================================================================
# DATA CLEANING FUNCTIONS
# ============================================================================

def filter_break_enter_crimes(df):
    """
    Filter dataset to include only break and enter crimes.
    
    Args:
        df (pd.DataFrame): Raw crime data
        
    Returns:
        pd.DataFrame: Filtered data containing only break and enter crimes
    """
    print(f"\n{'='*70}")
    print("FILTERING FOR BREAK AND ENTER CRIMES")
    print(f"{'='*70}")
    
    # Show all crime types before filtering
    print("\nCrime type distribution in original data:")
    print(df['TYPE'].value_counts())
    
    # Filter for break and enter crimes
    df_filtered = df[df['TYPE'].isin(BREAK_ENTER_TYPES)].copy()
    
    print(f"\n✓ Filtered to {len(df_filtered):,} break and enter records")
    print(f"  - Break and Enter Commercial: {len(df_filtered[df_filtered['TYPE'] == 'Break and Enter Commercial']):,}")
    print(f"  - Break and Enter Residential/Other: {len(df_filtered[df_filtered['TYPE'] == 'Break and Enter Residential/Other']):,}")
    
    return df_filtered


def clean_coordinates(df):
    """
    Remove records with invalid coordinates.
    
    Many records have X=0.0, Y=0.0 (marked as "OFFSET TO PROTECT PRIVACY")
    These cannot be mapped and must be removed.
    
    Args:
        df (pd.DataFrame): Crime data with potential invalid coordinates
        
    Returns:
        pd.DataFrame: Data with only valid coordinates
    """
    print(f"\n{'='*70}")
    print("CLEANING COORDINATES")
    print(f"{'='*70}")
    
    initial_count = len(df)
    
    # Check for missing values
    missing_x = df['X'].isnull().sum()
    missing_y = df['Y'].isnull().sum()
    print(f"\n✓ Missing X coordinates: {missing_x}")
    print(f"✓ Missing Y coordinates: {missing_y}")
    
    # Check for zero coordinates (privacy-protected locations)
    zero_coords = ((df['X'] == 0.0) & (df['Y'] == 0.0)).sum()
    print(f"✓ Records with (0,0) coordinates (privacy-protected): {zero_coords}")
    
    # Remove records with null or zero coordinates
    df_cleaned = df[
        (df['X'].notnull()) & 
        (df['Y'].notnull()) & 
        (df['X'] != 0.0) & 
        (df['Y'] != 0.0)
    ].copy()
    
    removed_count = initial_count - len(df_cleaned)
    print(f"\n✓ Removed {removed_count:,} records with invalid coordinates")
    print(f"✓ Remaining records: {len(df_cleaned):,}")
    
    return df_cleaned


def clean_neighborhoods(df):
    """
    Handle missing neighborhood values.
    
    Args:
        df (pd.DataFrame): Crime data
        
    Returns:
        pd.DataFrame: Data with neighborhood issues addressed
    """
    print(f"\n{'='*70}")
    print("CLEANING NEIGHBORHOODS")
    print(f"{'='*70}")
    
    missing_neighborhood = df['NEIGHBOURHOOD'].isnull().sum()
    print(f"\n✓ Records with missing neighborhood: {missing_neighborhood}")
    
    if missing_neighborhood > 0:
        # Remove records with missing neighborhoods
        df_cleaned = df[df['NEIGHBOURHOOD'].notnull()].copy()
        print(f"✓ Removed {missing_neighborhood} records with missing neighborhoods")
    else:
        df_cleaned = df.copy()
        print("✓ No missing neighborhoods - no action needed")
    
    # Show neighborhood distribution
    print(f"\n✓ Neighborhood distribution ({len(df_cleaned['NEIGHBOURHOOD'].unique())} unique neighborhoods):")
    neighborhood_counts = df_cleaned['NEIGHBOURHOOD'].value_counts()
    for neighborhood, count in neighborhood_counts.items():
        print(f"  - {neighborhood}: {count:,}")
    
    return df_cleaned


def add_derived_fields(df):
    """
    Add any derived fields that might be useful for visualization.
    
    Args:
        df (pd.DataFrame): Cleaned crime data
        
    Returns:
        pd.DataFrame: Data with additional derived fields
    """
    print(f"\n{'='*70}")
    print("ADDING DERIVED FIELDS")
    print(f"{'='*70}")
    
    # Add a simplified crime category for easier visualization
    df['CRIME_CATEGORY'] = df['TYPE'].apply(
        lambda x: 'Commercial' if 'Commercial' in x else 'Residential/Other'
    )
    
    print(f"✓ Added 'CRIME_CATEGORY' field:")
    print(df['CRIME_CATEGORY'].value_counts())
    
    return df


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """
    Main execution function - orchestrates the entire data cleaning pipeline.
    """
    print("\n" + "="*70)
    print(" BREAK AND ENTER CRIME DATA CLEANING PIPELINE")
    print("="*70)
    
    # Step 1: Load data
    df = load_crime_data(INPUT_FILE)
    
    # Step 2: Filter for break and enter crimes
    df = filter_break_enter_crimes(df)
    
    # Step 3: Clean coordinates
    df = clean_coordinates(df)
    
    # Step 4: Clean neighborhoods
    df = clean_neighborhoods(df)
    
    # Step 5: Add derived fields
    df = add_derived_fields(df)
    
    # Step 6: Save cleaned data
    print(f"\n{'='*70}")
    print("SAVING CLEANED DATA")
    print(f"{'='*70}")
    
    df.to_csv(OUTPUT_FILE, index=False)
    print(f"\n✓ Saved {len(df):,} cleaned records to: {OUTPUT_FILE}")
    
    # Final summary
    print(f"\n{'='*70}")
    print("CLEANING SUMMARY")
    print(f"{'='*70}")
    print(f"✓ Total break and enter crimes with valid locations: {len(df):,}")
    print(f"✓ Data ready for visualization!")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
