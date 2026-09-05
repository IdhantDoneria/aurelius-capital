"""SEC/EDGAR provider adapter (AIDP M21).

Converts EDGAR company-facts JSON into M20 SourceMessage objects. EDGAR data is public domain;
no credentials needed for the EDGAR REST API (https://data.sec.gov/api/xbrl/companyfacts/).

PIT safety — the critical distinction:
    observation_date = filing["filed"]   (knowledge date: when the filing became public)
    effective_date   = filing["end"]     (period end: what accounting period it covers)

Never use `end` as observation_date — that is a look-ahead violation in backtests. GDP Q1 end
2024-03-31 is knowable only after the 10-K/10-Q is filed, often 45–75 days later.

Restatement detection: the same (cik, concept, period_end) may appear across multiple
accession numbers. The adapter emits each filing as a separate message with monotone `revision`
so M19 RevisionStore can reconstruct any point-in-time view.

fetch() raises NotImplementedError. Use convert(company_facts_json, as_of) offline.
"""

from __future__ import annotations

from datetime import date, datetime

from mentisrex.research.market_data_ops.adapters import SourceAdapter, SourceMetadata
from mentisrex.research.market_data_ops.messages import (
    MessageType,
    SourceCapability,
    SourceMessage,
)

# EDGAR us-gaap concept → canonical field name (incomplete list of common metrics)
_CONCEPT_MAP: dict[str, str] = {
    # Income Statement
    "Revenues": "revenue",
    "RevenueFromContractWithCustomerExcludingAssessedTax": "revenue",
    "SalesRevenueNet": "revenue",
    "OperatingIncomeLoss": "operating_income",
    "NetIncomeLoss": "net_income",
    "GrossProfit": "gross_profit",
    "CostsAndExpenses": "total_expenses",
    "ResearchAndDevelopmentExpense": "rd_expense",
    "GeneralAndAdministrativeExpense": "sg_and_a",
    "IncomeTaxExpenseBenefit": "income_tax",
    "EarningsPerShareBasic": "eps_basic",
    "EarningsPerShareDiluted": "eps_diluted",
    # Balance Sheet
    "Assets": "total_assets",
    "AssetsCurrent": "current_assets",
    "CashAndCashEquivalentsAtCarryingValue": "cash",
    "Liabilities": "total_liabilities",
    "LiabilitiesCurrent": "current_liabilities",
    "LongTermDebt": "long_term_debt",
    "StockholdersEquity": "stockholders_equity",
    "RetainedEarningsAccumulatedDeficit": "retained_earnings",
    "CommonStockSharesOutstanding": "shares_outstanding",
    # Cash Flow
    "NetCashProvidedByUsedInOperatingActivities": "cash_flow_operations",
    "NetCashProvidedByUsedInInvestingActivities": "cash_flow_investing",
    "NetCashProvidedByUsedInFinancingActivities": "cash_flow_financing",
    "CapitalExpenditureDiscontinuedOperations": "capex",
    "PaymentsToAcquirePropertyPlantAndEquipment": "capex",
    # Dividends / Equity
    "PaymentsOfDividends": "dividends_paid",
}


