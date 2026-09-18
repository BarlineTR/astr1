#!/usr/bin/env python3
"""Bir GLB modelinin dikey profilini çıkarıp gövde/kubbe dikişini ölçer.

`robot-model.ts` içindeki `domeSeamY` sabiti bu betiğin çıktısından gelir.
Model değiştirilirse değer tahmin edilmez, yeniden ölçülür:

    python3 web/scripts/measure-model-seam.py web/client/public/models/astro-hero.glb

Yöntem: model yüksekliği eşit dilimlere bölünür ve her dilimde köşelerin dikey
eksene olan yatay uzaklığının 95. yüzdeliği hesaplanır. Ardışık iki dilim
arasındaki en büyük düşüş, gövdenin bittiği yerdir — kubbe daha dar başlar.
95. yüzdelik kullanılır çünkü azami değer tek bir tarama gürültüsünden etkilenir.
"""

from __future__ import annotations

import json
import math
import struct
import sys

SLICES = 36
OUTLIER_PERCENTILE = 0.95


def read_glb(path: str) -> tuple[dict, bytes]:
    data = open(path, "rb").read()
    magic, _version, length = struct.unpack("<III", data[:12])
    if magic != 0x46546C67:
        raise SystemExit(f"{path}: GLB başlığı geçersiz")
    offset, chunks = 12, []
    while offset < length:
        chunk_len, chunk_type = struct.unpack("<II", data[offset : offset + 8])
        chunks.append((chunk_type, data[offset + 8 : offset + 8 + chunk_len]))
        offset += 8 + chunk_len
    return json.loads(chunks[0][1].decode("utf-8")), chunks[1][1]


def read_positions(gltf: dict, blob: bytes) -> list[tuple[float, float, float]]:
    primitive = gltf["meshes"][0]["primitives"][0]
    accessor = gltf["accessors"][primitive["attributes"]["POSITION"]]
    view = gltf["bufferViews"][accessor["bufferView"]]
    base = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    stride = view.get("byteStride") or 12
    return [
        struct.unpack_from("<fff", blob, base + i * stride)
        for i in range(accessor["count"])
    ]


def main(path: str) -> None:
    gltf, blob = read_glb(path)
    points = read_positions(gltf, blob)

    ys = [p[1] for p in points]
    y_min, y_max = min(ys), max(ys)
    cx = sum(p[0] for p in points) / len(points)
    cz = sum(p[2] for p in points) / len(points)

    print(f"{path}")
    print(f"  köşe sayısı : {len(points)}")
    print(f"  yükseklik   : {y_max - y_min:.4f} m  ({y_min:.4f} .. {y_max:.4f})")
    print(f"  dikey eksen : x={cx:.4f}  z={cz:.4f}\n")
    print("  dilim   y_orta   köşe   yarıçap(p95)")

    profile: list[tuple[float, float]] = []
    step = (y_max - y_min) / SLICES
    for i in range(SLICES):
        low, high = y_min + step * i, y_min + step * (i + 1)
        chosen = [p for p in points if low <= p[1] < high]
        if not chosen:
            print(f"  {i:>5}  {(low + high) / 2:7.4f}  {0:>5}          —")
            continue
        radii = sorted(math.hypot(p[0] - cx, p[2] - cz) for p in chosen)
        p95 = radii[min(int(len(radii) * OUTLIER_PERCENTILE), len(radii) - 1)]
        profile.append((low, p95))
        print(
            f"  {i:>5}  {(low + high) / 2:7.4f}  {len(chosen):>5}      {p95:.4f}  "
            + "▏" * int(p95 * 100)
        )

    # Dikiş, ORANSAL değil MUTLAK daralmanın en büyük olduğu yerdir.
    #
    # Oransal ölçüt bu modelde yanlış cevap veriyordu: her kubbe tepesinde daralır
    # ve orada yarıçap zaten küçük olduğu için oran şişer. Tepedeki 0,1033 -> 0,0715
    # düşüşü %30,7 iken gerçek dikişteki 0,2167 -> 0,1721 düşüşü yalnızca %20,6.
    # Mutlak ölçütte sıralama tersine döner (0,0446 m > 0,0318 m) ve dikiş kazanır.
    drops = sorted(
        (
            (previous_r - current_r, boundary, previous_r, current_r)
            for (boundary, current_r), (_, previous_r) in zip(profile[1:], profile)
        ),
        reverse=True,
    )

    print("\n  en büyük daralmalar (mutlak):")
    for rank, (delta, boundary, before, after) in enumerate(drops[:3], start=1):
        ratio = delta / before * 100
        print(
            f"    {rank}. y={boundary:.4f}  {before:.4f} -> {after:.4f}  "
            f"= {delta:.4f} m  (%{ratio:.1f})"
        )

    seam = drops[0][1]
    print(f"\n  domeSeamY = {seam:.4f}   (dilim çözünürlüğü ±{step / 2:.4f} m)")
    print(
        "  Bu değeri kabul etmeden önce yukarıdaki profile bakın: dikişin üstünde\n"
        "  yarıçap bir süre sabit kalmalı, sürekli azalıyorsa seçilen yer kubbenin\n"
        "  tepesidir, gövdeyle birleştiği yer değil."
    )


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "web/client/public/models/astro-hero.glb")
