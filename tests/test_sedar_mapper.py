from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.integrity import sedar_mapper
from modules.integrity.sedar_mapper import map_line_items


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _line_items(data: dict) -> list[dict]:
    rows = []
    for item in data["statements"]["income_statement"]:
        values = item.get("values") or {}
        rows.append({
            "label": item["label"],
            "value": _mapper_source_value(values),
            "confidence": item.get("confidence"),
        })
    return rows


def _mapper_source_value(values: dict) -> int | float | None:
    annual_candidates = []
    for idx, (period, value) in enumerate((values or {}).items()):
        period_text = str(period)
        period_lower = period_text.lower()
        if (
            "year ended" not in period_lower
            and "years ended" not in period_lower
            and not period_lower.startswith("year ")
        ):
            continue
        import re
        match = re.search(r"(\d{4})", period_text)
        year = int(match.group(1)) if match else -1
        annual_candidates.append((year, idx, value))
    if annual_candidates:
        return sorted(annual_candidates, key=lambda row: (row[0], -row[1]), reverse=True)[0][2]
    return next(iter((values or {}).values()), None)


def _source_value(data: dict, label: str) -> int | float | None:
    for item in data["statements"]["income_statement"]:
        if item["label"] == label:
            return next(iter((item.get("values") or {}).values()), None)
    raise AssertionError(f"Label not found: {label}")


def _mapped_fixture(name: str, sector: str | None = None) -> tuple[dict, dict]:
    data = _load_fixture(name)
    return data, map_line_items(_line_items(data), data["accounting_standard"], sector=sector)


def _assert_conservation(result: dict) -> None:
    meta = result["meta"]
    total = meta["total"]
    benign_skipped = meta.get("benign_skipped_count", 0)
    assert meta["mapped_count"] + meta["unmapped_count"] + benign_skipped == total


def _assert_unmapped_labels_are_verbatim(data: dict, result: dict) -> None:
    from collections import Counter
    fixture_labels = Counter(item["label"] for item in data["statements"]["income_statement"])
    unmapped_labels = Counter(item["label"] for item in result["unmapped"])
    assert unmapped_labels <= fixture_labels


def test_cnr_fixture_maps_required_income_statement_fields():
    data, result = _mapped_fixture("CNR_FY2025_sedar.json")
    mapped = result["mapped"]

    assert mapped["revenue"]["value"] == 17304
    assert mapped["revenue"]["match_type"] == "exact"
    assert mapped["revenue"]["source_label"] == "Revenues"

    assert mapped["operating_income"]["value"] == _source_value(data, "Operating income")
    assert mapped["interest_expense"]["value"] == _source_value(data, "Interest expense")
    assert mapped["net_income"]["value"] == _source_value(data, "Net income")
    assert result["meta"]["mapped_count"] == 4
    _assert_conservation(result)
    _assert_unmapped_labels_are_verbatim(data, result)


def test_csu_fixture_maps_required_fields_and_keeps_duplicate_net_income_unmapped():
    data, result = _mapped_fixture("CSU_FY2025_sedar.json")
    mapped = result["mapped"]

    assert mapped["interest_expense"]["source_label"] == "Finance costs (note 18)"
    assert mapped["interest_expense"]["value"] == _source_value(data, "Finance costs (note 18)")
    assert mapped["revenue"]["source_label"] == "Revenue total"
    assert mapped["revenue"]["value"] == _source_value(data, "Revenue total")
    assert mapped["net_income"]["source_label"] == "Net income (loss)"
    assert mapped["net_income"]["value"] == _source_value(data, "Net income (loss)")
    assert result["meta"]["mapped_count"] == 3

    # "Net income (loss)" appears twice in CSU IS with the same value — benign duplicate.
    # The first occurrence maps to net_income; the second is benign-skipped.
    unmapped_labels = [item["label"] for item in result["unmapped"]]
    assert "Revenue total" not in unmapped_labels
    assert unmapped_labels.count("Net income (loss)") == 0
    assert result["meta"]["benign_skipped_count"] == 2
    _assert_conservation(result)
    _assert_unmapped_labels_are_verbatim(data, result)