class SECSourceAdapter(SourceAdapter):
    """Production contract wrapping EDGAR company-facts data.

    Input: the EDGAR companyfacts JSON (parsed into a dict), shaped as:
        {
          "cik": "0000320193",
          "entityName": "Apple Inc.",
          "facts": {
            "us-gaap": {
              "Revenues": {
                "units": {
                  "USD": [
                    {"end": "2022-09-24", "val": 394328000000,
                     "accn": "0001193125-22-...", "filed": "2022-10-28",
                     "form": "10-K", "fp": "FY", "fy": 2022}
                  ]
                }
              }
            }
          }
        }
    """

    def __init__(self, *, name: str = "sec_edgar") -> None:
        super().__init__(
            SourceMetadata(
                name,
                frozenset(
                    {
                        SourceCapability.HISTORICAL,
                        SourceCapability.FUNDAMENTALS,
                        SourceCapability.REFERENCE_DATA,
                    }
                ),
                schema_version="1.0",
                description="SEC/EDGAR company facts — PIT financial statements",
                vendor="sec",
            )
        )
        self._seq = 0

    def fetch(self, as_of: date, *, security_ids=None, fields=None) -> list[SourceMessage]:
        raise NotImplementedError(
            "sec_edgar.fetch: fetch company facts from "
            "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json, "
            "parse the JSON, then call convert(company_facts, as_of)."
        )

    def convert(
        self, company_facts: dict, as_of: date, *, security_id: str | None = None
    ) -> list[SourceMessage]:
        """Convert EDGAR company-facts JSON to SourceMessage (offline, testable).

        security_id: canonical internal id for this entity. Falls back to CIK string.
        """
        if self._state.value == "disconnected":
            self.connect()
        cik = str(company_facts.get("cik", "unknown"))
        sec_id = security_id or f"cik:{cik}"
        entity = company_facts.get("entityName", cik)

        # collect all raw filings across us-gaap concepts
        raw_filings: list[tuple] = []  # (filed_date, end_date, concept, unit, val, accn, form)
        for taxonomy, concepts in company_facts.get("facts", {}).items():
            for concept, concept_data in concepts.items():
                field = _CONCEPT_MAP.get(concept, concept.lower()[:40])
                for unit_label, observations in concept_data.get("units", {}).items():
                    currency = unit_label if unit_label not in ("pure", "shares") else None
                    for obs in observations:
                        filed = _parse_date(obs.get("filed"))
                        end = _parse_date(obs.get("end"))
                        val = obs.get("val")
                        if filed is None or end is None or val is None:
                            continue
                        # PIT gate: reject filings not yet knowable as_of
                        if filed > as_of:
                            continue
                        raw_filings.append(
                            (
                                filed,
                                end,
                                field,
                                currency,
                                float(val),
                                obs.get("accn", ""),
                                obs.get("form", ""),
                                taxonomy,
                                concept,
                                unit_label,
                            )
                        )

        # sort by (concept, period_end, filed) for deterministic revision numbering
        raw_filings.sort(key=lambda t: (t[2], t[1].isoformat(), t[0].isoformat()))

        # assign revision numbers per (field, period_end) — earlier filings = lower revision
        revision_counter: dict[tuple, int] = {}
        msgs = []
        for (
            filed,
            end,
            field,
            currency,
            val,
            accn,
            form,
            taxonomy,
            concept,
            unit_label,
        ) in raw_filings:
            key = (field, end)
            rev = revision_counter.get(key, 0)
            revision_counter[key] = rev + 1

            payload: dict = {
                "id": sec_id,
                "field": field,
                "value": val,
                "observation_date": filed.isoformat(),  # when knowable (filing date)
                "effective_date": end.isoformat(),  # accounting period end
                "source": self.metadata.name,
                "revision": rev,
                "accn": accn,
                "form": form,
                "taxonomy": taxonomy,
                "concept": concept,
                "unit_label": unit_label,
                "entity_name": entity,
                "cik": cik,
            }
            if currency:
                payload["currency"] = currency

            self._seq += 1
            msgs.append(
                SourceMessage(
                    source=self.metadata.name,
                    payload=payload,
                    msg_type=MessageType.REVISION if rev > 0 else MessageType.OBSERVATION,
                    vendor_id=f"{cik}:{concept}:{end.isoformat()}",
                    sequence=self._seq,
                    observation_date=filed,
                    effective_date=end,
                    schema_version=self.metadata.schema_version,
                )
            )

        return self._record(msgs)


def _parse_date(v) -> date | None:
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, str):
        try:
            return date.fromisoformat(v[:10])
        except ValueError:
            return None
    return None
