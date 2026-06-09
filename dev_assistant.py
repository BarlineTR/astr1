#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Üç LLM'li Geliştirme Asistanı (dev_assistant.py)
================================================

Abacus.AI LLM API'lerini kullanarak üç aşamalı bir yazılım geliştirme
boru hattı (pipeline) çalıştırır:

  1. GPT     -> Yazılım Mühendisi   (kod üretir)
  2. Claude  -> Kod İnceleyici      (üretilen kodu review eder)
  3. Gemini  -> Test / QA Uzmanı    (test/QA/log analizi yapar)

Tüm aşamalar Türkçe raporlanır ve sonuç yeni bir git branch'e commit edilir.

Bu bir CLI aracıdır (interaktif DEĞİLDİR). Görev, komut satırından parametre
olarak verilir.

Kullanım örneği:
    python3 dev_assistant.py "rosidl_buffer paketi için bir ring buffer sınıfı yaz"

Daha fazla seçenek için:
    python3 dev_assistant.py --help
"""

import argparse
import datetime
import os
import re
import subprocess
import sys
import textwrap

try:
    import abacusai
    from abacusai.api_class.enums import LLMName
except ImportError:
    print("HATA: 'abacusai' paketi bulunamadı. Lütfen 'pip install abacusai' çalıştırın.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Yapılandırma: Her rol için kullanılacak LLM modeli
# ---------------------------------------------------------------------------
MODELS = {
    "engineer": LLMName.OPENAI_GPT5,        # GPT  -> kod üretimi
    "reviewer": LLMName.CLAUDE_V4_5_SONNET,  # Claude -> kod incelemesi
    "tester":   LLMName.GEMINI_2_5_PRO,      # Gemini -> test / QA / log analizi
}

# Modeller kullanılamazsa düşülecek yedek (fallback) modeller
FALLBACK_MODELS = {
    "engineer": [LLMName.OPENAI_GPT4_1, LLMName.OPENAI_GPT4O],
    "reviewer": [LLMName.CLAUDE_V3_7_SONNET, LLMName.CLAUDE_V3_5_SONNET],
    "tester":   [LLMName.GEMINI_2_PRO, LLMName.GEMINI_1_5_PRO],
}

# Terminal renkleri (ANSI)
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    MAGENTA = "\033[95m"
    RED = "\033[91m"
    GRAY = "\033[90m"


def _no_color():
    """Renk istenmediğinde tüm kodları boşalt."""
    for attr in dir(C):
        if not attr.startswith("_") and attr.isupper():
            setattr(C, attr, "")


# ---------------------------------------------------------------------------
# Yardımcı fonksiyonlar
# ---------------------------------------------------------------------------
def banner(text, color=C.CYAN):
    line = "═" * 70
    print(f"\n{color}{C.BOLD}{line}{C.RESET}")
    print(f"{color}{C.BOLD}  {text}{C.RESET}")
    print(f"{color}{C.BOLD}{line}{C.RESET}\n")


def info(msg):
    print(f"{C.GRAY}» {msg}{C.RESET}")


def run_git(args, cwd):
    """Bir git komutu çalıştır ve (returncode, stdout, stderr) döndür."""
    proc = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def call_llm(client, role, prompt, system_message, max_tokens=4000, temperature=0.2):
    """
    Belirtilen rol için LLM'i çağırır. Birincil model başarısız olursa
    yedek modellere düşer.
    """
    candidates = [MODELS[role]] + FALLBACK_MODELS.get(role, [])
    last_err = None
    for model in candidates:
        try:
            info(f"Model çağrılıyor: {model}")
            resp = client.evaluate_prompt(
                prompt=prompt,
                system_message=system_message,
                llm_name=model,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return resp.content, str(model)
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"{C.YELLOW}  ! {model} başarısız oldu: {e}{C.RESET}")
            continue
    raise RuntimeError(f"Tüm modeller başarısız oldu ({role}). Son hata: {last_err}")


def extract_code_blocks(text):
    """Markdown kod bloklarını (```...```) çıkarır. Yoksa boş liste döner."""
    pattern = r"```(?:[a-zA-Z0-9_+\-]*)\n(.*?)```"
    return re.findall(pattern, text, re.DOTALL)


# ---------------------------------------------------------------------------
# Aşama tanımları (prompt'lar)
# ---------------------------------------------------------------------------
PROJECT_CONTEXT = textwrap.dedent("""\
    Proje bağlamı:
    - Bu bir ROS2 'rosidl' monorepo fork'udur.
    - 19 paket vardır; özel 'buffer' paketleri geliştirilmektedir
      (rosidl_buffer, rosidl_buffer_backend vb.).
    - Build sistemi: ament_cmake ve ament_python.
    - Aktif geliştirme branch'i: rolling.
    Lütfen yanıtlarını bu bağlamı dikkate alarak ver.