def test_ry_fixture_override_preserves_defaults_under_financial_sector_profile():
    """
    RY (Royal Bank of Canada, IFRS, CAD).

    OVERRIDE semantics: sector_profile=financial_sector ADDS sector-specific
    fields without dropping defaults. Default `revenue` (66,605) and
    `net_income` (20,369) still map. Sector additions `net_interest_income`
    and `provision_for_credit_losses` are present. `total_revenue_bank`
    does NOT map because its alias "total revenue" collides with default
    revenue's alias — first-write-wins keeps revenue (defaults iterated
    first). This is the RY trap defused: applying the sector profile no
    longer silently drops revenue/net_income coverage.
    """
    data, result = _mapped_fixture("RY_FY2025_sedar.json", sector="Financial Services")
    mapped = result["mapped"]

    # Defaults preserved
    assert mapped["revenue"]["value"] == 66605
    assert mapped["revenue"]["source_label"] == "Total revenue"
    assert mapped["net_income"]["value"] == 20369
    assert mapped["net_income"]["source_label"] == "Net income"

    # Sector additions
    assert mapped["net_interest_income"]["value"] == 33000
    assert mapped["net_interest_income"]["source_label"] == "Net interest income"
    assert mapped["provision_for_credit_losses"]["value"] == 4362
    assert mapped["provision_for_credit_losses"]["source_label"] == "Provision for credit losses"

    # First-write-wins: default revenue claims "total revenue", so the
    # profile's same-label total_revenue_bank does not map.
    assert "total_revenue_bank" not in mapped

    assert result["meta"]["sector_profile"] == "financial_sector"
    _assert_conservation(result)
    _assert_unmapped_labels_are_verbatim(data, result)


def test_collision_guard_keeps_both_distinct_labels_unmapped(monkeypatch):
    alias_table = {
        "schema_version": 1,
        "scope": "income_statement",
        "canonical_fields": {
            "revenue": {
                "aliases": [
                    {"label": "sales", "standards": ["IFRS"], "source": "synthetic"},
                    {"label": "turnover", "standards": ["IFRS"], "source": "synthetic"},
                ],
                "patterns": [],
            }
        },
        "sector_profiles": {},
    }
    monkeypatch.setattr(sedar_mapper, "_load_alias_table", lambda: alias_table)

    result = map_line_items(
        [
            {"label": "Sales", "value": 100},
            {"label": "Turnover", "value": 200},
        ],
        "IFRS",
    )

    assert "revenue" not in result["mapped"]
    assert [item["label"] for item in result["unmapped"]] == ["Sales", "Turnover"]
    assert result["meta"]["collisions"]
    _assert_conservation(result)


def test_standard_filter_rejects_ifrs_only_alias_for_us_gaap():
    result = map_line_items(
        [{"label": "Finance costs", "value": 297, "confidence": 0.99}],
        "US GAAP",
    )

    assert "interest_expense" not in result["mapped"]
    assert result["unmapped"] == [{"label": "Finance costs", "value": 297}]
    _assert_conservation(result)


def test_standard_normalization_us_gaap_with_periods():
    # "U.S. GAAP" (Claude verbatim extraction) must match alias table tag "US GAAP".
    result = map_line_items(
        [{"label": "Finance costs", "value": 297, "confidence": 0.99}],
        "U.S. GAAP",
    )
    # "Finance costs" is IFRS-only — still rejected even after normalization.
    assert "interest_expense" not in result["mapped"]
    assert result["unmapped"] == [{"label": "Finance costs", "value": 297}]
    _assert_conservation(result)


def test_standard_normalization_us_gaap_with_periods_maps_us_gaap_alias():
    # "U.S. GAAP" input must allow US GAAP-tagged aliases to fire.
    result = map_line_items(
        [{"label": "Operating income", "value": 500, "confidence": 0.99}],
        "U.S. GAAP",
    )
    assert result["mapped"]["operating_income"]["value"] == 500
    assert result["mapped"]["operating_income"]["match_type"] == "exact"
    _assert_conservation(result)


