"""
Vancouver Block-Level Land Use Profile
=======================================
Fetches the City of Vancouver property tax report via Open Data API,
classifies each parcel using the zoning_district code, derives street 
blocks
from address components, and aggregates to a block-level profile.

Block definition: properties sharing the same street_name and block range
(from_civic_number rounded to the nearest 100, which is standard North 
American
block numbering — 100-199 is one block, 200-299 is the next, etc.).

Output columns per block:
  block_id              street_name + block_range string, e.g. "W GEORGIA 
ST 600"
  street_name
  block_range           lower bound of the 100-unit range
  total_lots            count of distinct PIDs on the block
  total_unique_folio    count of distinct folios (property-level, not 
strata units)

  -- Lot counts by classification --
  lots_single_family
  lots_two_family
  lots_multifamily
  lots_mixed_use        C-2/C-3A/C-5/C-6 family — retail ground floor + 
res above
  lots_commercial_only  C-1, pure commercial with no residential 
permission
  lots_shopping_centre  C-7, C-8
  lots_industrial
  lots_historic_area    HA-1/2/3
  lots_downtown         DD, CWD, DEOD
  lots_cd_unknown       CD-1 — site-specific, needs secondary lookup
  lots_other            everything else (RA, FM, parks, etc.)

  -- Percentages (0.0–100.0) --
  pct_single_family, pct_two_family, pct_multifamily,
  pct_mixed_use, pct_commercial_only, pct_shopping_centre,
  pct_industrial, pct_historic_area, pct_downtown,
  pct_cd_unknown, pct_other

  -- Assessed value summary --
  total_land_value
  total_improvement_value
  median_year_built

Usage:
  python vancouver_block_profile.py
  python vancouver_block_profile.py --street "W GEORGIA ST"
  python vancouver_block_profile.py --out blocks.csv

Requirements:
  pip install requests pandas
"""

import argparse
import sys
import requests
import pandas as pd
from math import floor


# -----------------------------------------------------------------------

# 1.  ZONING CLASSIFICATION LOOKUP
# -----------------------------------------------------------------------


def classify_zone(district: str) -> str:
    """
    Map a zoning_district code to one of the 11 operational categories.
    The district string comes directly from the property tax dataset 
field.
    """
    if not district or pd.isna(district):
        return "other"

    d = str(district).strip().upper()

    # Single-family: RS-x, R1, and new R-series low-density
    if d.startswith("RS") or d.startswith("R1"):
        return "single_family"

    # New 2023+ residential districts (R3 = low-rise, R4 = mid-rise, R5 = 
# high-rise)
    # R3 is townhouse-scale so we treat as multifamily
    if d.startswith("R3") or d.startswith("R4") or d.startswith("R5"):
        return "multifamily"

    # Two-family: RT-x
    if d.startswith("RT"):
        return "two_family"

    # Multiple dwelling: RM-x, FM-1 (False Creek rental)
    if d.startswith("RM") or d.startswith("FM"):
        return "multifamily"

    # Mixed-use commercial (retail ground floor / residential above)
    # C-2 family is the classic high-street mixed-use
    # C-3A is arterial commercial with residential permitted
    # C-5, C-6 are arterial service commercial with residential
    # FC-1, FC-2 are False Creek mixed-use employment
    MIXED_USE_PREFIXES = ("C-2", "C-3", "C-5", "C-6", "FC-")
    if any(d.startswith(p) for p in MIXED_USE_PREFIXES):
        return "mixed_use"

    # MC (industrial-commercial interface) — mixed but employment-focused
    if d.startswith("MC"):
        return "mixed_use"

    # Pure neighbourhood commercial: C-1 only (no residential outright)
    if d == "C-1" or d.startswith("C-1 "):
        return "commercial_only"

    # Shopping centres: C-7 and C-8
    if d.startswith("C-7") or d.startswith("C-8"):
        return "shopping_centre"

    # Industrial: M-x, I-x, IC-x
    if (d.startswith("M-") or d.startswith("M1") or d.startswith("M2")
            or d.startswith("I-") or d.startswith("IC-")):
        return "industrial"

    # Historic areas
    if d.startswith("HA"):
        return "historic_area"

    # Downtown special districts
    if d in ("DD", "CWD", "DEOD", "FCCDD"):
        return "downtown"

    # Comprehensive Development — site-specific, needs secondary lookup
    if d.startswith("CD") or d == "CD-1":
        return "cd_unknown"

    # Limited agriculture
    if d.startswith("RA"):
        return "other"

    return "other"


