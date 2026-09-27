"""End to end on PostgreSQL + moto: upload → process → facts → calculations → dashboard/timeline
→ evidence → reconciliation → export. Runs when TEST_DATABASE_URL is set."""

import csv
import hashlib
import io
import os
import uuid
import zipfile
from xml.etree import ElementTree

import httpx
import pytest
from sample_pdf import build_report_2024, build_sample_report
from test_worker import client, only_this_tests_jobs, session_headers  # noqa: F401 (fixture)

from app.exports import _csv
from app.worker import process_next

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"
)
API = "/api/v1/documents"
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


@pytest.fixture(scope="module")
def reports(tmp_path_factory) -> tuple[bytes, bytes]:
    folder = tmp_path_factory.mktemp("reports")
    return (
        build_sample_report(folder / "ar2025.pdf").read_bytes(),
        build_report_2024(folder / "ar2024.pdf").read_bytes(),
    )


def upload(headers, data: bytes, filename: str, fiscal_year: int, company: str | None) -> str:
    """The real upload flow: create → PUT to the signed URL → complete."""
    body = {
        "filename": filename,
        "content_type": "application/pdf",
        "size_bytes": len(data),
        "fiscal_year": fiscal_year,
        "company_name": company,
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    created = client.post(API, json=body, headers=headers).json()
    httpx.put(created["upload"]["url"], content=data, headers=created["upload"]["headers"])
    assert client.post(f"{API}/{created['document']['id']}/complete", headers=headers).is_success
    return created["document"]["id"]


def by(items, **match):
    [item] = [i for i in items if all(i[k] == v for k, v in match.items())]
    return item


def test_research_workspace_end_to_end(storage, reports):
    owner, _ = session_headers()
    intruder, _ = session_headers()
    ar2025 = upload(owner, reports[0], "Annual Report 2025.pdf", 2025, "PT Contoh  Sejahtera")
    ar2024 = upload(owner, reports[1], "Annual Report 2024.pdf", 2024, None)
    process_next(storage)
    process_next(storage)
    # The company name is normalized and matched case-insensitively.
    patched = client.patch(
        f"{API}/{ar2024}", json={"company_name": " pt contoh sejahtera "}, headers=owner
    )
    assert patched.json()["company_name"] == "pt contoh sejahtera"

    # --- Dashboard / timeline for one document --------------------------------------------
    doc = client.get(f"{API}/{ar2025}/financials", headers=owner).json()
    assert (doc["scope"], doc["periods"]) == ("document", ["FY2024", "FY2025"])
    facts = {f["id"]: f for f in doc["facts"]}
    revenue = by(doc["cells"], metric="revenue", period="FY2025")
    assert revenue["status"] == "value"
    assert facts[revenue["primary_fact_id"]]["value"] == "12400000000000"
    assert revenue["change"]["value"] == "0.1809523809523809523809523809523810"
    assert revenue["change"]["formula_key"] == "yoy_change"
    roe = by(doc["calculations"], metric="roe", period="FY2025")
    assert roe["value"] == "0.07341772151898734177215189873417722"
    assert {facts[i]["evidence"]["page_number"] for i in roe["input_fact_ids"]} == {2, 5}
    assert {r["period"]: r["status"] for r in doc["reconciliations"]} == {
        "FY2024": "BALANCED",
        "FY2025": "BALANCED",
    }

    # --- Company timeline across both reports ---------------------------------------------
    company = client.get(f"{API}/{ar2025}/financials?scope=company", headers=owner).json()
    assert company["scope"] == "company" and len(company["documents"]) == 2
    assert company["periods"] == ["FY2023", "FY2024", "FY2025"]
    facts = {f["id"]: f for f in company["facts"]}
    # FY2024 revenue: 10,500 in the 2025 report, 10,520 in the 2024 report → a conflict.
    conflict = by(company["cells"], metric="revenue", period="FY2024")
    assert (conflict["status"], conflict["primary_fact_id"]) == ("conflict", None)
    assert sorted(facts[i]["value"] for i in conflict["fact_ids"]) == [
        "10500000000000",
        "10520000000000",
    ]
    growth = by(company["calculations"], metric="revenue_growth", period="FY2025")
    assert (growth["status"], growth["reason_code"]) == ("not_possible", "INCOMPATIBLE_INPUTS")
    # FY2024 net income agrees in both: one value, taken from the 2024 report (its own year).
    agreed = by(company["cells"], metric="net_income", period="FY2024")
    assert agreed["status"] == "value" and len(agreed["fact_ids"]) == 2
    assert facts[agreed["primary_fact_id"]]["document_id"] == ar2024
    assert by(company["reconciliations"], period="FY2023")["status"] == "BALANCED"
    assert any(q["level"] == "warning" and q["metric"] == "revenue" for q in company["quality"])

    # --- Evidence explorer ----------------------------------------------------------------
    ni_cell = by(company["cells"], metric="net_income", period="FY2025")
    net_income = facts[ni_cell["primary_fact_id"]]
    evidence_url = f"{API}/{ar2025}/evidence/{net_income['evidence']['id']}"
    explorer = client.get(evidence_url, headers=owner).json()
    assert explorer["document"]["filename"] == "Annual Report 2025.pdf"
    assert explorer["fact"]["value"] == "1740000000000"
    assert explorer["fact"]["evidence"]["page_number"] == 2
    assert explorer["fact"]["evidence"]["content"] == "Net income | 1,740 | 1,400"
    # Evidence of another document is not reachable through this one, nor by another user.
    other = f"{API}/{ar2024}/evidence/{net_income['evidence']['id']}"
    assert client.get(other, headers=owner).status_code == 404
    assert client.get(f"{API}/{ar2025}/evidence/{uuid.uuid4()}", headers=owner).status_code == 404
    assert client.get(evidence_url, headers=intruder).status_code == 404

    # --- Export: the same values the workspace shows --------------------------------------
    shown = {
        (facts[i]["metric"], c["period"]): facts[i]["value"]
        for c in company["cells"]
        if (i := c["primary_fact_id"])
    }

    response = client.get(f"{API}/{ar2025}/export?format=csv&scope=company", headers=owner)
    assert response.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    exported = {(r["metric"], r["period"]): r["value"] for r in rows if r["timeline"] == "shown"}
    assert exported == shown
    revenue_row = next(r for r in rows if r["metric"] == "revenue" and r["period"] == "FY2025")
    assert (revenue_row["value"], revenue_row["source_page"], revenue_row["unit"]) == (
        "12400000000000",
        "2",
        "absolute",
    )
    assert revenue_row["evidence_link"].startswith(f"/documents/{ar2025}/evidence/")
    disputed = {r["timeline"] for r in rows if (r["metric"], r["period"]) == ("revenue", "FY2024")}
    assert disputed == {"conflict"}

    payload = client.get(f"{API}/{ar2025}/export?format=json&scope=company", headers=owner).json()
    exported_json = {
        (f["metric"], f["period"]): f["value"]
        for f in payload["financial_facts"]
        if f["timeline"] == "shown"
    }
    assert exported_json == shown
    roe_row = by(payload["calculations"], calculation="roe", period="FY2025")
    assert roe_row["value"] == roe["value"] and "(page 5)" in roe_row["inputs"]

    xlsx = client.get(
        f"{API}/{ar2025}/export?format=xlsx&periods=FY2025&metrics=revenue", headers=owner
    )
    with zipfile.ZipFile(io.BytesIO(xlsx.content)) as z:
        workbook = z.read("xl/workbook.xml").decode()
        sheet = ElementTree.fromstring(z.read("xl/worksheets/sheet1.xml"))
    assert all(name in workbook for name in ("Financial Facts", "Calculations", "Evidence"))
    rows_xml = sheet.findall(".//m:row", NS)
    assert len(rows_xml) == 2  # header + FY2025 revenue only: the filters applied
    header = [c.findtext(".//m:t", namespaces=NS) for c in rows_xml[0].findall("m:c", NS)]
    value_cell = rows_xml[1].findall("m:c", NS)[header.index("value")]
    assert value_cell.get("t") is None  # a number cell...
    assert value_cell.findtext("m:v", namespaces=NS) == "12400000000000"  # ...with exact text

    assert client.get(f"{API}/{ar2025}/financials", headers=intruder).status_code == 404
    assert client.get(f"{API}/{ar2025}/export", headers=intruder).status_code == 404
    denied = client.patch(f"{API}/{ar2025}", json={"company_name": "x"}, headers=intruder)
    assert denied.status_code == 404


def test_csv_export_neutralizes_spreadsheet_formulas():
    body = _csv((["source_text"], [['=HYPERLINK("http://x")'], ["Revenue | 1 | 2"]]))
    text = body.decode("utf-8-sig")
    assert "'=HYPERLINK" in text and "\r\nRevenue | 1 | 2\r\n" in text
