#!/usr/bin/env python3
"""Arduino-free CognitiveLoop -> SocialBrain -> real Ollama demonstration.

Run with .venv/bin/python. Default input is a labeled synthetic person;
--camera 0 uses the shared face detector on a fresh webcam snapshot instead.
No ROS nodes, serial ports, cloud APIs or persistent robot memory are used.
This is a component demonstration, not the full robot/audio runtime.
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
for package in ("astro_ai", "astro_vision"):
    sys.path.insert(0, str(ROOT / "ros2_ws" / "src" / package))

from astro_ai.brain.cognitive_loop import CognitiveLoop
from astro_ai.brain.social_brain import SocialBrain
from astro_ai.contracts.person_state import UnifiedPersonState
from astro_ai.local_gemma_client import LocalGemmaClient


def observe(args):
    if args.camera is None:
        people = [] if args.scene == "empty" else [UnifiedPersonState(
            person_id="test_person", name="Deneme kişisi", is_present=True,
            distance_m=1.5, azimuth_deg=15.0, visual_confidence=0.95,
            is_looking_at_robot=True, has_vision=True, can_claim_vision=True,
        )]
        return people, {"source": "SENTETİK TEST", "face_count": len(people)}

    import cv2
    from astro_vision.detection_quality import create_face_detector

    cap = cv2.VideoCapture(args.camera)
    try:
        if not cap.isOpened():
            raise RuntimeError(f"Kamera {args.camera} açılamadı")
        for _ in range(8):
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError("Kamera karesi okunamadı")
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        detector = create_face_detector(Path.home() / ".astro" / "models", cascade)
        found = detector.detect(frame)
        # Laptop camera is uncalibrated: do not pretend to measure depth,
        # identity, eye contact, age or emotion from a bounding box.
        people = [UnifiedPersonState(
            person_id=f"camera_face_{i}", name="Misafir", is_present=True,
            distance_m=2.0, azimuth_deg=0.0, visual_confidence=float(conf),
            has_vision=True, can_claim_vision=True, spatial_uncertainty=1.0,
            raw_attributes={"distance_source": "test_placeholder_not_measurement"},
        ) for i, (_, _, _, _, conf) in enumerate(found)]
        return people, {
            "source": "CANLI WEBCAM ANLIK KARESİ", "face_count": len(people),
            "detector": type(detector).__name__,
            "distance": "ölçülmedi; karar motoruna 2 m test değeri verildi",
        }
    finally:
        cap.release()


def run_turn(args, client, question):
    people, observation = observe(args)
    print("\nALGILAMA:", json.dumps(observation, ensure_ascii=False), flush=True)
    loop = CognitiveLoop(on_telemetry=lambda text: print(text, flush=True))
    brain = SocialBrain(db_path=":memory:", enable_migration=False, cognitive_loop=loop)
    try:
        # Twelve real core steps, scheduled at 10 Hz over this single snapshot.
        for _ in range(12):
            result = loop.step({
                "people": people, "person_detected": bool(people), "vad": False,
                "robot_state": {"head_yaw_deg": 0.0, "is_speaking": False},
            })
            time.sleep(0.1)
        intent = result.behavioral_intent
        print("BİLİŞSEL KARAR:", intent.behavior_type.value if intent else "yok", flush=True)
        person = people[0] if people else None
        passive = brain.process_perception_stimulus("person_detected" if people else "empty_scene", person)
        assert passive.should_speak is False, "Yalnızca algı sözlü cevap başlatmamalı"
        print(f"SADECE GÖRÜNCE: action={passive.action.value}, should_speak={passive.should_speak}, LLM çağrısı=0", flush=True)

        _, decision, prompt = brain.process_dialogue_turn(
            question, person_state=person, active_persona="neutral", explicit_user_turn=True,
        )
        print(f"SORU: {question}\nKONUŞMA KAPISI: {decision.gate_mode}, should_speak={decision.should_speak}", flush=True)
        if not decision.should_speak:
            raise RuntimeError("Açık kullanıcı sorusu konuşma kapısında engellendi")
        # Keep the test's limited evidence explicit, including when no face exists.
        evidence = (
            "\nMASAÜSTÜ TESTİ: Türkçe, en fazla iki kısa cümleyle yanıt ver. "
            "Bu testte yalnızca yüz tespiti var; görüntü pikselleri sana verilmedi. "
            "Nesne, kıyafet, eylem, kimlik veya duygu uydurma. "
            f"Gözlem: {json.dumps(observation, ensure_ascii=False)}. "
            "Kaynak SENTETİK ise gerçek kamera görüntüsü gördüğünü söyleme. "
            "Kaynak WEBCAM ise yalnızca algılanan yüz sayısını söyle; mesafe ölçülmedi. "
            "Yüz sayısı sıfırsa 'Bu karede yüz algılanmadı' de; odanın boş olduğunu iddia etme."
        )
        start = time.monotonic()
        first = None
        chunks = []
        print("GEMMA: ", end="", flush=True)
        for chunk in client.stream(
            [{"role": "system", "content": prompt + evidence}, {"role": "user", "content": question}],
            n_predict=160, timeout=60, first_token_timeout=60,
        ):
            if first is None:
                first = time.monotonic() - start
            chunks.append(chunk)
            print(chunk, end="", flush=True)
        answer = "".join(chunks).strip()
        if not answer:
            raise RuntimeError("Ollama boş cevap döndürdü; bu test başarılı sayılmaz")
        print(f"\nSONUÇ: gerçek model={client.model_name}, ilk metin={first:.2f} sn, toplam={time.monotonic()-start:.2f} sn", flush=True)
        if args.speak:
            subprocess.run(["espeak-ng", "-v", "tr", answer], check=True)
    finally:
        brain.storage._get_connection().close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--scene", choices=("person", "empty"), default="person")
    source.add_argument("--camera", type=int, help="Gerçek webcam aygıtı; ör. 0")
    parser.add_argument("--model", default="gemma4:e2b")
    parser.add_argument("--question", default="Astro, şu an ne görüyorsun?")
    parser.add_argument("--interactive", action="store_true", help="Soruları klavyeden al; her tur yeni gözlem")
    parser.add_argument("--speak", action="store_true", help="Cevabı yerel espeak-ng ile seslendir")
    args = parser.parse_args()
    client = LocalGemmaClient(
        base_url="http://127.0.0.1:11434", backend="ollama", model_name=args.model,
        timeout_s=60, first_token_timeout_s=60,
    )
    if not client.health_check(timeout_s=3):
        parser.error(f"Ollama erişilemiyor veya model kurulu değil: {args.model}")
    print("Arduino yok | ROS yok | hafıza=:memory: | LLM=yerel Ollama | mikrofon yok", flush=True)
    if args.interactive:
        while True:
            question = input("\nSorun (çıkış: q): ").strip()
            if question.lower() in ("q", "exit", "çıkış"):
                break
            if question:
                run_turn(args, client, question)
    else:
        run_turn(args, client, args.question)


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\nTest kapatıldı.")
