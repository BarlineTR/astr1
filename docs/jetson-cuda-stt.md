# Jetson'da CUDA'lı STT Kurulumu

Jetson Orin üzerinde `speech_recognition_node` GPU'yu kullanmıyorsa buradasınız. Bu
belge sorunun nasıl doğrulanacağını, kalıcı çözümü ve kalıcı çözüme kadar
kullanabileceğiniz geçici ayarları anlatır.

---

## 1. Belirti

Açılış log'unda şu satır geçiyorsa STT tamamen CPU'da koşuyordur:

```
CUDA ile yüklenemedi (This CTranslate2 package was not compiled with CUDA support)
 — CPU moduna ve hafif modele (base) geçiliyor
✅ [STT] Faster-Whisper hazır (model: base, cihaz: cpu)
```

İki sonucu olur:

- **Yavaş.** Gerçek STT süresi `🎤 [Duyulan]` satırında raporlanır; CPU'da saniyeler
  mertebesine çıkar.
- **Halüsinasyon.** GPU'daki `large-v2` yerine CPU'daki `base` modeli yüklenir. `base`,
  sessizlik ve arka plan gürültüsü üzerinde uydurma cümleler üretmeye eğilimlidir —
  *"Altyazı M.K."*, *"Seçim yüzey."* gibi çıktılar bundandır.

## 2. Sebep

Bu bir yapılandırma hatası değil, paketleme kısıtı. `faster-whisper`'ın altındaki
`ctranslate2` PyPI'de mimariye göre farklı derleniyor ve **aarch64 tekerlekleri
CUDA'sız**. Tekerlek boyutları farkı açıkça gösteriyor:

| Tekerlek (4.8.1, cp310) | Boyut | CUDA |
|---|---|---|
| `manylinux…x86_64.whl` | 39.2 MB | ✅ var |
| `manylinux…aarch64.whl` | **16.6 MB** | ❌ yok |

Aradaki ~23 MB, tekerleğe gömülü CUDA çekirdekleri. `pip install ctranslate2`
Jetson'da her zaman CPU-only sürümü getirir; sürüm yükseltmek işe yaramaz.

Kalıcı çözüm: **CTranslate2'yi Jetson üzerinde CUDA açık şekilde kaynaktan derlemek.**

---

## 3. Kaynaktan derleme

Aşağıdakiler Jetson'ın kendisinde çalıştırılır. Yaklaşık 20-40 dakika sürer.

### 3.1 Ön koşullar

```bash
sudo apt update
sudo apt install -y build-essential cmake git libopenblas-dev
```

CUDA ve cuDNN JetPack ile birlikte gelir; ayrıca kurmayın. Doğrulayın:

```bash
nvcc --version                      # CUDA >= 11.0 olmalı
ls /usr/lib/aarch64-linux-gnu/libcudnn.so*   # cuDNN >= 8 olmalı
```

`nvcc` bulunamıyorsa PATH'e ekleyin:

```bash
export PATH=/usr/local/cuda/bin:$PATH
export LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH
```

### 3.2 C++ kütüphanesini derleyin

Depoyu, kurulu sürümle aynı etikette klonlayın (`pip show ctranslate2` ile bakın):

```bash
git clone --recursive --branch v4.8.1 https://github.com/OpenNMT/CTranslate2.git
cd CTranslate2
mkdir build && cd build
```

Derleme bayrakları — **`WITH_MKL` kullanmayın**, Intel'e özgüdür ve ARM'de derlenmez.
ARM'de CPU arka ucu için OpenBLAS kullanılır:

```bash
cmake .. \
  -DWITH_CUDA=ON \
  -DWITH_CUDNN=ON \
  -DWITH_MKL=OFF \
  -DWITH_OPENBLAS=ON \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CUDA_ARCHITECTURES=87

make -j"$(nproc)"
sudo make install
sudo ldconfig
```

> `CMAKE_CUDA_ARCHITECTURES=87` Orin içindir (compute capability 8.7). Xavier için
> `72`, Nano (Ampere) için `87` kullanın. Yanlış değer derlemeyi geçirir ama çalışma
> anında çekirdek bulunamaz hatası verir.

Jetson'da bellek darsa `make -j$(nproc)` OOM ile ölebilir; `make -j2` deneyin.

