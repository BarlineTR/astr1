#!/usr/bin/env python3
"""ASTRO V1 — XTTS işçi süreci istemcisi.

`xtts_worker.py`'yi XTTS deposunun kendi venv'indeki Python ile başlatır ve
satır tabanlı JSON protokolü üzerinden konuşur. Neden ayrı süreç: XTTS
numpy 1.26 + torch 2.5 ister, ASTRO ise rclpy ABI'si için numpy 2.2'ye
sabitlenmiştir — ikisi aynı yorumlayıcıya sığmaz (bkz. scripts/install_xtts.sh).

Yalnızca standart kütüphane kullanır; ROS'a bağımlı değildir.
"""
import json
import os
import queue
import subprocess
import threading
from pathlib import Path

PREFIX = "@@XTTS@@ "

DEFAULT_HOME = os.path.expanduser("~/.astro/tts")

# Kendi eğitilmiş bir XTTS modeli klasöründe beklenen dosya adları
CUSTOM_MODEL_FILES = {
    "checkpoint": "model.pth",
    "config": "config.json",
    "vocab": "vocab.json",
    "speakers": "speakers_xtts.pth",   # isteğe bağlı
}
OPTIONAL_MODEL_FILES = ("speakers",)


class XttsError(RuntimeError):
    """İşçi başlatılamadı ya da sentez başarısız oldu."""


