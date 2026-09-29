import asyncio
import edge_tts
import subprocess

async def main():
    communicate = edge_tts.Communicate("Dur Astro!", "tr-TR-EmelNeural")
    await communicate.save("/tmp/dur_astro.mp3")
    subprocess.run(["ffmpeg", "-y", "-i", "/tmp/dur_astro.mp3", "-ar", "16000", "-ac", "1", "/tmp/dur_astro.wav"], check=True)
    print("✅ /tmp/dur_astro.wav generated successfully!")

if __name__ == "__main__":
    asyncio.run(main())
