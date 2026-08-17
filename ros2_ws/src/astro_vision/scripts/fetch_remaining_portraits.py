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

KNOWN_FACES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "known_faces"))

TARGETS = [
    ("ahmet_karakaya", [
        "https://www.haberturk.com/ahmet-karakaya-kimdir-kac-yasinda-nereli-ve-hangi-gorevlerde-bulundu-bitlis-valisi-ahmet-karakaya-hayati-ve-biyografisi-3722744",
        "https://www.bitlis.gov.tr/vali-ahmet-karakaya",
        "https://www.taskoprupostasi.com/haber/21774345/bitlis-valisi-ahmet-karakaya-kimdir"
    ]),
    ("batuhan_bingol", [
        "https://www.haberturk.com/batuhan-bingol-kimdir-kac-yasinda-nereli-ahlat-kaymakami-batuhan-bingol-hangi-gorevlerde-bulundu-3616897",
        "https://www.dha.com.tr/gundem/kaymakam-batuhan-bingol-goreve-basladi-2302324"
    ])
]

for slug, urls in TARGETS:
    dest_dir = os.path.join(KNOWN_FACES_DIR, slug)
    os.makedirs(dest_dir, exist_ok=True)
    dest_file = os.path.join(dest_dir, f"{slug}.jpg")

    saved = False
    for url in urls:
        try:
            print(f"Scraping {slug} from {url}...")
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
                html = resp.read().decode('utf-8', errors='ignore')
                imgs = re.findall(r'(https://[^\s"\'<>]+\.(?:jpg|jpeg|png))', html)
                # Filter valid images
                cand_imgs = [img for img in imgs if not any(x in img.lower() for x in ["logo", "icon", "blank", "advert", "banner", "svg"])]
                for img_link in cand_imgs:
                    try:
                        print(f"   Downloading image: {img_link[:65]}...")
                        req_img = urllib.request.Request(img_link, headers=HEADERS)
                        with urllib.request.urlopen(req_img, context=ctx, timeout=8) as r_img:
                            data = r_img.read()
                            if len(data) > 8000:  # > 8KB
                                with open(dest_file, "wb") as f:
                                    f.write(data)
                                print(f"   ✅ Saved: {dest_file} ({len(data)//1024} KB)")
                                saved = True
                                break
                    except Exception as ie:
                        pass
                if saved:
                    break
        except Exception as e:
            print(f"Error {url}: {e}")

    if not saved:
        print(f"❌ Failed to save {slug}")
