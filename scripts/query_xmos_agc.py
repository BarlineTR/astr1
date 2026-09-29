import usb.core
import struct

dev = usb.core.find(idVendor=0x2886, idProduct=0x0018)
if dev:
    # AGCONOFF (Mod 19, Off 0)
    try:
        data = dev.ctrl_transfer(0xC0, 0, 0xC0 | 0, 19, 8, 1000)
        print("AGCONOFF (Mod 19, Off 0):", struct.unpack_from("<i", data)[0])
    except Exception as e:
        print("AGCONOFF error:", e)

    # AGCMAXGAIN (Mod 19, Off 1)
    try:
        data = dev.ctrl_transfer(0xC0, 0, 0xC0 | 1, 19, 8, 1000)
        print("AGCMAXGAIN (Mod 19, Off 1):", struct.unpack_from("<f", data)[0])
    except Exception as e:
        print("AGCMAXGAIN error:", e)

    # SPEECHDETECTED (Mod 19, Off 22)
    try:
        data = dev.ctrl_transfer(0xC0, 0, 0xC0 | 22, 19, 8, 1000)
        print("SPEECHDETECTED (Mod 19, Off 22):", struct.unpack_from("<i", data)[0])
    except Exception as e:
        print("SPEECHDETECTED error:", e)
