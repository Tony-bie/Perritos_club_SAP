import os
import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("SAP_SOC_BASE_URL")
TOKEN = os.getenv("SAP_SOC_TOKEN")


HEADERS = {"Authorization": f"Bearer {TOKEN}"}

# Fetch first page
r = requests.get(f"{BASE_URL}/logs/current", headers=HEADERS, params={"page": 1})
payload = r.json()

records = payload["data"]

# Fetch remaining pages
for page in range(2, payload["total_pages"] + 1):
    r = requests.get(f"{BASE_URL}/logs/current", headers=HEADERS, params={"page": page})
    records.extend(r.json()["data"])

# Convert to DataFrame
df = pd.DataFrame(records)
print(df.head())