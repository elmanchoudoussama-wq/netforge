"""
xform.pipeline
--------------
Reads a signal trace bundle (`.cap`/`.pcap`) and returns a transform
descriptor for the iterated-key-fold computation.

EAPOL-Key layout (from start of EAPOL payload):
  0     version
  1     type
  2-3   length
  4     descriptor type
  5-6   key information
  7-8   key length
  9-16  replay counter
  17-48 nonce (32)
  49-64 key IV
  65-72 RSC
  73-80 key ID
  81-96 MIC (16)          ← fixed offset
  97-98 key data length
  99+   key data
"""
import struct
from scapy.all import rdpcap, EAPOL, Dot11Beacon, Dot11Elt


MIC_OFFSET = 81
MIC_LEN = 16


def read_signal_trace(path: str):
    try:
        return rdpcap(path), None
    except Exception as e:
        return None, f"trace read error: {e}"


def _get_ssid(packets):
    """Prefer beacon SSID; fall back to any Dot11Elt SSID."""
    for pkt in packets:
        if pkt.haslayer(Dot11Beacon):
            try:
                # Beacon payload often has SSID in info, but safer via Dot11Elt
                if pkt.haslayer(Dot11Elt):
                    elt = pkt[Dot11Elt]
                    while isinstance(elt, Dot11Elt):
                        if elt.ID == 0 and elt.info:
                            return elt.info.decode("utf-8", errors="ignore")
                        elt = elt.payload
                        if not isinstance(elt, Dot11Elt):
                            break
                # fallback
                info = pkt[Dot11Beacon].info
                if info:
                    return info.decode("utf-8", errors="ignore")
            except Exception:
                pass
    return None


def extract_descriptor(path: str):
    packets, err = read_signal_trace(path)
    if err:
        return None, err

    ssid = _get_ssid(packets)
    m1 = None  # ANonce from AP (no MIC)
    m2 = None  # SNonce + MIC from client

    for pkt in packets:
        if not pkt.haslayer(EAPOL):
            continue
        raw = bytes(pkt[EAPOL])
        if len(raw) < 99:
            continue

        # key information is big-endian at offset 5-6
        key_info = struct.unpack(">H", raw[5:7])[0]

        # must be pairwise (bit 3)
        if not (key_info & 0x0008):
            continue

        has_mic = bool(key_info & 0x0100)
        has_ack = bool(key_info & 0x0080)
        nonce = raw[17:49]

        # Message 1: AP → STA, ACK set, MIC clear
        if has_ack and not has_mic and m1 is None:
            m1 = {
                "anonce": nonce,
                "ap": pkt.addr2,   # transmitter = AP
                "cl": pkt.addr1,   # receiver = client
            }
        # Message 2: STA → AP, MIC set, ACK clear
        elif has_mic and not has_ack and m2 is None:
            if len(raw) < MIC_OFFSET + MIC_LEN:
                continue
            mic = raw[MIC_OFFSET:MIC_OFFSET + MIC_LEN]
            m2 = {
                "snonce": nonce,
                "ap": pkt.addr1,   # receiver = AP
                "cl": pkt.addr2,   # transmitter = client
                "mic": mic,
                "raw": raw,
            }

    # Fallback: any frame with MIC if we didn't get a clean M2
    if m1 and not m2:
        for pkt in packets:
            if not pkt.haslayer(EAPOL):
                continue
            raw = bytes(pkt[EAPOL])
            if len(raw) < 99:
                continue
            key_info = struct.unpack(">H", raw[5:7])[0]
            if not (key_info & 0x0008) or not (key_info & 0x0100):
                continue
            mic = raw[MIC_OFFSET:MIC_OFFSET + MIC_LEN]
            nonce = raw[17:49]
            # prefer client→AP direction if we can tell
            m2 = {
                "snonce": nonce,
                "ap": pkt.addr1,
                "cl": pkt.addr2,
                "mic": mic,
                "raw": raw,
            }
            break

    if not (m1 and m2):
        return None, "no complete transform pair in trace (need M1+M2)"

    try:
        ap_mac = bytes.fromhex(m2["ap"].replace(":", ""))
        cl_mac = bytes.fromhex(m2["cl"].replace(":", ""))
    except Exception as e:
        return None, f"bad MAC address: {e}"

    if len(ap_mac) != 6 or len(cl_mac) != 6:
        return None, "MAC addresses must be 6 bytes"

    # Zero the MIC field for the verification buffer
    zeroed = bytearray(m2["raw"])
    zeroed[MIC_OFFSET:MIC_OFFSET + MIC_LEN] = b"\x00" * MIC_LEN

    tag = ssid or "Unknown"
    return {
        "basis": tag.encode("utf-8", "ignore"),
        "u_left": ap_mac,
        "u_right": cl_mac,
        "n_left": m1["anonce"],
        "n_right": m2["snonce"],
        "msg": bytes(zeroed),
        "target": m2["mic"],
        "tag": tag,
    }, None
