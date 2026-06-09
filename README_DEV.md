# 🤖 Üç LLM'li Geliştirme Asistanı (`dev_assistant.py`)

Bu araç, **Abacus.AI** LLM API'lerini kullanarak ROS2 `rosidl` projesinde
üç aşamalı, otomatik bir yazılım geliştirme boru hattı (pipeline) çalıştırır.
Her aşamada farklı bir LLM, farklı bir rol üstlenir:

| Aşama | Model | Rol | Görevi |
|------|-------|-----|--------|
| 1 | **GPT** (`OPENAI_GPT5`) | 👷 Yazılım Mühendisi | Görevi yerine getiren kodu üretir |
| 2 | **Claude** (`CLAUDE_V4_5_SONNET`) | 🔍 Kod İnceleyici | Üretilen kodu review eder |
| 3 | **Gemini** (`GEMINI_2_5_PRO`) | 🧪 Test / QA Uzmanı | Test, QA ve log analizi yapar |

Tüm aşamalar **Türkçe** raporlanır ve sonuçlar **yeni bir git branch'e** commit edilir.

> ℹ️ Bir model geçici olarak kullanılamazsa, araç otomatik olarak yedek
> modellere (ör. GPT-4.1, Claude 3.7, Gemini 2 Pro) düşer.

---

## 📋 Gereksinimler

- Python 3.8+
- `abacusai` Python paketi (kurulu)
- `ABACUS_API_KEY` ortam değişkeni (bu ortamda **zaten ayarlı**)
- Git deposu (`/home/ubuntu/astv1`)

Kurulum gerekiyorsa:

```bash
pip install abacusai
```

---

## 🚀 Kullanım

Bu araç **interaktif değildir** — bir CLI aracıdır. Görevi komut satırından
parametre olarak verirsiniz.

### Temel kullanım

```bash
cd /home/ubuntu/astv1
python3 dev_assistant.py "rosidl_buffer paketi için thread-safe bir ring buffer sınıfı yaz"
```

Araç sırayla:
1. GPT ile kodu üretir,
2. Claude ile kodu inceler,
3. Gemini ile test/QA analizi yapar,
4. Sonuçları `dev_assistant_output/` klasörüne kaydeder,
5. Yeni bir git branch oluşturup commit eder.

### Parametreler

| Parametre | Açıklama |
|-----------|----------|
| `task` (zorunlu) | Yapılacak geliştirme görevi (Türkçe açıklama, tırnak içinde). |
| `--branch ADI` | Oluşturulacak git branch adı (varsayılan: `dev-assistant/<tarih>`). |
| `--no-commit` | Sonuçları git'e **commit etmez** (sadece dosyaya yazar). |
| `--no-color` | Renkli terminal çıktısını kapatır. |
| `--output-dir DIR` | Üretilen dosyaların klasörü (varsayılan: `dev_assistant_output`). |
| `--repo DIR` | Git deposunun kök dizini (varsayılan: script'in bulunduğu dizin). |

### Örnekler

```bash
# 1) Basit görev
python3 dev_assistant.py "rosidl_buffer_backend için basit bir mesaj kuyruğu yaz"

# 2) Commit yapmadan sadece analiz
python3 dev_assistant.py "CMakeLists.txt'e yeni bir test hedefi ekle" --no-commit

# 3) Özel branch adı ve renksiz çıktı
python3 dev_assistant.py "Python bindings için yardımcı fonksiyon ekle" \
    --branch feature/py-helper --no-color
```

---

## 📂 Çıktılar

Her çalıştırma şunları üretir (varsayılan `dev_assistant_output/` içinde):

- `rapor_<zaman>.md` — Üç aşamanın tamamını içeren **Türkçe** Markdown raporu.
- `generated_<zaman>_N.txt` — GPT'nin ürettiği her kod bloğu ayrı dosya olarak.

Ardından bu dosyalar yeni bir git branch'e otomatik commit edilir.

---

## 🌿 Git Akışı

- Araç her çalıştırmada `dev-assistant/<zaman damgası>` adında yeni bir branch
  oluşturur (veya `--branch` ile belirttiğiniz adı kullanır).
- Yalnızca `dev_assistant_output/` klasöründeki dosyalar commit edilir;
  böylece projenizin geri kalanına dokunulmaz.
- Commit sonrası branch'i incelemek için:

  ```bash
  git log --oneline -1
  git diff rolling..HEAD
  ```

- Beğenmezseniz branch'i silebilirsiniz:

  ```bash
  git checkout rolling
  git branch -D dev-assistant/<zaman>
  ```

---

## 🔧 Yapılandırma

Kullanılan modelleri değiştirmek isterseniz `dev_assistant.py` dosyasının
başındaki `MODELS` ve `FALLBACK_MODELS` sözlüklerini düzenleyin:

```python
MODELS = {
    "engineer": LLMName.OPENAI_GPT5,        # Kod üretimi
    "reviewer": LLMName.CLAUDE_V4_5_SONNET,  # Kod incelemesi
    "tester":   LLMName.GEMINI_2_5_PRO,      # Test / QA
}
```

Mevcut tüm model adlarını görmek için:

```bash
python3 -c "from abacusai.api_class.enums import LLMName; print([n for n in dir(LLMName) if not n.startswith('_')])"
```

---

## ⚠️ Notlar

- `ABACUS_API_KEY` bu ortamda hazırdır; ek yapılandırma gerekmez.
- Üretilen kod **öneri niteliğindedir** — projeye eklemeden önce inceleyin.
- LLM çağrıları ağ bağlantısı gerektirir ve görev büyüklüğüne göre
  birkaç dakika sürebilir.
