import os
import platform

import requests
import urllib3


FMP_API_KEY = os.environ.get("FMP_API_KEY", "").strip()


def _make_session():
    session = requests.Session()
    session.trust_env = False
    if platform.system() == "Windows":
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        session.verify = False
    return session


def get_company_profile(ticker):
    """Get company profile - price, market cap, beta, volume."""
    session = _make_session()
    try:
        url = f"https://financialmodelingprep.com/stable/profile?symbol={ticker}&apikey={FMP_API_KEY}"
        response = session.get(url, timeout=10)
        print(f"Company Profile Status: {response.status_code}, Body: {response.text[:300]}")
        if response.status_code != 200:
            return None
        data = response.json()
        if isinstance(data, list) and data:
            return data[0]
        return None
    except Exception as e:
        print(f"Exception: {e}")
        return None


def get_earnings_calendar(ticker, limit=8):
    """Get earnings history with EPS and revenue actuals vs estimates."""
    session = _make_session()
    try:
        url = (
            "https://financialmodelingprep.com/stable/earnings-calendar"
            f"?symbol={ticker}&limit={limit}&apikey={FMP_API_KEY}"
        )
        response = session.get(url, timeout=10)
        print(f"Earnings Calendar Status: {response.status_code}, Body: {response.text[:300]}")
        if response.status_code != 200:
            return []
        data = response.json()
        if not isinstance(data, list):
            return []
        symbol = (ticker or "").upper()
        results = []
        for item in data:
            if not isinstance(item, dict) or item.get("symbol") != symbol:
                continue
            results.append({
                "date": item.get("date"),
                "epsActual": item.get("epsActual"),
                "epsEstimated": item.get("epsEstimated"),
                "revenueActual": item.get("revenueActual"),
                "revenueEstimated": item.get("revenueEstimated"),
            })
            if len(results) >= limit:
                break
        return results
    except Exception as e:
        print(f"Exception: {e}")
        return []


if __name__ == "__main__":
    import json

    print("Testing FMP API...")
    profile = get_company_profile("NVDA")
    print("Profile:", json.dumps(profile, indent=2) if profile else "None")
    earnings = get_earnings_calendar("NVDA")
    print("Earnings Calendar:", json.dumps(earnings, indent=2) if earnings else "None")