# -----------------------------------------------------------------------

# 2.  DATA FETCH FROM VANCOUVER OPEN DATA API
# -----------------------------------------------------------------------


BASE_URL = "https://opendata.vancouver.ca/api/explore/v2.1/catalog/datasets"
DATASET  = "property-tax-report"

FIELDS = [
    "pid", "folio", "land_coordinate",
    "zoning_district", "zoning_classification",
    "from_civic_number", "to_civic_number", "street_name",
    "legal_type",
    "current_land_value", "current_improvement_value",
    "year_built", "report_year",
]

def fetch_tax_data(limit: int = 100_000, street_filter: str = None) -> pd.DataFrame: 
# """
#     Page through the property tax report API and return a DataFrame.
#     The API returns max 100 records per call; we loop with offset.
#     """
    all_records = []
    offset = 0
    page_size = 100   # API max per request

    where_clause = ""
    if street_filter:
        # Case-insensitive substring match on street_name
        safe = street_filter.replace("'", "''")
        where_clause = f"upper(street_name) like '%{safe.upper()}%'"

    params_base = {
        "select": ",".join(FIELDS),
        "limit":  page_size,
        "order_by": "street_name,from_civic_number",
    }
    if where_clause:
        params_base["where"] = where_clause

    url = f"{BASE_URL}/{DATASET}/records"

    print(f"Fetching from Vancouver Open Data API ({DATASET})…", 
file=sys.stderr)

    while True:
        params = {**params_base, "offset": offset}
        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  API error at offset {offset}: {e}", 
file=sys.stderr)
            break

        data = resp.json()
        results = data.get("results", [])
        if not results:
            break

        all_records.extend(results)
        total_count = data.get("total_count", 0)

        offset += page_size
        if offset % 5000 == 0:
            print(f"  … {offset:,} / {total_count:,}", file=sys.stderr)

        if offset >= min(limit, total_count):
            break

    print(f"  Fetched {len(all_records):,} records total.", 
file=sys.stderr)
    return pd.DataFrame(all_records)


# -----------------------------------------------------------------------

# 3.  BLOCK ID DERIVATION
# -----------------------------------------------------------------------


def derive_block_id(df: pd.DataFrame) -> pd.DataFrame:
    """
    A North American street block is defined by a street name and a
    100-unit civic number range (100–199, 200–299, etc.).

    For properties where from_civic_number is missing or 0, we fall back
    to to_civic_number.  The block_range is the floor-to-100 of the 
number.
    """
    df = df.copy()

    # Coerce to numeric, NaN if unparseable
    df["from_num"] = pd.to_numeric(df["from_civic_number"], 
errors="coerce")
    df["to_num"]   = pd.to_numeric(df["to_civic_number"],   
errors="coerce")

    # Use from_num preferentially; fall back to to_num
    df["civic_num"] = df["from_num"].fillna(df["to_num"])

    # Block range = floor to nearest 100
    df["block_range"] = (df["civic_num"].fillna(0) // 100 * 
100).astype(int)

    # Clean street name
    df["street_name"] = df["street_name"].fillna("UNKNOWN").str.strip().str.upper()

    # Block ID string
    df["block_id"] = df["street_name"] + " " + df["block_range"].astype(str)

    return df


# -----------------------------------------------------------------------

# 4.  AGGREGATION
# -----------------------------------------------------------------------


CATEGORIES = [
    "single_family", "two_family", "multifamily",
    "mixed_use", "commercial_only", "shopping_centre",
    "industrial", "historic_area", "downtown",
    "cd_unknown", "other",
]

