#!/usr/bin/env python3
"""Inspect ReSpeaker v3.0 DSP Parameters and Channel Configuration on Jetson."""

import sys
import numpy as np

# Tuning parameter IDs for Seeed ReSpeaker 4 Mic Array (XVF3000 / XMOS based)
PARAMETERS = {
    'AECFREEZEONOFF': (18, 'int', 1, 0, 'rw', 'Adaptive Echo Canceler freeze (0=off, 1=on)'),
    'ECHOONOFF': (19, 'int', 1, 1, 'rw', 'Echo canceler on/off (0=off, 1=on)'),
    'NLATTENONOFF': (20, 'int', 1, 1, 'rw', 'Non-linear attenuation on/off (0=off, 1=on)'),
    'NLAEC_MODE': (21, 'int', 1, 0, 'rw', 'Non-linear AEC mode (0=default, 1=medium, 2=aggressive)'),
    'AGCONOFF': (25, 'int', 1, 1, 'rw', 'Automatic Gain Control (0=off, 1=on)'),
    'AGCHDESIRED': (26, 'float', 1, 0.1, 'rw', 'AGC desired high level'),
    'STATNOISEONOFF': (32, 'int', 1, 1, 'rw', 'Stationary noise suppression (0=off, 1=on)'),
    'NONSTATNOISEONOFF': (33, 'int', 1, 1, 'rw', 'Non-stationary noise suppression (0=off, 1=on)'),
    'DOAANGLE': (10, 'int', 1, 0, 'ro', 'DOA Angle (degrees)'),
    'VOICEACTIVITY': (11, 'int', 1, 0, 'ro', 'Voice activity detection (0/1)'),
    'SPEECHPROB': (12, 'float', 1, 0.0, 'ro', 'Speech probability'),
}

def probe_dsp():
    print("=== 1. USB & DSP PARAMETER PROBE ===")
    try:
        import usb.core
        import usb.util
        dev = usb.core.find(idVendor=0x2886, idProduct=0x0018)
        if dev is None:
            print("❌ ReSpeaker device (2886:0018) not found via pyusb!")
            return
        print(f"✅ ReSpeaker Found: {dev.manufacturer} - {dev.product} (Bus {dev.bus} Dev {dev.address})")

        # Read parameters using USB vendor control transfer
        # bRequest: 0 (read), bmRequestType: 0xC0 (Vendor In Device)
        # wValue: parameter_id, wIndex: 0x1C (XVF DSP control interface)
        print("\n--- DSP Parameter Values ---")
        # Try probing interface indices
        found_config = None
        for test_idx in [3, 0x1C, 0, 1, 2, 4, 0x24]:
            for test_req in [0, 0x80, 0x01]:
                for test_type in [0xC0, 0xA1, 0xC1]:
                    try:
                        ret = dev.ctrl_transfer(test_type, test_req, 19, test_idx, 8, timeout=200)
                        if ret:
                            found_config = (test_type, test_req, test_idx)
                            print(f"  [Found Working Control Config]: type=0x{test_type:02X} req=0x{test_req:02X} wIndex=0x{test_idx:02X} -> {bytes(ret)}")
                            break
                    except Exception:
                        pass
                if found_config:
                    break
            if found_config:
                break

        if found_config:
            b_type, b_req, w_idx = found_config
            for name, param_def in PARAMETERS.items():
                param_id = param_def[0]
                param_type = param_def[1]
                try:
                    ret = dev.ctrl_transfer(b_type, b_req, param_id, w_idx, 8, timeout=500)
                    if ret:
                        raw_bytes = bytes(ret)
                        if param_type == 'int':
                            val = int.from_bytes(raw_bytes[:4], byteorder='little', signed=True)
                        elif param_type == 'float':
                            import struct
                            val = struct.unpack('<f', raw_bytes[:4])[0]
                        else:
                            val = raw_bytes
                        print(f"  {name:20s} (ID {param_id:2d}): {val}  [{param_def[5]}]")
                except Exception as e:
                    print(f"  {name:20s} (ID {param_id:2d}): Read Error ({e})")
        else:
            print("  [Note]: Standard USB Control Vendor interface did not respond to vendor read. DSP is running in autonomous standalone hardware mode.")

    except Exception as exc:
        print(f"PyUSB Error: {exc}")
    finally:
        try:
            if 'dev' in locals() and dev is not None:
                import usb.util
                usb.util.dispose_resources(dev)
        except Exception:
            pass

def probe_channels():
    print("\n=== 2. ALSA 6-CHANNEL CAPTURE PROBE ===")
    import subprocess
    import wave
    
    test_wav = "/tmp/probe_6ch.wav"
    cmd = ["arecord", "-D", "hw:0,0", "-f", "S16_LE", "-r", "16000", "-c", "6", "-d", "2", test_wav]
    print(f"Recording 2 seconds of 6-channel audio to {test_wav}...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"❌ arecord failed: {res.stderr}")
        return
    
    with wave.open(test_wav, "rb") as wf:
        n_ch = wf.getnchannels()
        sr = wf.getframerate()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)
        data = np.frombuffer(raw, dtype=np.int16).reshape(-1, n_ch)
        
        print(f"✅ Recorded: {n_frames} frames @ {sr}Hz, {n_ch} channels")
        for ch in range(n_ch):
            ch_data = data[:, ch].astype(np.float32)
            rms = np.sqrt(np.mean(ch_data**2))
            peak = np.max(np.abs(ch_data))
            print(f"  Channel {ch}: RMS={rms:6.1f} | Peak={peak:5.0f} | Min={np.min(ch_data):5.0f} | Max={np.max(ch_data):5.0f}")

if __name__ == "__main__":
    probe_dsp()
    probe_channels()
