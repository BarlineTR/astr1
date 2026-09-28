import os
import sys
import ssl
import re
import urllib.request

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

ctx = ssl._create_unverified_context()
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'tr,en-US;q=0.7,en;q=0.3'
}

url = "https://www.haberturk.com/ahmet-karakaya-kimdir-kac-yasinda-nereli-ve-hangi-gorevlerde-bulundu-bitlis-valisi-ahmet-karakaya-hayati-ve-biyografisi-3722744"
req = urllib.request.Request(url, headers=HEADERS)
with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
    html = resp.read().decode('utf-8', errors='ignore')
    m = re.search(r'property=["\']og:image["\']\s+content=["\']([^"\']+)["\']', html)
    if m:
        img_url = m.group(1)
        print("og:image:", img_url)
        dest_path = os.path.abspath("ros2_ws/src/astro_vision/data/known_faces/ahmet_karakaya/ahmet_karakaya.jpg")
        with open(dest_path, "wb") as f:
            req_img = urllib.request.Request(img_url, headers=HEADERS)
            with urllib.request.urlopen(req_img, context=ctx, timeout=8) as r:
                content = r.read()
                f.write(content)
        print(f"✅ Saved Ahmet Karakaya portrait ({len(content)//1024} KB)")
