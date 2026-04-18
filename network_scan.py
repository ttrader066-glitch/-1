#!/usr/bin/env python3
"""
Skaner sieci lokalnej - szukanie drukarek i innych urzadzen
Uzycie: python3 network_scan.py [podsiec]
Przyklad: python3 network_scan.py 192.168.1.0/24
"""

import socket
import concurrent.futures
import ipaddress
import sys
import os
from datetime import datetime

DEFAULT_NETWORK = "192.168.1.0/24"
TIMEOUT = 0.5
MAX_WORKERS = 150

# Porty drukarek i innych urzadzen
PRINTER_PORTS = {
    515:  "LPD/LPR",
    631:  "IPP (drukarka)",
    9100: "RAW/JetDirect",
    9101: "JetDirect-2",
    9102: "JetDirect-3",
}

OTHER_PORTS = {
    80:   "HTTP",
    443:  "HTTPS",
    8080: "HTTP-alt",
    22:   "SSH",
    23:   "Telnet",
    445:  "SMB",
    3389: "RDP",
    21:   "FTP",
}

ALL_PORTS = {**PRINTER_PORTS, **OTHER_PORTS}


def get_hostname(ip: str) -> str:
    try:
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return "-"


def scan_ports(ip: str) -> dict:
    open_ports = {}
    for port, name in ALL_PORTS.items():
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(TIMEOUT)
            if sock.connect_ex((ip, port)) == 0:
                open_ports[port] = name
            sock.close()
        except Exception:
            pass
    return open_ports


def is_printer(open_ports: dict) -> bool:
    return any(p in open_ports for p in PRINTER_PORTS)


def scan_host(ip: str) -> dict | None:
    ports = scan_ports(ip)
    if not ports:
        return None
    hostname = get_hostname(ip)
    printer = is_printer(ports)
    return {"ip": ip, "hostname": hostname, "ports": ports, "printer": printer}


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "nieznane"


def auto_detect_network() -> str:
    local_ip = get_local_ip()
    parts = local_ip.rsplit(".", 1)
    if len(parts) == 2:
        return f"{parts[0]}.0/24"
    return DEFAULT_NETWORK


def main():
    if len(sys.argv) > 1:
        network_str = sys.argv[1]
    else:
        network_str = auto_detect_network()
        print(f"Automatycznie wykryta siec: {network_str}")
        print(f"Twoje IP: {get_local_ip()}")
        print(f"(Mozesz podac inna podsiec: python3 {sys.argv[0]} 10.0.0.0/24)\n")

    try:
        network = ipaddress.IPv4Network(network_str, strict=False)
    except ValueError as e:
        print(f"Blad: nieprawidlowy format sieci: {e}")
        sys.exit(1)

    hosts = list(network.hosts())
    total = len(hosts)

    print(f"Skanowanie sieci: {network}")
    print(f"Szukam drukarek (porty: 515/LPD, 631/IPP, 9100/JetDirect)")
    print(f"Hostow do sprawdzenia: {total}")
    print(f"Start: {datetime.now().strftime('%H:%M:%S')}")
    print("-" * 72)

    results = []
    done = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_ip = {executor.submit(scan_host, str(ip)): str(ip) for ip in hosts}
        for future in concurrent.futures.as_completed(future_to_ip):
            done += 1
            result = future.result()
            if result:
                results.append(result)
            if done % 25 == 0 or done == total:
                pct = int(done / total * 100)
                printers = sum(1 for r in results if r["printer"])
                print(f"  [{pct:3}%] {done}/{total} | Urzadzenia: {len(results)} | Drukarki: {printers}", end="\r")

    results.sort(key=lambda x: list(map(int, x["ip"].split("."))))
    printers = [r for r in results if r["printer"]]
    others = [r for r in results if not r["printer"]]

    print("\n" + "=" * 72)
    print(f"WYNIKI - {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 72)

    # Drukarki najpierw
    if printers:
        print(f"\n DRUKARKI znalezione: {len(printers)}\n")
        print(f"  {'IP':<18} {'Hostname':<28} {'Uslugi'}")
        print("  " + "-" * 68)
        for r in printers:
            services = ", ".join(f"{p}/{n}" for p, n in r["ports"].items())
            print(f"  {r['ip']:<18} {r['hostname']:<28} {services}")
    else:
        print("\n  Nie znaleziono drukarek.")
        print("  Sprawdz czy drukarka jest wlaczona i podlaczona do sieci.")

    # Pozostale urzadzenia
    if others:
        print(f"\n INNE AKTYWNE URZADZENIA: {len(others)}\n")
        print(f"  {'IP':<18} {'Hostname':<28} {'Porty'}")
        print("  " + "-" * 68)
        for r in others:
            ports_str = ", ".join(map(str, r["ports"].keys()))
            print(f"  {r['ip']:<18} {r['hostname']:<28} {ports_str}")

    print("\n" + "=" * 72)

    output_file = "wyniki_skanowania.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"Skanowanie sieci: {network}\n")
        f.write(f"Data: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Drukarki: {len(printers)} | Inne urzadzenia: {len(others)}\n\n")
        if printers:
            f.write("DRUKARKI:\n")
            f.write(f"{'IP':<18} {'Hostname':<28} {'Uslugi'}\n")
            f.write("-" * 72 + "\n")
            for r in printers:
                services = ", ".join(f"{p}/{n}" for p, n in r["ports"].items())
                f.write(f"{r['ip']:<18} {r['hostname']:<28} {services}\n")
            f.write("\n")
        f.write("WSZYSTKIE URZADZENIA:\n")
        f.write(f"{'IP':<18} {'Hostname':<28} {'Porty'}\n")
        f.write("-" * 72 + "\n")
        for r in results:
            ports_str = ", ".join(map(str, r["ports"].keys()))
            marker = "[DRUKARKA] " if r["printer"] else ""
            f.write(f"{r['ip']:<18} {r['hostname']:<28} {marker}{ports_str}\n")

    print(f"Wyniki zapisane do: {os.path.abspath(output_file)}")


if __name__ == "__main__":
    main()
