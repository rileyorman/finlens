"""
Quick end-to-end test — runs without Streamlit.
Usage: python test_run.py
"""
import os, json
from dotenv import load_dotenv
from modules.pdf_extractor import extract_text_from_pdf
from modules.claude_analyzer import analyze_financials
from modules.excel_exporter import create_excel_file

load_dotenv()
API_KEY = os.getenv("ANTHROPIC_API_KEY")
PDF_PATH = "test_financials.pdf"

print("Step 1 — Extracting text from PDF...")
with open(PDF_PATH, "rb") as f:
    text = extract_text_from_pdf(f)
print(f"  Extracted {len(text):,} characters")
print(f"  First 300 chars:\n  {text[:300]}\n")

print("Step 2 — Sending to Claude...")
data = analyze_financials(text, API_KEY)
print(f"  Company : {data.get('company_name')}")
print(f"  Period  : {data.get('period')}")
print(f"  Currency: {data.get('currency')}")
print(f"  Income statement rows : {len(data.get('income_statement', []))}")
print(f"  Balance sheet rows    : {len(data.get('balance_sheet', []))}")
print(f"  Cash flow rows        : {len(data.get('cash_flow_statement', []))}")

print("\nStep 3 — Building Excel file...")
excel_bytes = create_excel_file(data)
out_path = "test_output.xlsx"
with open(out_path, "wb") as f:
    f.write(excel_bytes)
print(f"  Saved {len(excel_bytes):,} bytes to {out_path}")

print("\nFull JSON from Claude:")
print(json.dumps(data, indent=2))