def test_standard_normalization_maps_accounting_family_variants():
    assert sedar_mapper._normalize_standard("IFRS") == "ifrs"
    assert sedar_mapper._normalize_standard("IFRS Accounting Standards") == "ifrs"
    assert sedar_mapper._normalize_standard("IFRS 16") == "ifrs"
    assert sedar_mapper._normalize_standard("US GAAP") == "usgaap"
    assert sedar_mapper._normalize_standard("U.S. GAAP") == "usgaap"
    assert sedar_mapper._normalize_standard("United States GAAP") == "usgaap"


def test_prefer_profile_escape_hatch_is_limited_to_reit_operating_income():
    alias_table = sedar_mapper._load_alias_table()
    uses = []
    for profile_name, profile in (alias_table.get("sector_profiles") or {}).items():
        for field_name, config in (profile.get("canonical_fields") or {}).items():
            for alias in config.get("aliases") or []:
                if alias.get("prefer_profile"):
                    uses.append((profile_name, field_name, alias["label"]))

    assert uses == [("reit_sector", "net_operating_income", "operating income")]


def test_operating_income_maps_under_ifrs():
    result = map_line_items(
        [{"label": "Operating income", "value": 798716, "confidence": 0.99}],
        "IFRS",
    )
    assert result["mapped"]["operating_income"]["value"] == 798716
    assert result["mapped"]["operating_income"]["match_type"] == "exact"
    _assert_conservation(result)


def test_standard_normalization_ifrs_exact_passes():
    # "IFRS" must continue to work as before.
    result = map_line_items(
        [{"label": "Finance costs", "value": 297, "confidence": 0.99}],
        "IFRS",
    )
    assert result["mapped"]["interest_expense"]["value"] == 297
    _assert_conservation(result)


def test_standard_normalization_different_standard_still_rejects():
    # A genuinely different standard ("Japanese GAAP") must not match US GAAP or IFRS aliases.
    result = map_line_items(
        [
            {"label": "Finance costs", "value": 100},
            {"label": "Operating income", "value": 200},
        ],
        "Japanese GAAP",
    )
    assert result["mapped"] == {}
    assert result["meta"]["mapped_count"] == 0
    _assert_conservation(result)


def test_normalization_maps_note_references_case_and_trailing_punctuation():
    result = map_line_items(
        [{"label": "  Finance Costs (Note 18).  ", "value": 297, "confidence": 0.99}],
        "IFRS",
    )

    assert result["mapped"]["interest_expense"]["value"] == 297
    assert result["mapped"]["interest_expense"]["source_label"] == "  Finance Costs (Note 18).  "
    assert result["mapped"]["interest_expense"]["match_type"] == "exact"
    _assert_conservation(result)


def test_shop_fixture_maps_four_fields_us_gaap():
    """
    SHOP (Shopify, US GAAP, USD, December year-end) maps four fields after
    alias additions (item 1, Jun 2026):
    - "Total revenues" → revenue
    - "Gross profit" → gross_profit
    - "Income (loss) from operations" → operating_income
    - "Net income" → net_income

    Persistent alias gap: "Interest income" does NOT match "interest expense".
    When mapped_count changes, update the expected value and document the new alias.
    Do NOT weaken assertions to make the test pass.
    """
    data = _load_fixture("SHOP_FY2025_sedar.json")
    assert data["accounting_standard"] == "U.S. GAAP"
    result = map_line_items(_line_items(data), data["accounting_standard"])
    mapped = result["mapped"]

    assert mapped["gross_profit"]["value"] == 5555
    assert mapped["gross_profit"]["match_type"] == "exact"
    assert mapped["gross_profit"]["source_label"] == "Gross profit"

    assert mapped["operating_income"]["value"] == 1468
    assert mapped["operating_income"]["match_type"] == "exact"
    assert mapped["operating_income"]["source_label"] == "Income (loss) from operations"

    assert mapped["net_income"]["value"] == 1231
    assert mapped["net_income"]["match_type"] == "exact"
    assert mapped["net_income"]["source_label"] == "Net income"

    assert mapped["revenue"]["value"] == 11556
    assert mapped["revenue"]["match_type"] == "exact"
    assert mapped["revenue"]["source_label"] == "Total revenues"
    assert "interest_expense" not in mapped

    assert result["meta"]["mapped_count"] == 4
    _assert_conservation(result)
    _assert_unmapped_labels_are_verbatim(data, result)

    unmapped_labels = [item["label"] for item in result["unmapped"]]
    assert "Total revenues" not in unmapped_labels
    assert "Net unrealized (loss) gain on equity and other investments" in unmapped_labels


