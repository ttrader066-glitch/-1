#!/usr/bin/env python3
"""
Skaner sieci lokalnej - uruchom lokalnie na swoim komputerze
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
PORTS = [22, 80, 443, 8080, 21, 23, 445, 3389, 8443, 3000]
TIMEOUT = 0.5
MAX_WORKERS = 150


def get_hostname(ip: str) -> str:
    try:
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return "-"


def scan_ports(ip: str) -> list[int]:
    open_ports = []
    for port in PORTS:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(TIMEOUT)
            if sock.connect_ex((ip, port)) == 0:
                open_ports.append(port)
            sock.close()
        except Exception:
            pass
    return open_ports


def scan_host(ip: str) -> dict | None:
    ports = scan_ports(ip)
    if not ports:
        return None
    hostname = get_hostname(ip)
    return {"ip": ip, "hostname": hostname, "ports": ports}


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
    print(f"Liczba hostow do sprawdzenia: {total}")
    print(f"Czas rozpoczecia: {datetime.now().strftime('%H:%M:%S')}")
    print("-" * 70)

    results = []
    done = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_ip = {executor.submit(scan_host, str(ip)): str(ip) for ip in hosts}
        for future in concurrent.futures.as_completed(future_to_ip):
            done += 1
            result = future.result()
            if result:
                results.append(result)
            if done % 50 == 0 or done == total:
                pct = int(done / total * 100)
                print(f"  Postep: {done}/{total} ({pct}%) | Znaleziono: {len(results)}", end="\r")

    results.sort(key=lambda x: list(map(int, x["ip"].split("."))))

    print("\n" + "=" * 70)
    print(f"WYNIKI SKANOWANIA - {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 70)

    if not results:
        print("Nie znaleziono zadnych aktywnych urzadzen.")
    else:
        print(f"\nZnaleziono {len(results)} aktywnych urzadzen:\n")
        print(f"{'IP':<18} {'Hostname':<35} {'Otwarte porty'}")
        print("-" * 70)
        for r in results:
            ports_str = ", ".join(map(str, r["ports"]))
            print(f"{r['ip']:<18} {r['hostname']:<35} {ports_str}")

    print("\n" + "=" * 70)

    # Zapis do pliku
    output_file = "wyniki_skanowania.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"Skanowanie sieci: {network}\n")
        f.write(f"Data: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Znaleziono urzadzen: {len(results)}\n\n")
        f.write(f"{'IP':<18} {'Hostname':<35} {'Otwarte porty'}\n")
        f.write("-" * 70 + "\n")
        for r in results:
            ports_str = ", ".join(map(str, r["ports"]))
            f.write(f"{r['ip']:<18} {r['hostname']:<35} {ports_str}\n")

    print(f"Wyniki zapisane do: {os.path.abspath(output_file)}")


if __name__ == "__main__":
    main()