### 3.3 Python sarmalayıcısını derleyin

```bash
cd ../python
pip install -r install_requirements.txt
python setup.py bdist_wheel
```

Şimdi PyPI'den gelen CPU-only sürümü kaldırıp yenisini kurun. Proje venv'i
kullanıyorsanız önce onu etkinleştirin:

```bash
source ~/Desktop/astr1/.venv/bin/activate     # venv kullanıyorsanız
pip uninstall -y ctranslate2
pip install dist/*.whl
```

CTranslate2'yi standart olmayan bir dizine kurduysanız, kütüphane yolunu her
çalıştırmada görünür kılmanız gerekir:

```bash
export LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH
```

Bunu kalıcı yapmak için `~/.bashrc`'ye ekleyin — aksi hâlde `ros2 launch` sırasında
`libctranslate2.so` bulunamaz.

### 3.4 Doğrulama

```bash
python -c "import ctranslate2; print(ctranslate2.get_cuda_device_count())"
```

`0` dönerse CUDA hâlâ yok — derleme bayraklarını gözden geçirin. `1` dönmeli.

Ardından robotu başlatın; şu satırı görmelisiniz:

```
✅ [STT] Faster-Whisper hazır (model: large-v2, cihaz: cuda)
```

`🎤 [Duyulan]` satırındaki `RTF` (real-time factor) değeri artık **1.0'ın belirgin
altında** olmalı — yani ses süresinden daha kısa sürede çözülüyor.

---

## 4. Derlemeye kadar geçici çözümler

Kaynaktan derlemeye vaktiniz yoksa, `.env` ile iki seçeneğiniz var.

### 4.1 CPU'da daha iyi model

`base` yerine `small` kullanın. Halüsinasyonlar belirgin şekilde azalır, karşılığında
yaklaşık iki kat yavaşlar:

```bash
STT_FW_CPU_MODEL="small"
```

### 4.2 Bulut STT'yi birincil yapın

Ağınız güvenilirse yerel STT'den tamamen vazgeçebilirsiniz. `speech_recognition_node`
zaten Groq Whisper-large-v3'ü birincil, OpenAI Whisper-1'i yedek olarak deniyor ve
yerel motora ancak ikisi de başarısız olursa düşüyor. Yerel motoru büsbütün kapatmak
için:

```bash
STT_ENGINE="groq"
```

Bu, Jetson'ın GPU'sunu ve RAM'ini XTTS'e bırakır — bellek kabul kontrolünün XTTS'i
reddetme ihtimalini de düşürür (bkz. `.env.example` içindeki `XTTS_*` eşikleri).

---

## 5. İlgili konu: NumPy sürümü

Jetson'da NVIDIA'nın kendi PyTorch derlemesi **NumPy 1.x**'e karşı derlenmiştir. Ortama
NumPy 2.x girerse şu uyarıyı görürsünüz:

```
Failed to initialize NumPy: _ARRAY_API not found
A module that was compiled using NumPy 1.x cannot be run in NumPy 2.2.6
```

Bu uyarı düğümü öldürmez — uzun bir traceback bastığı için öyle görünür — ama
torch↔numpy dönüşümlerini sessizce bozar. `scripts/install.sh` aarch64 algıladığında
numpy'yi otomatik olarak 1.26.4'e sabitler. Elle kurulum yaptıysanız:

```bash
pip install "numpy==1.26.4"
```

Sürümü doğrulayın:

```bash
python -c "import numpy, torch; print(numpy.__version__); print(torch.from_numpy(numpy.zeros(3)))"
```

İkinci komut hata vermeden bir tensör basmalıdır.

---

## 6. Özet kontrol listesi

- [ ] `nvcc --version` çalışıyor, CUDA >= 11.0
- [ ] CTranslate2 `-DWITH_CUDA=ON -DWITH_CUDNN=ON -DWITH_MKL=OFF -DWITH_OPENBLAS=ON` ile derlendi
- [ ] `CMAKE_CUDA_ARCHITECTURES` karta uygun (Orin: 87)
- [ ] `ctranslate2.get_cuda_device_count()` → 1
- [ ] `LD_LIBRARY_PATH` kalıcı olarak ayarlı
- [ ] `numpy` 1.26.4
- [ ] Log'da `cihaz: cuda` ve RTF < 1.0
