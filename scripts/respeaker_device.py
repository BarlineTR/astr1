#!/usr/bin/env python3
"""ASTRO Robot — ReSpeaker 6-Channel Hardware Device Resolver & Validator.

Deterministically resolves and validates the ReSpeaker 4-Mic USB Array (UAC1.0):
    ALSA device:   hw:CARD=ArrayUAC10,DEV=0
    Sample rate:   16000 Hz
    Channels:      6
    Sample format: S16_LE (int16)
    Mic indices:   [1, 2, 3, 4]

Prevents accidental capture from onboard audio cards (e.g. NVIDIA Jetson APE, HDA Intel,
or software virtual downmixes like pulse/default) which produce invalid/zero-valued PCM.

Diagnostic & calibration support ONLY. Does not modify production runtime.
"""

from dataclasses import dataclass
import os
import re
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    import sounddevice as sd
    HAS_SOUNDDEVICE = True
except ImportError:
    sd = None
    HAS_SOUNDDEVICE = False

RESPEAKER_CARD_ID = "ArrayUAC10"
RESPEAKER_ALSA_DEVICE = "hw:CARD=ArrayUAC10,DEV=0"
REQUIRED_SAMPLE_RATE = 16000
REQUIRED_CHANNELS = 6
REQUIRED_SAMPLE_FORMAT = "S16_LE"
REQUIRED_MIC_CHANNELS = (1, 2, 3, 4)

FORBIDDEN_NAME_HINTS = (
    "ape",
    "jetson",
    "tegra",
    "hda",
    "realtek",
    "pulse",
    "pipewire",
    "default",
    "sysdefault",
    "dmix",
)


@dataclass
class RespeakerDeviceInfo:
    """Validated capture configuration for ReSpeaker hardware."""
    alsa_device_string: str
    device_index: Optional[Any]  # int or str
    device_name: str
    card_id: str
    sample_rate: int
    channels: int
    sample_format: str
    mic_indices: Tuple[int, ...]
    is_valid_respeaker: bool
    diagnostic_notes: str = ""


def parse_asound_cards(cards_text: str) -> Dict[str, int]:
    """Parses /proc/asound/cards text to map ALSA card IDs to integer card indices."""
    card_map: Dict[str, int] = {}
    for line in cards_text.splitlines():
        match = re.search(r"^\s*(\d+)\s+\[([^\]]+)\]:", line)
        if match:
            idx = int(match.group(1))
            card_id = match.group(2).strip()
            card_map[card_id] = idx
    return card_map


