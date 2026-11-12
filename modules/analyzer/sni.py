#!/usr/bin/env python3
from scapy.all import *
from scapy.layers.tls.all import *
from datetime import datetime

INTERFACE = "enx94b86dae6662"   # ← your Bluetooth/USB interface
FILTER = "tcp port 443"

seen = set()

def extract_sni(pkt):
    try:
        if pkt.haslayer(TLSClientHello):
            for ext in pkt[TLSClientHello].ext:
                if isinstance(ext, TLS_Ext_ServerName):
                    for name in ext.servernames:
                        sni = name.servername.decode(errors="ignore")
                        if sni and sni not in seen:
                            seen.add(sni)
                            print(f"[{datetime.now().strftime('%H:%M:%S')}] SNI → {sni}")
    except:
        pass

print(f"[*] Listening on {INTERFACE} ...")
print("[*] Open the app on your phone and connect\n")

sniff(iface=INTERFACE, filter=FILTER, prn=extract_sni, store=0)