""")

ENGINEER_SYSTEM = (
    "Sen kıdemli bir yazılım mühendisisin ve ROS2 / rosidl ekosisteminde uzmansın. "
    "Verilen görev için temiz, üretim kalitesinde, iyi yorumlanmış kod üret. "
    "Kodu uygun dilde markdown kod bloğu (```) içinde ver. "
    "Kodun ardından kısa bir Türkçe açıklama ekle. Tüm açıklamaların TÜRKÇE olsun."
)

REVIEWER_SYSTEM = (
    "Sen titiz bir kıdemli kod inceleyicisin (code reviewer). ROS2/rosidl, C++, "
    "Python, CMake ve ament build sistemlerinde uzmansın. Sana verilen kodu "
    "incele: doğruluk, güvenlik, performans, okunabilirlik, hata yönetimi, "
    "ROS2/ament en iyi pratiklerine uygunluk açısından değerlendir. "
    "Bulgularını numaralı maddeler halinde, önem derecesiyle (KRİTİK/ORTA/DÜŞÜK) "
    "belirt. Sonunda genel bir değerlendirme ve onay durumu (ONAYLANDI / "
    "DÜZELTME GEREKLİ) ver. Tüm yanıtın TÜRKÇE olsun."
)

TESTER_SYSTEM = (
    "Sen bir Test/QA uzmanısın. ROS2 paketleri için test stratejileri, birim "
    "testleri (gtest/pytest/launch_testing), kenar durumları (edge case) ve log "
    "analizi konusunda uzmansın. Sana verilen kod ve inceleme raporuna dayanarak: "
    "(1) önerilen test senaryolarını, (2) yazılması gereken örnek test kodunu, "
    "(3) olası hata/log analizini ve dikkat edilmesi gereken QA risklerini "
    "açıkla. Tüm yanıtın TÜRKÇE olsun."
)


# ---------------------------------------------------------------------------
# Ana akış
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Üç LLM'li (GPT + Claude + Gemini) ROS2 geliştirme asistanı.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Örnekler:
              python3 dev_assistant.py "rosidl_buffer için thread-safe ring buffer yaz"
              python3 dev_assistant.py "X özelliğini ekle" --no-commit
              python3 dev_assistant.py "X özelliğini ekle" --branch feature/x --no-color
        """),
    )
    parser.add_argument("task", help="Yapılacak geliştirme görevi (Türkçe açıklama).")
    parser.add_argument("--branch", default=None,
                        help="Oluşturulacak git branch adı (varsayılan: otomatik üretilir).")
    parser.add_argument("--no-commit", action="store_true",
                        help="Sonuçları git'e commit ETME.")
    parser.add_argument("--no-color", action="store_true",
                        help="Renkli çıktıyı kapat.")
    parser.add_argument("--output-dir", default="dev_assistant_output",
                        help="Üretilen dosyaların kaydedileceği klasör (repo köküne göre).")
    parser.add_argument("--repo", default=os.path.dirname(os.path.abspath(__file__)),
                        help="Git deposunun kök dizini (varsayılan: bu script'in dizini).")
    args = parser.parse_args()

    if args.no_color:
        _no_color()

    repo = os.path.abspath(args.repo)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    banner("ÜÇ LLM'Lİ GELİŞTİRME ASİSTANI", C.MAGENTA)
    print(f"{C.BOLD}Görev:{C.RESET} {args.task}")
    print(f"{C.BOLD}Depo :{C.RESET} {repo}")
    print(f"{C.BOLD}Zaman:{C.RESET} {timestamp}")

    client = abacusai.ApiClient()

    # Çıktı klasörü
    out_dir = os.path.join(repo, args.output_dir)
    os.makedirs(out_dir, exist_ok=True)

    report_lines = []

    def log_report(title, body, model):
        report_lines.append(f"\n## {title}\n")
        report_lines.append(f"*Model: `{model}`*\n")
        report_lines.append(body + "\n")

    # ---------------- AŞAMA 1: GPT - Kod Üretimi ----------------
    banner("AŞAMA 1/3 — GPT (Yazılım Mühendisi): Kod Üretimi", C.BLUE)
    eng_prompt = (
        f"{PROJECT_CONTEXT}\n\nGÖREV:\n{args.task}\n\n"
        "Bu görevi yerine getiren kodu üret. Hangi dosyaya yazılması gerektiğini de belirt."
    )
    engineer_out, eng_model = call_llm(
        client, "engineer", eng_prompt, ENGINEER_SYSTEM, max_tokens=4000
    )
    print(f"\n{C.GREEN}{engineer_out}{C.RESET}\n")
    log_report("AŞAMA 1 — GPT (Yazılım Mühendisi): Üretilen Kod", engineer_out, eng_model)

    # Üretilen kod bloklarını dosyaya kaydet
    code_blocks = extract_code_blocks(engineer_out)
    saved_files = []
    if code_blocks:
        for i, block in enumerate(code_blocks, 1):
            fname = os.path.join(out_dir, f"generated_{timestamp}_{i}.txt")
            with open(fname, "w", encoding="utf-8") as f:
                f.write(block)
            saved_files.append(fname)
        info(f"{len(code_blocks)} kod bloğu kaydedildi -> {out_dir}")
    else:
        info("Üretilen yanıtta kod bloğu bulunamadı (yalnızca açıklama).")

    # ---------------- AŞAMA 2: Claude - Kod İncelemesi ----------------
    banner("AŞAMA 2/3 — Claude (Kod İnceleyici): Code Review", C.YELLOW)
    rev_prompt = (
        f"{PROJECT_CONTEXT}\n\nORİJİNAL GÖREV:\n{args.task}\n\n"
        f"YAZILIM MÜHENDİSİNİN ÜRETTİĞİ ÇIKTI:\n{engineer_out}\n\n"
        "Yukarıdaki kodu detaylı incele ve raporla."
    )
    reviewer_out, rev_model = call_llm(
        client, "reviewer", rev_prompt, REVIEWER_SYSTEM, max_tokens=3000
    )
    print(f"\n{C.CYAN}{reviewer_out}{C.RESET}\n")
    log_report("AŞAMA 2 — Claude (Kod İnceleyici): İnceleme Raporu", reviewer_out, rev_model)

    # ---------------- AŞAMA 3: Gemini - Test / QA / Log Analizi ----------------
    banner("AŞAMA 3/3 — Gemini (Test/QA Uzmanı): Test & QA Analizi", C.GREEN)
    test_prompt = (
        f"{PROJECT_CONTEXT}\n\nORİJİNAL GÖREV:\n{args.task}\n\n"
        f"ÜRETİLEN KOD:\n{engineer_out}\n\n"
        f"KOD İNCELEME RAPORU:\n{reviewer_out}\n\n"
        "Yukarıdakilere dayanarak test/QA/log analizi yap."
    )
    tester_out, test_model = call_llm(
        client, "tester", test_prompt, TESTER_SYSTEM, max_tokens=3000
    )
    print(f"\n{C.MAGENTA}{tester_out}{C.RESET}\n")
    log_report("AŞAMA 3 — Gemini (Test/QA Uzmanı): Test & QA Analizi", tester_out, test_model)

    # ---------------- Raporu kaydet ----------------
    report_header = textwrap.dedent(f"""\
        # Geliştirme Asistanı Raporu

        - **Görev:** {args.task}
        - **Tarih:** {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        - **Mühendis modeli (GPT):** `{eng_model}`
        - **İnceleyici modeli (Claude):** `{rev_model}`
        - **Test/QA modeli (Gemini):** `{test_model}`
        - **Kaydedilen kod dosyaları:** {", ".join(os.path.basename(f) for f in saved_files) or "yok"}
        """)
    report_path = os.path.join(out_dir, f"rapor_{timestamp}.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_header + "\n".join(report_lines))

    banner("ÖZET RAPOR", C.MAGENTA)
    print(f"{C.BOLD}Rapor dosyası:{C.RESET} {report_path}")
    for sf in saved_files:
        print(f"{C.BOLD}Kod dosyası  :{C.RESET} {sf}")

    # ---------------- Git commit ----------------
    if args.no_commit:
        info("--no-commit verildi; git işlemi atlanıyor.")
        return

    banner("GIT — Yeni Branch'e Commit", C.BLUE)

    # Git deposu mu kontrol et
    rc, _, _ = run_git(["rev-parse", "--is-inside-work-tree"], repo)
    if rc != 0:
        print(f"{C.RED}HATA: {repo} bir git deposu değil. Commit atlanıyor.{C.RESET}")
        return

    # Git kimliği ayarlı değilse, yerel bir varsayılan ayarla (commit'in
    # "Author identity unknown" hatasıyla başarısız olmaması için).
    rc, name, _ = run_git(["config", "user.name"], repo)
    if rc != 0 or not name:
        run_git(["config", "user.name", "Dev Assistant"], repo)
        run_git(["config", "user.email", "dev-assistant@local"], repo)
        info("Git kimliği ayarlanmadığından yerel varsayılan kullanıldı.")

    branch = args.branch or f"dev-assistant/{timestamp}"
    rc, out, err = run_git(["checkout", "-b", branch], repo)
    if rc != 0:
        print(f"{C.YELLOW}Branch oluşturulamadı ('{branch}'): {err}{C.RESET}")
        info("Mevcut branch üzerinde commit deneniyor.")
    else:
        info(f"Yeni branch oluşturuldu: {branch}")

    # Sadece üretilen çıktı klasörünü ekle
    run_git(["add", args.output_dir], repo)
    commit_msg = f"dev-assistant: {args.task[:60]}"
    rc, out, err = run_git(["commit", "-m", commit_msg], repo)
    if rc == 0:
        info("Commit başarılı.")
        _, head, _ = run_git(["rev-parse", "--short", "HEAD"], repo)
        _, cur_branch, _ = run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo)
        print(f"{C.GREEN}{C.BOLD}✓ Branch '{cur_branch}' üzerinde commit edildi (HEAD: {head}).{C.RESET}")
    else:
        print(f"{C.YELLOW}Commit yapılmadı (değişiklik yok olabilir): {err or out}{C.RESET}")

    banner("TAMAMLANDI ✓", C.GREEN)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nİptal edildi.")
        sys.exit(130)
    except Exception as exc:  # noqa: BLE001
        print(f"\n{C.RED}HATA: {exc}{C.RESET}")
        sys.exit(1)
