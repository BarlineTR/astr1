import usb.core
import struct

dev = usb.core.find(idVendor=0x2886, idProduct=0x0018)
print("Device found:", dev is not None)
if dev is not None:
    # Try reading DOAANGLE (Module 21, Offset 0)
    try:
        data = dev.ctrl_transfer(0xC0, 0, 0xC0 | 0, 21, 8, 1000)
        val = struct.unpack_from("<i", data)[0]
        print(f"✅ DOAANGLE (Mod 21, Off 0): {val}")
    except Exception as e:
        print(f"❌ DOAANGLE error: {e}")

    # Try reading SPEECHDETECTED (Module 19, Offset 22)
    try:
        data = dev.ctrl_transfer(0xC0, 0, 0xC0 | 22, 19, 8, 1000)
        val = struct.unpack_from("<i", data)[0]
        print(f"✅ SPEECHDETECTED (Mod 19, Off 22): {val}")
    except Exception as e:
        print(f"❌ SPEECHDETECTED error: {e}")

    # Try reading AECFREEZEONOFF (Module 18, Offset 7)
    try:
        data = dev.ctrl_transfer(0xC0, 0, 0xC0 | 7, 18, 8, 1000)
        val = struct.unpack_from("<i", data)[0]
        print(f"✅ AECFREEZEONOFF (Mod 18, Off 7): {val}")
    except Exception as e:
        print(f"❌ AECFREEZEONOFF error: {e}")