def test_atd_fixture_maps_five_fields_with_derived_gross_profit():
    """
    ATD (Alimentation Couche-Tard, IFRS, USD, April year-end).

    After alias additions (item 1) and benign-duplicate relaxation (item 13),
    five IS line items map:
    - "Revenues" → revenue
    - "Cost of sales, excluding depreciation, amortization and impairment" → cost_of_revenue
      (semantics.excludes_da: True — D&A not included in this cost line)
    - "Operating income" → operating_income
    - "Financial expenses" → interest_expense
    - "Net earnings" → net_income (first of two identical occurrences; second benign-skipped)

    Gross profit is DERIVED (revenue - cost_of_revenue = 13021.3).
    Derived entries are NOT counted in mapped_count.

    Do NOT weaken assertions. If mapped_count changes, update and document the new alias.
    """
    data = _load_fixture("ATD_FY2025_sedar.json")
    assert data["accounting_standard"] == "IFRS Accounting Standards"
    result = map_line_items(_line_items(data), data["accounting_standard"])
    mapped = result["mapped"]

    assert mapped["revenue"]["source_label"] == "Revenues"
    assert mapped["revenue"]["value"] == _source_value(data, "Revenues")

    assert mapped["cost_of_revenue"]["source_label"] == (
        "Cost of sales, excluding depreciation, amortization and impairment (Note 7)"
    )
    assert mapped["cost_of_revenue"]["value"] == _source_value(
        data, "Cost of sales, excluding depreciation, amortization and impairment (Note 7)"
    )
    assert mapped["cost_of_revenue"].get("semantics", {}).get("excludes_da") is True

    assert mapped["operating_income"]["source_label"] == "Operating income"
    assert mapped["operating_income"]["value"] == _source_value(data, "Operating income")

    assert mapped["interest_expense"]["source_label"] == "Financial expenses (Note 9)"
    assert mapped["interest_expense"]["value"] == _source_value(data, "Financial expenses (Note 9)")

    assert mapped["net_income"]["source_label"] == "Net earnings"
    assert mapped["net_income"]["value"] == _source_value(data, "Net earnings")

    # Derived gross profit — not a line-item mapping.
    assert "gross_profit" in mapped
    assert mapped["gross_profit"]["derived"] is True
    assert mapped["gross_profit"]["excludes_da"] is True
    assert abs(mapped["gross_profit"]["value"] - 13021.3) < 0.01

    assert result["meta"]["mapped_count"] == 5
    assert result["meta"]["gross_profit_derived"] is True
    assert result["meta"]["benign_skipped_count"] == 1  # second "Net earnings"

    _assert_conservation(result)
    _assert_unmapped_labels_are_verbatim(data, result)

    unmapped_labels = [item["label"] for item in result["unmapped"]]
    assert "Revenues" not in unmapped_labels
    assert "Operating income" not in unmapped_labels
    assert "Financial expenses (Note 9)" not in unmapped_labels
    # "Net financial expenses" is a separate label and remains unmapped.
    assert "Net financial expenses" in unmapped_labels


