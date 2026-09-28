#!/usr/bin/env python3
"""Downloads official portrait photos for all Turkish Cabinet Ministers into known_faces."""

import os
import sys
import ssl
import json
import re
import urllib.request
import urllib.parse

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

ctx = ssl._create_unverified_context()
HEADERS = {
    'User-Agent': 'AstroSocialRobot/1.0 (https://github.com/BarlineTR/astr1; contact@astrorobot.org) Mozilla/5.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'tr,en-US;q=0.7,en;q=0.3'
}

KNOWN_FACES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "known_faces"))

CABINET_MEMBERS = [
    ("cevdet_yilmaz", "Cevdet_Yılmaz", "https://www.haberler.com/cevdet-yilmaz/biyografisi/"),
    ("hakan_fidan", "Hakan_Fidan", "https://www.haberler.com/hakan-fidan/biyografisi/"),
    ("ali_yerlikaya", "Ali_Yerlikaya", "https://www.haberler.com/ali-yerlikaya/biyografisi/"),
    ("yasar_guler", "Yaşar_Güler", "https://www.haberler.com/yasar-guler/biyografisi/"),
    ("mehmet_simsek", "Mehmet_Şimşek", "https://www.haberler.com/mehmet-simsek/biyografisi/"),
    ("mehmet_fatih_kacir", "Mehmet_Fatih_Kacır", "https://www.haberler.com/mehmet-fatih-kacir/biyografisi/"),
    ("yilmaz_tunc", "Yılmaz_Tunç", "https://www.haberler.com/yilmaz-tunc/biyografisi/"),
    ("yusuf_tekin", "Yusuf_Tekin", "https://www.haberler.com/yusuf-tekin/biyografisi/"),
    ("kemal_memisoglu", "Kemal_Memişoğlu", "https://www.haberler.com/kemal-memisoglu/biyografisi/"),
    ("abdulkadir_uraloglu", "Abdulkadir_Uraloğlu", "https://www.haberler.com/abdulkadir-uraloglu/biyografisi/"),
    ("alparslan_bayraktar", "Alparslan_Bayraktar", "https://www.haberler.com/alparslan-bayraktar/biyografisi/"),
    ("ibrahim_yumakli", "İbrahim_Yumaklı", "https://www.haberler.com/ibrahim-yumakli/biyografisi/"),
    ("murat_kurum", "Murat_Kurum", "https://www.haberler.com/murat-kurum/biyografisi/"),
    ("mehmet_nuri_ersoy", "Mehmet_Nuri_Ersoy", "https://www.haberler.com/mehmet-nuri-ersoy/biyografisi/"),
    ("mahinur_ozdemir_goktas", "Mahinur_Özdemir_Göktaş", "https://www.haberler.com/mahinur-ozdemir-goktas/biyografisi/"),
    ("osman_askin_bak", "Osman_Aşkın_Bak", "https://www.haberler.com/osman-askin-bak/biyografisi/"),
    ("vedat_isikhan", "Vedat_Işıkhan", "https://www.haberler.com/vedat-isikhan/biyografisi/"),
    ("omer_bolat", "Ömer_Bolat", "https://www.haberler.com/omer-bolat/biyografisi/"),
    ("selcuk_bayraktar", "Selçuk_Bayraktar", "https://www.haberler.com/selcuk-bayraktar/biyografisi/")
]

def fetch_wiki_image(wiki_title: str) -> list[str]:
    urls = []
    try:
        api_url = f"https://tr.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(wiki_title)}"
        req = urllib.request.Request(api_url, headers=HEADERS)
        with urllib.request.urlopen(req, context=ctx, timeout=6) as resp:
            data = json.loads(resp.read().decode('utf-8', errors='ignore'))
            orig = data.get("originalimage", {}).get("source")
            thumb = data.get("thumbnail", {}).get("source")
            if orig:
                urls.append(orig)
            if thumb:
                urls.append(thumb)
    except Exception:
        pass
    return urls

def fetch_haberler_image(page_url: str) -> list[str]:
    urls = []
    try:
        req = urllib.request.Request(page_url, headers=HEADERS)
        with urllib.request.urlopen(req, context=ctx, timeout=6) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
            m = re.search(r'property=["\']og:image["\']\s+content=["\']([^"\']+)["\']', html)
            if m:
                urls.append(m.group(1))
    except Exception:
        pass
    return urls

def main():
    os.makedirs(KNOWN_FACES_DIR, exist_ok=True)
    print("🇹🇷 Cumhurbaşkanlığı Kabinesi & Bakanlar Portre Veritabanı İndiriliyor...\n")

    success = 0
    for slug, wiki_title, fallback_url in CABINET_MEMBERS:
        person_dir = os.path.join(KNOWN_FACES_DIR, slug)
        os.makedirs(person_dir, exist_ok=True)
        dest_path = os.path.join(person_dir, f"{slug}.jpg")

        image_urls = fetch_wiki_image(wiki_title)
        if not image_urls:
            image_urls = fetch_haberler_image(fallback_url)

        saved = False
        for img_url in image_urls:
            try:
                req = urllib.request.Request(img_url, headers=HEADERS)
                with urllib.request.urlopen(req, context=ctx, timeout=8) as r:
                    content = r.read()
                    if len(content) > 3000:
                        with open(dest_path, "wb") as f:
                            f.write(content)
                        print(f"✅ [{slug}]: {dest_path} ({len(content)//1024} KB)")
                        saved = True
                        success += 1
                        break
            except Exception as e:
                pass

        if not saved:
            # Try secondary search
            alt_urls = fetch_haberler_image(fallback_url)
            for img_url in alt_urls:
                try:
                    req = urllib.request.Request(img_url, headers=HEADERS)
                    with urllib.request.urlopen(req, context=ctx, timeout=8) as r:
                        content = r.read()
                        if len(content) > 3000:
                            with open(dest_path, "wb") as f:
                                f.write(content)
                            print(f"✅ [{slug} (Haberler)]: {dest_path} ({len(content)//1024} KB)")
                            saved = True
                            success += 1
                            break
                except Exception:
                    pass

        if not saved:
            print(f"❌ [{slug}]: Fotoğraf indirilemedi.")

    print(f"\n🎉 Toplam {success}/{len(CABINET_MEMBERS)} Kabine Üyesi fotoğrafı başarıyla bilinen yüzler dizinine eklendi!")

if __name__ == "__main__":
    main()
