#!/usr/bin/env python3
"""
Shared CSV loader for HubSpot exports.

Loads deals and companies CSVs, joins them, and produces normalized
deal records matching the API format for use by both history and
analytics ETL modes.
"""
import csv
import sys
from typing import Dict, List, Optional
from pathlib import Path

# Increase CSV field size limit for large HubSpot exports
csv.field_size_limit(sys.maxsize)


def load_deals_from_csv(
    deals_csv_path: str,
    companies_csv_path: Optional[str] = None
) -> tuple:
    """
    Load deals from CSV export, optionally joined with companies export.

    Args:
        deals_csv_path: Path to deals CSV export from HubSpot
        companies_csv_path: Optional path to companies CSV export

    Returns:
        tuple: (deals_list, stats_dict)
            - deals_list: List of deal dicts in API format
            - stats_dict: Population stats for reporting

    The function:
    1. Loads companies CSV (if provided) into a lookup dict
    2. Loads deals CSV
    3. Joins deals to companies on Associated Company IDs
    4. Normalizes column names to match API format
    5. Reports employee count population rate
    """
    stats = {
        'total_deals': 0,
        'deals_with_company_id': 0,
        'companies_with_employees': 0,
        'deals_with_employee_count': 0,
    }

    # Load companies CSV into lookup dict
    company_lookup = {}
    if companies_csv_path:
        print(f"\n  Loading companies from: {companies_csv_path}")
        with open(companies_csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            print(f"  Company CSV columns: {len(headers)} found")

            for row in reader:
                company_id = row.get('Record ID')
                if not company_id:
                    continue

                # Extract relevant fields with flexible column matching
                company_data = {
                    'id': company_id,
                    'name': row.get('Company name', ''),
                    'domain': row.get('Company Domain Name', ''),
                    'numberofemployees': row.get('Number of Employees', ''),
                }

                company_lookup[company_id] = company_data

                # Track employee count population
                if company_data['numberofemployees'] and company_data['numberofemployees'].strip():
                    stats['companies_with_employees'] += 1

        print(f"  Loaded {len(company_lookup)} companies")
        print(f"  Employee count populated: {stats['companies_with_employees']}/{len(company_lookup)} "
              f"({100*stats['companies_with_employees']//len(company_lookup) if company_lookup else 0}%)")

    # Load deals CSV
    print(f"\n  Loading deals from: {deals_csv_path}")
    deals = []

    with open(deals_csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames
        print(f"  Deal CSV columns: {len(headers)} found")

        for row in reader:
            stats['total_deals'] += 1

            deal_id = row.get('Record ID')
            if not deal_id:
                continue

            # Extract associated company IDs (semicolon-separated if multiple)
            company_ids_raw = row.get('Associated Company IDs', '')
            company_ids = [cid.strip() for cid in company_ids_raw.split(';') if cid.strip()] if company_ids_raw else []

            # Take first associated company
            company_id = company_ids[0] if company_ids else None
            company_data = company_lookup.get(company_id, {}) if company_id else {}

            if company_id:
                stats['deals_with_company_id'] += 1

            if company_data.get('numberofemployees'):
                stats['deals_with_employee_count'] += 1

            # Build normalized deal object matching API format
            deal_obj = {
                'id': deal_id,
                'properties': {
                    'dealname': row.get('Deal Name', ''),
                    'pipeline': row.get('Pipeline', ''),
                    'dealstage': row.get('Deal Stage', ''),
                    'closedate': row.get('Close Date', ''),
                    'createdate': row.get('Create Date', ''),
                    'hubspot_owner_id': row.get('Deal owner', ''),
                    'amount': row.get('Amount', '0'),
                    # Analytics-specific fields
                    'new_revenue': row.get('New ARR', ''),  # Column is "New ARR"
                    'expansion_revenue': row.get('Expansion ARR', ''),
                    'prior_arr': row.get('Prior ARR', ''),
                    'sao': row.get('SAO', ''),
                    'hs_manual_forecast_category': row.get('Forecast category', ''),
                },
                # Add company data if available
                'company_id': company_id,
                'company_name': company_data.get('name', row.get('Associated Company (Primary)', '')),
                'company_numberofemployees': company_data.get('numberofemployees', ''),
            }

            deals.append(deal_obj)

    print(f"  Loaded {len(deals)} deals")
    print(f"\n  Company Association Coverage:")
    print(f"    Deals with company ID: {stats['deals_with_company_id']}/{stats['total_deals']} "
          f"({100*stats['deals_with_company_id']//stats['total_deals'] if stats['total_deals'] else 0}%)")
    print(f"    Deals with employee count: {stats['deals_with_employee_count']}/{stats['total_deals']} "
          f"({100*stats['deals_with_employee_count']//stats['total_deals'] if stats['total_deals'] else 0}%)")

    return deals, stats