def test_reiun_fixture_maps_reit_sector_profile_without_replacing_defaults():
    """
    REI.UN (Canadian Retail REIT, IFRS, CAD, December year-end).

    REIT-sector profile uses OVERRIDE semantics: it augments the default
    canonical fields. REI.UN keeps default revenue, interest_expense, and
    net_income mappings while adding the v1 universal REIT fields.
    """
    data = _load_fixture("REIUN_FY2025_sedar.json")
    assert data["accounting_standard"] == "IFRS"
    assert data["sector_inferred"] == "Real Estate (REIT)"
    result = map_line_items(
        _line_items(data),
        data["accounting_standard"],
        sector=data["sector_inferred"],
    )
    mapped = result["mapped"]

    assert mapped["rental_revenue"]["source_label"] == "Rental revenue"
    assert mapped["rental_revenue"]["value"] == _source_value(data, "Rental revenue")

    assert mapped["net_operating_income"]["source_label"] == "Operating income"
    assert mapped["net_operating_income"]["value"] == _source_value(data, "Operating income")

    assert mapped["property_operating_costs"]["source_label"] == "Total operating costs"
    assert mapped["property_operating_costs"]["value"] == _source_value(data, "Total operating costs")

    assert mapped["investment_property_fair_value_delta"]["source_label"] == (
        "Fair value loss on investment properties, net"
    )
    assert mapped["investment_property_fair_value_delta"]["value"] == _source_value(
        data, "Fair value loss on investment properties, net"
    )

    assert "operating_income" not in mapped

    assert mapped["interest_expense"]["source_label"] == "Interest costs, net"
    assert mapped["interest_expense"]["value"] == _source_value(data, "Interest costs, net")

    assert mapped["net_income"]["source_label"] == "Net income"
    assert mapped["net_income"]["value"] == _source_value(data, "Net income")

    assert mapped["revenue"]["source_label"] == "Total revenue"
    assert mapped["revenue"]["value"] == _source_value(data, "Total revenue")

    assert result["meta"]["sector_profile"] == "reit_sector"
    assert result["meta"]["mapped_count"] == 7
    assert result["meta"]["benign_skipped_count"] == 1  # second "Net income"

    unmapped_labels = [item["label"] for item in result["unmapped"]]
    assert "Rental revenue" not in unmapped_labels
    assert "Total operating costs" not in unmapped_labels
    assert "Operating income" not in unmapped_labels
    assert "Fair value loss on investment properties, net" not in unmapped_labels
    assert "Income (loss) from equity-accounted investments" in unmapped_labels

    _assert_conservation(result)
    _assert_unmapped_labels_are_verbatim(data, result)


def test_cnq_fixture_maps_resource_sector_profile_without_replacing_defaults():
    """
    CNQ (Canadian Natural Resources, IFRS, CAD, December year-end).

    Resource-sector profile uses OVERRIDE semantics: it augments the default
    canonical fields. CNQ maps sector-native fields from its primary income
    statement while preserving default net_income via "Net earnings".

    Important CNQ semantics: `total_revenue` is gross Product sales before
    royalties. The statement also contains a net "Revenue" line after royalties;
    that line deliberately remains unmapped so the gross and royalty components
    do not collapse into one generic revenue value.
    """
    data = _load_fixture("cnq_fy2024_sedar.json")
    assert data["accounting_standard"] == "IFRS"
    assert data["sector_inferred"] == "Upstream Oil & Gas"
    provenance = data["source_provenance"]
    assert provenance["pdf_origin_url"] == (
        "https://www.cnrl.com/content/uploads/2025/03/12.31.2024-Q4-FS.pdf"
    )
    assert "Radware CAPTCHA" in provenance["sedar_access_note"]
    assert "Q4 financial statements" in provenance["document_note"]

    result = map_line_items(
        _line_items(data),
        data["accounting_standard"],
        sector=data["sector_inferred"],
    )
    mapped = result["mapped"]

    assert mapped["total_revenue"]["source_label"] == "Product sales"
    assert mapped["total_revenue"]["value"] == 41509

    assert mapped["royalties"]["source_label"] == "Less: royalties"
    assert mapped["royalties"]["value"] == -5853

    assert mapped["operating_expense"]["source_label"] == "Production"
    assert mapped["operating_expense"]["value"] == 8093

    assert mapped["depletion_depreciation_amortization"]["source_label"] == (
        "Depletion, depreciation and amortization"
    )
    assert mapped["depletion_depreciation_amortization"]["value"] == 6681

    assert mapped["net_income"]["source_label"] == "Net earnings"
    assert mapped["net_income"]["value"] == 6106
    assert "exploration_expense" not in mapped

    assert result["meta"]["sector_profile"] == "resource_sector"
    assert result["meta"]["mapped_count"] == 5
    assert result["meta"]["benign_skipped_count"] == 1  # second "Net earnings"

    unmapped_labels = [item["label"] for item in result["unmapped"]]
    assert "Revenue" in unmapped_labels
    assert "Product sales" not in unmapped_labels
    assert "Less: royalties" not in unmapped_labels

    _assert_conservation(result)
    _assert_unmapped_labels_are_verbatim(data, result)


