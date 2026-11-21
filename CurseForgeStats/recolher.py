#!/usr/bin/env python3
"""Tira uma "fotografia" dos downloads dos mods do CurseForge e junta-a ao histórico
(historico.js, lido pela dashboard). Corre isto uma vez por dia (cron ou systemd timer)
para teres a evolução ao longo do tempo.

    ./recolher.py                                  # usa a lista do mods.txt
    ./recolher.py outra-lista.txt
    ./recolher.py https://www.curseforge.com/minecraft/mc-mods/sodium 238222
"""
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

API = "https://api.cfwidget.com"
FICHEIRO = Path(__file__).with_name("historico.js")
# registos mais antigos que isto ficam reduzidos a um por dia, para o ficheiro não crescer sem fim
DIAS_DETALHE = 30


def buscar(url, tentativas=5):
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "cf-dashboard/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                corpo = r.read()
                if r.status == 200 and corpo.strip():
                    return json.loads(corpo)
        except (OSError, ValueError):
            pass
        # a API devolve 202/vazio enquanto vai buscar os dados ao CurseForge
        time.sleep(3 * (i + 1))
    raise RuntimeError(f"falhou {url}")


def caminho_de(linha):
    """Link/ID/nome do mod → caminho no CFWidget (o mesmo que a página faz)."""
    l = re.sub(r"[?#].*$", "", linha.strip()).rstrip("/")
    if l.isdigit():
        return l
    m = re.search(r"curseforge\.com/(.+)", l, re.I)
    if m:
        partes = m.group(1).split("/")
        if partes[0] == "projects" and len(partes) > 1 and partes[1].isdigit():
            return partes[1]
        if len(partes) >= 3:
            return "/".join(partes[:3])
    elif re.fullmatch(r"[a-z0-9][a-z0-9-]*", l, re.I):
        return "minecraft/mc-mods/" + l.lower()
    raise ValueError(f"não percebi: {linha.strip()}")


def ler_fontes(args):
    linhas = []
    if not args:
        args = [str(Path(__file__).with_name("mods.txt"))]
    for a in args:
        if Path(a).is_file():
            linhas += Path(a).read_text(encoding="utf-8").splitlines()
        else:
            linhas.append(a)
    links, autores = [], []
    for l in map(str.strip, linhas):
        if not l or l.startswith("#"):
            continue
        if l.lower().startswith("autor:"):
            autores.append(l.split(":", 1)[1].strip())
        else:
            links.append(caminho_de(l))
    return links, autores


def carregar():
    if not FICHEIRO.exists():
        return []
    txt = FICHEIRO.read_text(encoding="utf-8")
    return json.loads(txt[txt.index("=") + 1:].strip().rstrip(";"))


def compactar(hist):
    """Tira os downloads por ficheiro e, antes dos últimos DIAS_DETALHE dias, fica só o último registo de cada dia."""
    limite = datetime.now(timezone.utc) - timedelta(days=DIAS_DETALHE)
    por_dia, recentes = {}, []
    for s in sorted(hist, key=lambda s: s["t"]):
        for p in s["p"].values():
            p.pop("f", None)
        if datetime.fromisoformat(s["t"]) >= limite:
            recentes.append(s)
        else:
            por_dia[s["t"][:10]] = s
    return list(por_dia.values()) + recentes


def main():
    try:
        links, autores = ler_fontes(sys.argv[1:])
    except ValueError as e:
        raise SystemExit(f"Erro: {e}")
    for autor in autores:
        links += [str(p["id"]) for p in buscar(f"{API}/author/search/{autor}")["projects"]]
    if not links:
        raise SystemExit("Sem mods: põe links no mods.txt ou passa-os como argumentos.")

    snap = {"t": datetime.now(timezone.utc).isoformat(timespec="seconds"), "p": {}}
    for caminho in dict.fromkeys(links):
        try:
            d = buscar(f"{API}/{caminho}")
        except RuntimeError:
            print(f"  ✕ {caminho} (não respondeu)")
            continue
        # só nome e total: a página não usa os downloads de cada ficheiro no histórico
        snap["p"][str(d["id"])] = {"n": d["title"], "d": d["downloads"]["total"]}
        print(f"  {d['title']:<20} {d['downloads']['total']:>7}")

    hist = compactar(carregar() + [snap])
    FICHEIRO.write_text("window.HISTORICO = " + json.dumps(hist, ensure_ascii=False) + ";\n", encoding="utf-8")
    total = sum(p["d"] for p in snap["p"].values())
    print(f"Total {total} · {len(hist)} registos em {FICHEIRO.name}")


if __name__ == "__main__":
    main()
