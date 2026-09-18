#!/usr/bin/env python3
"""Giriş sahnesindeki GLB'yi web için küçültür.

    python3 web/scripts/optimize-model.py <girdi.glb> <cikti.glb>

Yapılan üç şey ve gerekçeleri:

1. `metallicRoughness` dokusu atılır. Malzemenin `metallicFactor` değeri zaten 0,
   yani doku hiçbir görsel etki üretmeden 2,26 MB yer kaplıyor ve çözülünce
   64 MB ekran kartı belleği istiyordu.
2. `occlusion` dokusu atılır. Fotogrametri taramasının taban rengi zaten pişmiş
   gölge taşıyor; ayrıca modelin ikinci bir UV kümesi yok, bu yüzden Three.js
   dokuyu kullanmıyordu bile.
3. Kalan taban rengi ve normal dokuları küçültülür. 4096², ekranda en fazla
   birkaç yüz piksel kaplayan bir nesne için gereğinden fazla.

Geometri olduğu gibi kalır: 95.895 üçgen web için makul ve sıkıştırma
(Draco/meshopt) ek çalışma zamanı bağımlılığı getirirdi.
"""

from __future__ import annotations

import io
import json
import struct
import sys

from PIL import Image

# Hangi dokunun hangi boyuta indirileceği. Atılacaklar None.
TARGET_SIZE = {
    "baseColorTexture": 2048,
    "normalTexture": 1024,
    "occlusionTexture": None,
    "metallicRoughnessTexture": None,
}
JPEG_QUALITY = 86


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


def write_glb(path: str, gltf: dict, blob: bytes) -> None:
    json_chunk = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    json_chunk += b" " * ((4 - len(json_chunk) % 4) % 4)
    blob += b"\0" * ((4 - len(blob) % 4) % 4)
    total = 12 + 8 + len(json_chunk) + 8 + len(blob)
    with open(path, "wb") as handle:
        handle.write(struct.pack("<III", 0x46546C67, 2, total))
        handle.write(struct.pack("<II", len(json_chunk), 0x4E4F534A))
        handle.write(json_chunk)
        handle.write(struct.pack("<II", len(blob), 0x004E4942))
        handle.write(blob)


def slot_of(gltf: dict, image_index: int) -> str | None:
    """Bir görüntünün malzemede hangi yuvada kullanıldığını bulur."""
    material = gltf["materials"][0]
    pbr = material.get("pbrMetallicRoughness", {})
    slots = {
        "normalTexture": material.get("normalTexture"),
        "occlusionTexture": material.get("occlusionTexture"),
        "baseColorTexture": pbr.get("baseColorTexture"),
        "metallicRoughnessTexture": pbr.get("metallicRoughnessTexture"),
    }
    for name, reference in slots.items():
        if reference is None:
            continue
        if gltf["textures"][reference["index"]].get("source") == image_index:
            return name
    return None


def main(source: str, destination: str) -> None:
    gltf, blob = read_glb(source)
    views = gltf["bufferViews"]

    # Yeniden kurulacak parçalar: her bufferView'ın yeni içeriği.
    payloads: list[bytes] = []
    for view in views:
        start = view.get("byteOffset", 0)
        payloads.append(blob[start : start + view["byteLength"]])

    material = gltf["materials"][0]
    pbr = material.setdefault("pbrMetallicRoughness", {})
    dropped: list[str] = []

    print(f"girdi : {source}  ({len(blob) / 1e6:.2f} MB ikili veri)")

    for index, image in enumerate(gltf.get("images", [])):
        slot = slot_of(gltf, index)
        target = TARGET_SIZE.get(slot or "", None)
        view_index = image["bufferView"]
        before = len(payloads[view_index])

        if target is None:
            payloads[view_index] = b""
            dropped.append(slot or f"image{index}")
            print(f"  {slot:<24} atıldı        ({before / 1e6:.2f} MB kazanç)")
            continue

        picture = Image.open(io.BytesIO(payloads[view_index]))
        original = picture.size
        picture = picture.convert("RGB").resize((target, target), Image.LANCZOS)
        out = io.BytesIO()
        picture.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        payloads[view_index] = out.getvalue()
        print(
            f"  {slot:<24} {original[0]}² -> {target}²   "
            f"{before / 1e6:.2f} -> {len(payloads[view_index]) / 1e6:.2f} MB"
        )

    # Atılan dokuların malzeme referansları kaldırılmalı, yoksa yükleyici
    # boş bir bufferView'ı çözmeye çalışır.
    if "occlusionTexture" in dropped:
        material.pop("occlusionTexture", None)
    if "metallicRoughnessTexture" in dropped:
        pbr.pop("metallicRoughnessTexture", None)

    # İkili veriyi baştan kur ve tüm offsetleri yeniden yaz.
    rebuilt = bytearray()
    for view, payload in zip(views, payloads):
        padding = (4 - len(rebuilt) % 4) % 4
        rebuilt.extend(b"\0" * padding)
        view["byteOffset"] = len(rebuilt)
        view["byteLength"] = len(payload)
        rebuilt.extend(payload)

    gltf["buffers"][0]["byteLength"] = len(rebuilt)
    write_glb(destination, gltf, bytes(rebuilt))

    import os

    print(
        f"çıktı : {destination}  "
        f"({os.path.getsize(source) / 1e6:.2f} MB -> {os.path.getsize(destination) / 1e6:.2f} MB)"
    )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])