def test_aem_fixture_maps_mining_sector_profile_without_replacing_defaults():
    """
    AEM (Agnico Eagle, gold miner, IFRS, USD, December year-end).

    Mining-sector profile uses OVERRIDE semantics: it augments the default
    canonical fields. AEM maps mining-native income-statement fields while
    preserving default interest_expense and net_income coverage.
    """
    data = _load_fixture("AEM_FY2025_sedar.json")
    assert data["source"] == "sedar_pdf"
    assert data["accounting_standard"] == "IFRS"
    assert data["currency"] == "USD"
    assert data["scale"] == "thousands"
    assert data["fiscal_year_end"] == "2025-12-31"
    assert data["filing_date"] == "2026-02-12"
    assert data["sector_inferred"] == "Gold Mining"
    provenance = data["source_provenance"]
    assert provenance["pdf_origin_url"] == (
        "https://www.agnicoeagle.com/English/investor-relations/"
        "financial-reports/default.aspx"
    )
    assert provenance["sedar_access_note"] == (
        "SEDAR+ skipped per CAPTCHA finding; issuer IR Cloudflare-blocked "
        "to automated fetch"
    )
    assert provenance["retrieval_method"] == (
        "manual browser download from issuer IR page by Riley, 2026-06-13"
    )
    assert "PDF page 96" in provenance["document_note"]
    assert provenance["future_pattern"] == (
        "tier-3 manual issuer download is acceptable when IR is Cloudflare-blocked; "
        "mirrors are not"
    )

    result = map_line_items(
        _line_items(data),
        data["accounting_standard"],
        sector=data["sector_inferred"],
    )
    mapped = result["mapped"]

    assert mapped["revenue"]["source_label"] == "Revenues from mining operations (Note 19)"
    assert mapped["revenue"]["value"] == _source_value(
        data, "Revenues from mining operations (Note 19)"
    )

    assert mapped["production_costs"]["source_label"] == "Production (i)"
    assert mapped["production_costs"]["value"] == _source_value(data, "Production (i)")

    assert mapped["exploration_expense"]["source_label"] == (
        "Exploration and corporate development"
    )
    assert mapped["exploration_expense"]["value"] == _source_value(
        data, "Exploration and corporate development"
    )

    assert mapped["mine_development_amortization"]["source_label"] == (
        "Amortization of property, plant and mine development (Note 9)"
    )
    assert mapped["mine_development_amortization"]["value"] == _source_value(
        data, "Amortization of property, plant and mine development (Note 9)"
    )

    assert mapped["interest_expense"]["source_label"] == "Finance costs (Note 14)"
    assert mapped["interest_expense"]["value"] == _source_value(data, "Finance costs (Note 14)")

    assert mapped["net_income"]["source_label"] == "Net income for the year"
    assert mapped["net_income"]["value"] == _source_value(data, "Net income for the year")

    assert result["meta"]["sector_profile"] == "mining_sector"
    assert result["meta"]["mapped_count"] == 6
    assert result["meta"]["benign_skipped_count"] == 1  # second "Net income for the year"

    unmapped_labels = [item["label"] for item in result["unmapped"]]
    assert "Revenues from mining operations (Note 19)" not in unmapped_labels
    assert "Production (i)" not in unmapped_labels
    assert "Care and maintenance" in unmapped_labels
    assert "Income and mining taxes expense (Note 25)" in unmapped_labels

    _assert_conservation(result)
    _assert_unmapped_labels_are_verbatim(data, result)