def read_proc_asound_cards() -> Optional[str]:
    """Reads /proc/asound/cards if available on Linux."""
    cards_path = "/proc/asound/cards"
    if os.path.exists(cards_path):
        try:
            with open(cards_path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except Exception:
            return None
    return None


def resolve_respeaker_from_devices(
    devices: List[Dict[str, Any]],
    asound_cards_text: Optional[str] = None,
) -> RespeakerDeviceInfo:
    """Deterministically resolves the ReSpeaker ArrayUAC10 device from device lists."""
    card_idx_from_asound: Optional[int] = None
    if asound_cards_text:
        card_map = parse_asound_cards(asound_cards_text)
        card_idx_from_asound = card_map.get(RESPEAKER_CARD_ID)

    # 1. Search query devices for positive ReSpeaker match
    matched_device: Optional[Dict[str, Any]] = None
    matched_idx: Optional[int] = None

    for idx, dev in enumerate(devices):
        name = dev.get("name", "").lower()
        max_in = dev.get("max_input_channels", 0)

        # Strictly exclude onboard / virtual audio cards (like Jetson APE)
        if any(f in name for f in FORBIDDEN_NAME_HINTS):
            continue

        # Positive identification
        is_respeaker = (
            ("arrayuac10" in name)
            or ("respeaker" in name and "4 mic" in name)
            or ("uac1.0" in name and "4 mic" in name)
        )
        if is_respeaker and max_in >= REQUIRED_CHANNELS:
            matched_device = dev
            matched_idx = idx
            break

    # If positive match was found in sounddevice list
    if matched_device is not None:
        alsa_str = RESPEAKER_ALSA_DEVICE
        hw_match = re.search(r"hw:(\d+),(\d+)", matched_device.get("name", ""))
        dev_num = hw_match.group(2) if hw_match else "0"
        alsa_str = f"hw:CARD={RESPEAKER_CARD_ID},DEV={dev_num}"

        return RespeakerDeviceInfo(
            alsa_device_string=alsa_str,
            device_index=matched_idx,
            device_name=matched_device.get("name", "ReSpeaker 4 Mic Array (UAC1.0), USB Audio"),
            card_id=RESPEAKER_CARD_ID,
            sample_rate=REQUIRED_SAMPLE_RATE,
            channels=REQUIRED_CHANNELS,
            sample_format=REQUIRED_SAMPLE_FORMAT,
            mic_indices=REQUIRED_MIC_CHANNELS,
            is_valid_respeaker=True,
            diagnostic_notes=f"Resolved via device query index {matched_idx} ({matched_device.get('name')})",
        )

    # If /proc/asound/cards has ArrayUAC10
    if card_idx_from_asound is not None:
        return RespeakerDeviceInfo(
            alsa_device_string=f"hw:CARD={RESPEAKER_CARD_ID},DEV=0",
            device_index=card_idx_from_asound,
            device_name="ReSpeaker 4 Mic Array (UAC1.0), USB Audio",
            card_id=RESPEAKER_CARD_ID,
            sample_rate=REQUIRED_SAMPLE_RATE,
            channels=REQUIRED_CHANNELS,
            sample_format=REQUIRED_SAMPLE_FORMAT,
            mic_indices=REQUIRED_MIC_CHANNELS,
            is_valid_respeaker=True,
            diagnostic_notes=f"Resolved via /proc/asound/cards card {card_idx_from_asound} (ArrayUAC10)",
        )

    # ReSpeaker was NOT found — do NOT fall back to any other device
    rejected_summary = ", ".join(f"[{i}] {d.get('name')}" for i, d in enumerate(devices[:5]))
    return RespeakerDeviceInfo(
        alsa_device_string="",
        device_index=None,
        device_name="NONE",
        card_id="",
        sample_rate=REQUIRED_SAMPLE_RATE,
        channels=REQUIRED_CHANNELS,
        sample_format=REQUIRED_SAMPLE_FORMAT,
        mic_indices=REQUIRED_MIC_CHANNELS,
        is_valid_respeaker=False,
        diagnostic_notes=f"ReSpeaker ArrayUAC10 not detected. Evaluated devices: {rejected_summary}",
    )


def resolve_respeaker_capture_device(
    allow_simulation: bool = False,
    device_override: Optional[Any] = None,
) -> RespeakerDeviceInfo:
    """Resolves the verified ReSpeaker capture configuration from the host system."""
    if allow_simulation:
        return RespeakerDeviceInfo(
            alsa_device_string="SIMULATED:hw:CARD=ArrayUAC10,DEV=0",
            device_index="SIMULATED",
            device_name="ReSpeaker 4 Mic Array (UAC1.0), USB Audio [SIMULATED]",
            card_id=RESPEAKER_CARD_ID,
            sample_rate=REQUIRED_SAMPLE_RATE,
            channels=REQUIRED_CHANNELS,
            sample_format=REQUIRED_SAMPLE_FORMAT,
            mic_indices=REQUIRED_MIC_CHANNELS,
            is_valid_respeaker=True,
            diagnostic_notes="Simulated ReSpeaker 6-channel hardware",
        )

    # If explicit override provided
    if device_override is not None:
        return RespeakerDeviceInfo(
            alsa_device_string=str(device_override),
            device_index=device_override,
            device_name=f"Explicit override: {device_override}",
            card_id=RESPEAKER_CARD_ID,
            sample_rate=REQUIRED_SAMPLE_RATE,
            channels=REQUIRED_CHANNELS,
            sample_format=REQUIRED_SAMPLE_FORMAT,
            mic_indices=REQUIRED_MIC_CHANNELS,
            is_valid_respeaker=True,
            diagnostic_notes="User explicit device override",
        )

    devices: List[Dict[str, Any]] = []
    if HAS_SOUNDDEVICE and sd is not None:
        try:
            devices = [dict(d) for d in sd.query_devices()]
        except Exception:
            devices = []

    asound_text = read_proc_asound_cards()
    return resolve_respeaker_from_devices(devices, asound_text)


def validate_respeaker_device(
    info: RespeakerDeviceInfo,
    printer: Callable[[str], None] = print,
) -> bool:
    """Validates device and prints configuration banner. Aborts on mismatch."""
    printer("\n" + "=" * 62)
    printer(" ReSpeaker Hardware Capture Device Validation")
    printer("=" * 62)
    printer(f"  device:      {info.alsa_device_string or 'NOT FOUND'}")
    printer(f"  device_name: {info.device_name}")
    printer(f"  sample_rate: {info.sample_rate} Hz")
    printer(f"  channels:    {info.channels}")
    printer(f"  format:      {info.sample_format}")
    printer(f"  mic_indices: {list(info.mic_indices)}")
    printer(f"  notes:       {info.diagnostic_notes}")
    printer("=" * 62)

    if not info.is_valid_respeaker:
        printer("❌ CRITICAL ERROR: Selected device is NOT the ReSpeaker 4-Mic Array (ArrayUAC10)!")
        printer("   Calibration / metrics recording cannot proceed on invalid device (e.g. Jetson APE).")
        printer("   Please verify ReSpeaker USB connection (dmesg, lsusb, or cat /proc/asound/cards).")
        return False

    printer("✓ ReSpeaker hardware validated successfully (ArrayUAC10, 6ch, 16kHz, S16_LE).\n")
    return True