class XttsClient:
    """Kalıcı XTTS işçi sürecini yöneten ince istemci.

    Model yüklemesi pahalı olduğu için süreç bir kez başlatılır ve açık tutulur.
    `synthesize()` çağrıları bir kilitle sıraya alınır: işçi tek modelli, tek akışlı.
    """

    def __init__(
        self,
        speaker_wav,
        home=None,
        language="tr",
        device="auto",
        half=True,
        batch_size=4,
        model="tts_models/multilingual/multi-dataset/xtts_v2",
        model_dir=None,
        checkpoint=None,
        config=None,
        vocab=None,
        speakers=None,
        logger=None,
    ):
        self.home = Path(os.path.expanduser(home or os.getenv("TTS_XTTS_HOME") or DEFAULT_HOME))
        # İşçi XTTS deposunun içinde çalışır; göreli yol orada başka bir şeye işaret eder.
        self.speaker_wav = os.path.abspath(os.path.expanduser(str(speaker_wav)))
        self.language = language
        self.device = device
        self.half = half
        self.batch_size = batch_size
        self.model = model
        self._log = logger or (lambda level, msg: None)

        # Kendi modeliniz: klasör verilirse dosya adları ondan türetilir, tek tek
        # verilen yollar klasörden gelenleri ezer. Hiçbiri yoksa hazır xtts_v2 kullanılır.
        self.custom_model = self._resolve_custom_model(model_dir, checkpoint, config, vocab, speakers)

        self.proc = None
        self.info = {}
        self._responses = queue.Queue()
        self._ready = threading.Event()
        self._startup_error = None
        self._req_lock = threading.Lock()
        self._req_id = 0

    # --------------------------------------------------------- kendi modeliniz
    @staticmethod
    def _resolve_custom_model(model_dir, checkpoint, config, vocab, speakers):
        """Verilen klasör/yollardan model dosyalarını çözer; hiçbiri yoksa None."""
        explicit = {"checkpoint": checkpoint, "config": config, "vocab": vocab, "speakers": speakers}
        if not model_dir and not any(explicit.values()):
            return None

        resolved = {}
        base = Path(os.path.expanduser(model_dir)) if model_dir else None
        for key, filename in CUSTOM_MODEL_FILES.items():
            given = explicit.get(key)
            if given:
                # Elle verilen yol yoksa sessizce yutulmaz; doğrulama hata döndürür.
                resolved[key] = os.path.abspath(os.path.expanduser(given))
            elif base is not None:
                path = str((base / filename).absolute())
                # speakers_xtts.pth her eğitimde üretilmez: klasörden türetilmiş ve
                # yoksa isteğe bağlı sayılır, model onsuz da klonlama yapar.
                resolved[key] = None if (key in OPTIONAL_MODEL_FILES and not os.path.exists(path)) else path
            else:
                resolved[key] = None
        return resolved

    def _check_custom_model(self):
        """Kendi modeliniz seçiliyse dosyaları doğrular; sorun varsa mesaj döndürür."""
        if not self.custom_model:
            return None
        for key, path in self.custom_model.items():
            if not path:
                if key in OPTIONAL_MODEL_FILES:
                    continue
                return (
                    f"Özel XTTS modeli eksik: {key} yolu verilmedi "
                    f"(TTS_XTTS_MODEL_DIR ya da TTS_XTTS_{key.upper()} ayarlayın)"
                )
            if not os.path.exists(path):
                return f"Özel XTTS modeli dosyası bulunamadı: {path}"
        return None

    # ------------------------------------------------------------------ yollar
    @property
    def python_path(self) -> Path:
        return self.home / ".venv" / "bin" / "python"

    @property
    def worker_path(self) -> Path:
        # İşçi bu paketin içinde durur; ROS payı ile birlikte kurulur.
        return Path(__file__).with_name("xtts_worker.py")

    def check_install(self):
        """Kurulum eksikse açıklayıcı bir mesaj döndürür, tamamsa None."""
        if not self.home.exists():
            return f"XTTS dizini yok: {self.home} — ./scripts/install_xtts.sh çalıştırın"
        if not self.python_path.exists():
            return f"XTTS venv'i yok: {self.python_path} — ./scripts/install_xtts.sh çalıştırın"
        if not os.path.exists(self.speaker_wav):
            return f"Referans ses dosyası yok: {self.speaker_wav}"
        if not self.worker_path.exists():
            return f"İşçi betiği bulunamadı: {self.worker_path}"
        return self._check_custom_model()

    # ------------------------------------------------------------------ yaşam döngüsü
    def start(self):
        """İşçiyi başlatır. Hemen döner; hazır olmasını `wait_ready()` bekler."""
        problem = self.check_install()
        if problem:
            raise XttsError(problem)

        cmd = [
            str(self.python_path),
            str(self.worker_path),
            "--speaker-wav", self.speaker_wav,
            "--language", self.language,
            "--device", self.device,
            "--half", "1" if self.half else "0",
            "--batch-size", str(self.batch_size),
            "--model", self.model,
        ]

        if self.custom_model:
            for key, flag in (("checkpoint", "--checkpoint"), ("config", "--config"),
                              ("vocab", "--vocab"), ("speakers", "--speakers")):
                if self.custom_model.get(key):
                    cmd += [flag, self.custom_model[key]]

        env = os.environ.copy()
        # Kabuk profili ROS Humble'ı source ettiğinde PYTHONPATH venv'in içine sızar
        # ve XTTS, ASTRO'nun numpy 2.x'ini görür. Temizlemek şart.
        env["PYTHONPATH"] = ""
        env["COQUI_TOS_AGREED"] = "1"
        # Fonemleştirici PATH'te "espeak" arar; install_xtts.sh symlink'i venv'in
        # bin'ine koyar, oysa çağıran süreç ASTRO venv'inin PATH'iyle çalışıyor.
        env["PATH"] = f"{self.python_path.parent}{os.pathsep}{env.get('PATH', '')}"
        env["VIRTUAL_ENV"] = str(self.python_path.parent.parent)

        self.proc = subprocess.Popen(
            cmd,
            cwd=str(self.home),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self):
        for line in self.proc.stdout:
            line = line.rstrip("\n")
            if not line.startswith(PREFIX):
                # XTTS kütüphanesinin kendi çıktısı — gürültü, debug'a gider.
                if line.strip():
                    self._log("debug", f"[xtts] {line}")
                continue
            try:
                msg = json.loads(line[len(PREFIX):])
            except json.JSONDecodeError:
                self._log("warn", f"[xtts] ayrıştırılamayan yanıt: {line}")
                continue

            event = msg.get("event")
            if event == "ready":
                self.info = msg
                self._ready.set()
            elif event == "error":
                self._startup_error = f"{msg.get('stage')}: {msg.get('message')}"
                self._ready.set()  # bekleyeni serbest bırak; hata wait_ready'de patlar
            else:
                self._responses.put(msg)
        # Süreç öldü: hazır olmayı bekleyen varsa kilitlenmesin.
        self._ready.set()

    def _read_stderr(self):
        for line in self.proc.stderr:
            line = line.rstrip("\n")
            if line.strip():
                self._log("debug", f"[xtts:err] {line}")

    def wait_ready(self, timeout=300.0):
        """Model yüklenip ısınana kadar bekler. Hata veya zaman aşımında XttsError."""
        if not self._ready.wait(timeout):
            raise XttsError(f"XTTS {timeout:.0f} sn içinde hazır olmadı (model indiriliyor olabilir)")
        if self._startup_error:
            raise XttsError(f"XTTS başlatılamadı — {self._startup_error}")
        if not self.info:
            raise XttsError(f"XTTS süreci beklenmedik şekilde sonlandı (kod {self.returncode})")
        return self.info

    @property
    def is_ready(self):
        return bool(self.info) and self.is_alive

    @property
    def is_alive(self):
        return self.proc is not None and self.proc.poll() is None

    @property
    def returncode(self):
        return None if self.proc is None else self.proc.poll()

    # ------------------------------------------------------------------ sentez
    def synthesize(self, text, out_path, timeout=120.0, language=None):
        """Metni `out_path`'e sentezler ve işçinin yanıtını döndürür."""
        if not self.is_alive:
            raise XttsError(f"XTTS süreci çalışmıyor (kod {self.returncode})")

        with self._req_lock:
            self._req_id += 1
            req_id = self._req_id
            req = {"id": req_id, "text": text, "out": os.path.abspath(str(out_path))}
            if language:
                req["language"] = language

            try:
                self.proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
                self.proc.stdin.flush()
            except (BrokenPipeError, ValueError) as exc:
                raise XttsError(f"XTTS sürecine yazılamadı: {exc}") from exc

            # Gecikmiş/eşleşmeyen yanıtlar atlanır; bekleyen tek istek var.
            while True:
                try:
                    msg = self._responses.get(timeout=timeout)
                except queue.Empty as exc:
                    raise XttsError(f"XTTS {timeout:.0f} sn içinde yanıt vermedi") from exc
                if msg.get("id") == req_id:
                    break

        if not msg.get("ok"):
            raise XttsError(msg.get("message", "bilinmeyen sentez hatası"))
        return msg

    def stop(self):
        """İşçiyi nazikçe kapatır, takılırsa öldürür."""
        if self.proc is None:
            return
        try:
            if self.is_alive:
                self.proc.stdin.write(json.dumps({"cmd": "quit"}) + "\n")
                self.proc.stdin.flush()
                self.proc.wait(timeout=5)
        except Exception:  # noqa: BLE001 — kapanışta hata yutulur
            pass
        finally:
            if self.is_alive:
                self.proc.kill()
            self.proc = None