def test_carun_fixture_maps_reit_sector_profile_without_replacing_defaults():
    """
    CAR.UN (CAPREIT, residential REIT, IFRS, CAD, December year-end).

    REIT-sector profile uses OVERRIDE semantics: it augments the default
    canonical fields. CAR.UN keeps default net_income while adding the v1
    universal REIT fields.
    """
    data = _load_fixture("CARUN_FY2024_sedar.json")
    assert data["accounting_standard"] == "IFRS"
    assert data["sector_inferred"] == "Real Estate (REIT)"
    provenance = data["source_provenance"]
    assert provenance["pdf_origin_url"] == (
        "https://www.capreit.ca/wp-content/uploads/2025/02/"
        "CAPREIT-Q4-2024-Annual-Report-web-optimized.pdf"
    )
    assert "Radware CAPTCHA" in provenance["sedar_access_note"]
    assert "annual report" in provenance["document_note"]
    assert provenance["future_pattern"] == (
        "issuer-hosted PDF is the established campaign protocol per "
        "docs/FETCH_CAMPAIGN_LOG.md"
    )

    result = map_line_items(
        _line_items(data),
        data["accounting_standard"],
        sector=data["sector_inferred"],
    )
    mapped = result["mapped"]

    assert mapped["rental_revenue"]["source_label"] == "Revenue from investment properties"
    assert mapped["rental_revenue"]["value"] == _source_value(data, "Revenue from investment properties")

    assert mapped["net_operating_income"]["source_label"] == "Net operating income"
    assert mapped["net_operating_income"]["value"] == _source_value(data, "Net operating income")

    assert mapped["property_operating_costs"]["source_label"] == "Property operating costs"
    assert mapped["property_operating_costs"]["value"] == _source_value(data, "Property operating costs")

    assert mapped["investment_property_fair_value_delta"]["source_label"] == (
        "Fair value adjustments of investment properties"
    )
    assert mapped["investment_property_fair_value_delta"]["value"] == _source_value(
        data, "Fair value adjustments of investment properties"
    )

    assert mapped["net_income"]["source_label"] == "Net income (loss)"
    assert mapped["net_income"]["value"] == 292742

    assert result["meta"]["mapped_count"] == 5
    assert result["meta"]["sector_profile"] == "reit_sector"

    unmapped_labels = [item["label"] for item in result["unmapped"]]
    assert "Revenue from investment properties" not in unmapped_labels
    assert "Property operating costs" not in unmapped_labels
    assert "Net operating income" not in unmapped_labels
    assert "Fair value adjustments of investment properties" not in unmapped_labels
    assert "Fair value adjustments of financial instruments" in unmapped_labels

    _assert_conservation(result)
    _assert_unmapped_labels_are_verbatim(data, result)


