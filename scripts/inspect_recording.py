import wave

for p in ['/home/okistech/.astro/tts/Recording.wav', '/home/okistech/Desktop/usb_4_mic_array/test/respeaker.wav']:
    try:
        with wave.open(p, 'rb') as wf:
            dur = wf.getnframes() / float(wf.getframerate())
            print(f"{p}: ch={wf.getnchannels()}, rate={wf.getframerate()}, dur={dur:.2f}s")
    except Exception as e:
        print(f"{p}: {e}")
