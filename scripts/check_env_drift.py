#!/usr/bin/env python3
"""ASTRO V1 — .env.example ile kaynak kod arasındaki sürüklenmeyi denetler.

Neden: inceleme sırasında .env.example'da kodda hiç okunmayan 14 ayar ve kodda
okunup hiç belgelenmemiş ~30 ayar (OPENAI_API_KEY dahil) bulundu. "Anahtarları
ekledim ama çalışmıyor" sorununun doğrudan sebebi buydu.

NOT: satır bazlı grep yetmez — os.getenv( çağrıları birden çok satıra yayılabiliyor
ve ilk taramada GEMINI_TEXT_MODELS yanlışlıkla "ölü" sanılmıştı. Bu yüzden AST.

Çıkış kodu: 0 = temiz, 1 = sürüklenme var.
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "ros2_ws" / "src"
EXAMPLE = ROOT / ".env.example"

# Kod tarafından okunan ama .env'e ait olmayan işletim sistemi değişkenleri
SYSTEM = {"PYTHONPATH", "LD_LIBRARY_PATH", "CUDA_VISIBLE_DEVICES", "HOME", "PATH", "ROS_DISTRO"}


def keys_read_by_code() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for f in sorted(SRC.rglob("*.py")):
        if "/test/" in str(f):
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            fn = node.func
            is_env = (
                isinstance(fn, ast.Attribute)
                and (
                    fn.attr == "getenv"
                    or (fn.attr == "get" and isinstance(fn.value, ast.Attribute) and fn.value.attr == "environ")
                )
            )
            if not is_env:
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                found.setdefault(arg.value, set()).add(f.name)
    return found


def keys_in_example() -> set[str]:
    if not EXAMPLE.exists():
        print(f"HATA: {EXAMPLE} bulunamadı", file=sys.stderr)
        sys.exit(1)
    return set(re.findall(r"^([A-Z_0-9]+)=", EXAMPLE.read_text(encoding="utf-8"), re.M))


def duplicate_keys() -> list[str]:
    seen, dupes = set(), []
    for line in EXAMPLE.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Z_0-9]+)=", line)
        if m:
            if m.group(1) in seen:
                dupes.append(m.group(1))
            seen.add(m.group(1))
    return dupes


def main() -> int:
    code = {k: v for k, v in keys_read_by_code().items() if k not in SYSTEM}
    doc = keys_in_example()

    undocumented = sorted(set(code) - doc)
    dead = sorted(doc - set(code))
    dupes = duplicate_keys()

    ok = True
    if undocumented:
        ok = False
        print("❌ Kodda okunuyor ama .env.example'da BELGELENMEMİŞ:")
        for k in undocumented:
            print(f"     {k:38} ({', '.join(sorted(code[k])[:2])})")
    if dead:
        ok = False
        print("❌ .env.example'da var ama kodda HİÇ OKUNMUYOR (ölü ayar):")
        for k in dead:
            print(f"     {k}")
    if dupes:
        ok = False
        print("❌ .env.example'da TEKRAR EDEN anahtar (dotenv sonuncuyu kullanır):")
        for k in sorted(set(dupes)):
            print(f"     {k}")

    if ok:
        print(f"✅ Yapılandırma tutarlı — {len(doc)} anahtar, hepsi kodda okunuyor, tekrar yok.")
        return 0
    print("\nDüzeltme: .env.example'ı gerçek koda göre güncelleyin.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