def test_dirun_fixture_maps_reit_sector_profile_without_replacing_defaults():
    """
    DIR.UN (Dream Industrial REIT, industrial REIT, IFRS, CAD, December year-end).

    REIT-sector profile uses OVERRIDE semantics: it augments the default
    canonical fields. DIR.UN keeps default net_income while adding the v1
    universal REIT fields.
    """
    data = _load_fixture("DIRUN_FY2024_sedar.json")
    assert data["source"] == "sedar_pdf"
    assert data["accounting_standard"] == "IFRS"
    assert data["sector_inferred"] == "Real Estate (REIT)"
    assert data["filing_date"] == "2025-02-18"
    provenance = data["source_provenance"]
    assert provenance["pdf_origin_url"] == (
        "https://investors.dream.ca/wp-content/uploads/2025/02/"
        "2024-DIR-Annual-Report-FINAL.pdf"
    )
    assert "Radware CAPTCHA" in provenance["sedar_access_note"]
    assert "annual report" in provenance["document_note"].lower()
    assert provenance["future_pattern"] == (
        "issuer-hosted PDF is the established campaign protocol per "
        "docs/FETCH_CAMPAIGN_LOG.md"
    )

    result = map_line_items(
        _line_items(data),
        data["accounting_standard"],
        sector=data["sector_inferred"],
    )
    mapped = result["mapped"]

    assert mapped["rental_revenue"]["source_label"] == "Investment properties revenue"
    assert mapped["rental_revenue"]["value"] == _source_value(data, "Investment properties revenue")

    assert mapped["net_operating_income"]["source_label"] == "Net rental income"
    assert mapped["net_operating_income"]["value"] == _source_value(data, "Net rental income")

    assert mapped["property_operating_costs"]["source_label"] == (
        "Investment properties operating expenses"
    )
    assert mapped["property_operating_costs"]["value"] == _source_value(
        data, "Investment properties operating expenses"
    )

    assert mapped["investment_property_fair_value_delta"]["source_label"] == (
        "Fair value adjustments to investment properties"
    )
    assert mapped["investment_property_fair_value_delta"]["value"] == _source_value(
        data, "Fair value adjustments to investment properties"
    )

    assert mapped["net_income"]["source_label"] == "Net income"
    assert mapped["net_income"]["value"] == 259611

    assert result["meta"]["mapped_count"] == 5
    assert result["meta"]["sector_profile"] == "reit_sector"

    unmapped_labels = [item["label"] for item in result["unmapped"]]
    assert "Investment properties revenue" not in unmapped_labels
    assert "Investment properties operating expenses" not in unmapped_labels
    assert "Net rental income" not in unmapped_labels
    assert "Fair value adjustments to investment properties" not in unmapped_labels
    assert "Share of net income from equity accounted investments" in unmapped_labels
    assert "Fair value adjustments to financial instruments" in unmapped_labels

    _assert_conservation(result)
    _assert_unmapped_labels_are_verbatim(data, result)


def test_benign_duplicate_same_value_maps_first_occurrence(monkeypatch):
    """Same normalized label + same value = benign duplicate: first occurrence maps."""
    alias_table = {
        "schema_version": 1,
        "scope": "income_statement",
        "canonical_fields": {
            "net_income": {
                "aliases": [
                    {"label": "net earnings", "standards": ["IFRS"], "source": "synthetic"},
                ],
                "patterns": [],
            }
        },
        "sector_profiles": {},
    }
    monkeypatch.setattr(sedar_mapper, "_load_alias_table", lambda: alias_table)

    result = map_line_items(
        [
            {"label": "Net earnings", "value": 2592.4},
            {"label": "Net earnings", "value": 2592.4},
        ],
        "IFRS",
    )

    assert result["mapped"]["net_income"]["value"] == 2592.4
    assert result["meta"]["mapped_count"] == 1
    assert result["meta"]["benign_skipped_count"] == 1
    meta = result["meta"]
    assert meta["mapped_count"] + meta["unmapped_count"] + meta["benign_skipped_count"] == meta["total"]


def test_ambiguous_duplicate_different_values_still_blocks(monkeypatch):
    """Same normalized label + different values = ambiguous: all occurrences go to unmapped."""
    alias_table = {
        "schema_version": 1,
        "scope": "income_statement",
        "canonical_fields": {
            "net_income": {
                "aliases": [
                    {"label": "net earnings", "standards": ["IFRS"], "source": "synthetic"},
                ],
                "patterns": [],
            }
        },
        "sector_profiles": {},
    }
    monkeypatch.setattr(sedar_mapper, "_load_alias_table", lambda: alias_table)

    result = map_line_items(
        [
            {"label": "Net earnings", "value": 2592.4},
            {"label": "Net earnings", "value": 2580.4},
        ],
        "IFRS",
    )

    assert "net_income" not in result["mapped"]
    assert len(result["unmapped"]) == 2
    assert result["meta"]["mapped_count"] == 0
    assert result["meta"].get("benign_skipped_count", 0) == 0
    meta = result["meta"]
    assert meta["mapped_count"] + meta["unmapped_count"] + meta.get("benign_skipped_count", 0) == meta["total"]
