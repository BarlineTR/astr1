#!/usr/bin/env python3
"""ASTRO V1 — Kurulu kopyanın kaynakla güncel olduğunu doğrular.

Neden gerekli: `ros2 launch` install/ ağacından çalışır, src/'den DEĞİL.
Kaynağı düzeltip build almadan test edersen, düzelttiğini sandığın hata canlıda
aynen durur. Bu bir kez gerçekten yaşandı: fallback'i onaran commit'ten sonra
build alınmadığı için canlı çalıştırmada aynı AttributeError görüldü.

Ayrıca giriş noktalarının venv yorumlayıcısını gösterdiğini doğrular. Çıplak
`colcon build` (README'nin yasakladığı) shebang'i /usr/bin/python3 yapar ve
düğümler edge_tts, sounddevice gibi venv paketlerini "kurulu değil" sanır.

Kurulum yoksa testler atlanır (CI ve temiz makineler için).
"""

import os
import unittest

WS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SRC = os.path.join(WS, "src")
INSTALL = os.path.join(WS, "install")

PY_PACKAGES = {
    "astro_ai": os.path.join("astro_ai", "astro_ai"),
    "astro_audio": os.path.join("astro_audio", "astro_audio"),
}

ENTRY_POINTS = [
    os.path.join("astro_ai", "lib", "astro_ai", "astro_realtime_node"),
    os.path.join("astro_audio", "lib", "astro_audio", "audio_stream_node"),
]


def _installed_site_packages(pkg: str) -> str:
    base = os.path.join(INSTALL, pkg, "lib")
    if not os.path.isdir(base):
        return ""
    for entry in os.listdir(base):
        cand = os.path.join(base, entry, "site-packages", pkg)
        if os.path.isdir(cand):
            return cand
    return ""


@unittest.skipUnless(os.path.isdir(INSTALL), "ros2_ws/install yok — derleme yapılmamış")
class TestInstalledCopyIsFresh(unittest.TestCase):
    def test_no_module_is_stale(self):
        stale = []
        for pkg, rel_src in PY_PACKAGES.items():
            src_dir = os.path.join(SRC, rel_src)
            inst_dir = _installed_site_packages(pkg)
            if not inst_dir or not os.path.isdir(src_dir):
                continue
            for root, _dirs, files in os.walk(src_dir):
                for name in files:
                    if not name.endswith(".py"):
                        continue
                    src_f = os.path.join(root, name)
                    inst_f = os.path.join(inst_dir, os.path.relpath(src_f, src_dir))
                    if not os.path.exists(inst_f):
                        stale.append(f"KURULMAMIŞ: {os.path.relpath(src_f, WS)}")
                    elif os.path.getmtime(src_f) > os.path.getmtime(inst_f) + 1.0:
                        stale.append(f"BAYAT: {os.path.relpath(src_f, WS)}")

        self.assertEqual(
            stale, [],
            "Kurulu kopya kaynakla uyuşmuyor — `ros2 launch` ESKİ kodu çalıştırır.\n"
            "Çözüm: ./scripts/build.sh\n\n" + "\n".join(stale),
        )


@unittest.skipUnless(os.path.isdir(INSTALL), "ros2_ws/install yok — derleme yapılmamış")
class TestEntryPointsUseVenvPython(unittest.TestCase):
    """README: 'Do not run bare colcon build.' — shebang'i bozar."""

    def test_shebangs_point_at_venv(self):
        venv_python = os.path.join(os.path.dirname(WS), ".venv", "bin", "python")
        wrong = []
        for rel in ENTRY_POINTS:
            path = os.path.join(INSTALL, rel)
            if not os.path.isfile(path):
                continue
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                shebang = fh.readline().strip()
            if not shebang.startswith("#!"):
                continue
            interpreter = shebang[2:].strip()
            if interpreter != venv_python:
                wrong.append(f"{rel}: {interpreter}")

        self.assertEqual(
            wrong, [],
            "Giriş noktaları venv yorumlayıcısını göstermiyor — düğümler edge_tts /\n"
            "sounddevice gibi paketleri göremez. Çıplak `colcon build` yerine\n"
            "./scripts/build.sh kullanın.\n\n" + "\n".join(wrong),
        )


if __name__ == "__main__":
    unittest.main()