def build_block_profiles(df: pd.DataFrame) -> pd.DataFrame:
    """
    Group parcels by block_id and compute lot counts + percentages
    for each land use category.
    """
    # Apply zoning classifier
    df = df.copy()
    df["use_class"] = df["zoning_district"].apply(classify_zone)

    # Coerce value columns
    df["current_land_value"]        = pd.to_numeric(df["current_land_value"],        errors="coerce")
    df["current_improvement_value"] =  pd.to_numeric(df["current_improvement_value"], errors="coerce")
    df["year_built"]                = pd.to_numeric(df["year_built"],                errors="coerce")

    # --- For counting "lots" we use unique PIDs.
    # A shopping mall that spans several legal parcels will appear as
    # multiple PIDs with the same zoning code on the same block —
    # that's correct behaviour (each lot is counted, but they're all
    # tagged shopping_centre, so pct_shopping_centre approaches 100%).
    # Strata units sharing a folio are counted as one "lot" here because
    # they represent one physical building entry, not separate buildings.
    # If you want to count strata buildings rather than strata units,
    # use unique folio counts instead of unique PIDs.

    records = []

    for block_id, grp in df.groupby("block_id"):
        row = {"block_id": block_id}

        # Extract street info from first record
        row["street_name"]  = grp["street_name"].iloc[0]
        row["block_range"]  = grp["block_range"].iloc[0]

        total_lots = grp["pid"].nunique()
        row["total_lots"]        = total_lots
        row["total_unique_folio"] = grp["folio"].nunique()

        # Count lots per category
        cat_counts = grp.groupby("use_class")["pid"].nunique()

        for cat in CATEGORIES:
            n = int(cat_counts.get(cat, 0))
            row[f"lots_{cat}"] = n
            row[f"pct_{cat}"]  = round(100.0 * n / total_lots, 1) if total_lots > 0 else 0.0

        # Value aggregates
        row["total_land_value"] = grp["current_land_value"].sum(min_count=1)
        row["total_improvement_value"] = grp["current_improvement_value"].sum(min_count=1)
        row["median_year_built"] = grp["year_built"].median()

        records.append(row)

    result = pd.DataFrame(records)

    # Sort by street name then block range for readability
    result = result.sort_values(["street_name", 
"block_range"]).reset_index(drop=True)
    return result


# -----------------------------------------------------------------------

# 5.  REPORTING
# -----------------------------------------------------------------------


def print_summary(blocks: pd.DataFrame, top_n: int = 20):
    """Print a human-readable summary of the most mixed blocks."""
    print(f"\n{'='*72}")
    print(f"  Vancouver Block-Level Land Use Profile")
    print(f"  {len(blocks):,} blocks derived from {blocks['total_lots'].sum():,} lots")
    print(f"{'='*72}\n")

    # City-wide totals
    total_lots = blocks["total_lots"].sum()
    print("City-wide lot totals:")
    for cat in CATEGORIES:
        n = blocks[f"lots_{cat}"].sum()
        pct = 100.0 * n / total_lots if total_lots > 0 else 0
        print(f"  {cat:<20s}  {n:>8,}  ({pct:5.1f}%)")

    print(f"\n--- Top {top_n} most mixed-use blocks (highest pct_mixed_use) ---\n")
    display_cols = [
        "block_id", "total_lots",
        "pct_single_family", "pct_multifamily", "pct_mixed_use",
        "pct_commercial_only", "pct_shopping_centre", "pct_cd_unknown",
    ]
    top = (blocks
           .nlargest(top_n, "pct_mixed_use")[display_cols]
           .to_string(index=False, float_format=lambda x: f"{x:5.1f}"))
    print(top)


# ------------------------------------------------------------------------
# 6.  MAIN
# -----------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Vancouver block-level land use profiler")
    parser.add_argument("--street",  type=str, default=None,help="Filter to a specific street name (substring match)")
    parser.add_argument("--limit",   type=int, default=100_000,help="Max records to fetch (default 100,000)")
    parser.add_argument("--out",     type=str, default="block_profiles.csv", help="Output CSV filename")
    parser.add_argument("--report-year", type=int, default=None, help="Filter to a specific report year (e.g. 2023)")
    args = parser.parse_args()

    # Fetch
    df = fetch_tax_data(limit=args.limit, street_filter=args.street)

    if df.empty:
        print("No records returned. Check your filter or network connection.", file=sys.stderr)
        sys.exit(1)

    # Optionally filter by report year
    if args.report_year and "report_year" in df.columns:
        df = df[pd.to_numeric(df["report_year"], errors="coerce") == 
args.report_year]
        print(f"Filtered to report year {args.report_year}: {len(df):,} records", file=sys.stderr)

    # Derive block IDs
    df = derive_block_id(df)

    # Build profiles
    print("Building block profiles…", file=sys.stderr)
    blocks = build_block_profiles(df)

    # Save
    blocks.to_csv(args.out, index=False)
    print(f"\nSaved {len(blocks):,} block profiles → {args.out}", 
file=sys.stderr)

    # Print summary to stdout
    print_summary(blocks)

    return blocks


if __name__ == "__main__":
    main()

