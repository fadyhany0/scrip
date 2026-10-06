from curl_cffi import requests
from bs4 import BeautifulSoup

mobile_headers = {
    "user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9",
}

r = requests.get("https://www.amazon.eg/s?k=samsung", headers=mobile_headers, impersonate="safari17_0", timeout=10)
print("Mobile status:", r.status_code, "Len:", len(r.text))
soup = BeautifulSoup(r.text, "lxml")
asins = [div["data-asin"] for div in soup.select("div[data-asin]") if div.get("data-asin")]
print("Mobile search ASINs:", len(asins), asins[:5])
