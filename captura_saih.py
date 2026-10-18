#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Captura diaria de datos horarios del SAIH Duero (temperatura y lluvia).

Qué hace, en cada ejecución:
  1. Descarga las páginas de histórico de cada serie (4 en total).
  2. Extrae los datos horarios que la web tiene publicados en ese momento.
  3. Los añade a un CSV acumulado por serie (carpeta datos/), sin duplicar horas.
  4. Anota los huecos (horas sin dato) en datos/huecos.csv.
  5. Escribe datos/estado.json con el resultado de la ejecución.
  6. Termina con error (código 1) si algo no es como se espera, para que
     GitHub lo marque en rojo y avise por correo.

Importante: los huecos se quedan VACÍOS. Nunca se rellenan con ceros ni se inventan.
Solo usa la biblioteca estándar de Python (no hace falta instalar nada).
"""
import csv
import html as htmllib
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Madrid")
CARPETA = Path(os.environ.get("CARPETA_DATOS", "datos"))
BASE = "https://www.saihduero.es/risr/"

# Las cuatro series. Las direcciones son las que se comprobaron a mano.
SERIES = {
    "castrocalbon_temperatura": {
        "url": BASE + "PL284/historico/xATRUFURfRDOywEU",
        "titulo": "Temperatura ambiente",
        "tipo": "temperatura",
    },
    "castrocalbon_lluvia": {
        "url": BASE + "PL284/historico/xADTQNURfRDOywEU",
        "titulo": "Pluviometría",
        "tipo": "lluvia",
    },
    "moralesdelrey_temperatura": {
        "url": BASE + "EA082/historico/xATRUFURfJDOwEUR",
        "titulo": "Temperatura ambiente",
        "tipo": "temperatura",
    },
    "moralesdelrey_lluvia": {
        "url": BASE + "EA082/historico/xADTQNURfJDOwEUR",
        "titulo": "Pluviometría",
        "tipo": "lluvia",
    },
}

# --- Ajustes (SUPUESTOS míos, no datos del SAIH; se pueden cambiar) ---------
# Lluvia por encima de este valor en UNA hora se marca como "dudoso" y no se
# suma en los totales diarios. Motivo: el primer dato de las series de lluvia
# (20/07/2026 00:00) marca 120 l/m2 en las dos estaciones a la vez, y parece
# un artefacto del inicio de la serie, no lluvia real.
UMBRAL_LLUVIA_DUDOSA = 50.0
# Temperaturas fuera de este rango se marcan como "dudoso".
TEMP_MIN, TEMP_MAX = -30.0, 50.0
# Si el último dato de una serie tiene más antigüedad que esto, se avisa.
MAX_ANTIGUEDAD_HORAS = 36
# Una página con menos filas que estas se considera sospechosa.
MIN_FILAS = 24
# -----------------------------------------------------------------------------

CAMPOS = ["epoch", "fecha_hora_local", "valor", "calidad"]

# Formato de la tabla de valores de la web (comprobado en el código fuente):
#   <td class="datefield" data-order="1788127200">31/08/2026 00:00</td>
#   <td class="valuefield" data-order="15.20">15,20</td>
# El número de data-order de la fecha es la hora exacta (segundos desde 1970),
# lo que evita confusiones en el cambio de hora de octubre.
RE_FILA = re.compile(
    r'<td[^>]*class="datefield"[^>]*data-order="(\d+)"[^>]*>[^<]*</td>\s*'
    r'<td[^>]*class="valuefield"[^>]*data-order="([^"]*)"[^>]*>',
    re.S,
)
# Plan B: la matriz de datos de la gráfica   {d:"31/08/2026 00:00", v:15.20}
RE_GRAFICA = re.compile(r'\{\s*d:"(\d\d/\d\d/\d{4} \d\d:\d\d)"\s*,\s*v:\s*(-?[\d.]+)\s*\}')
RE_TITULO = re.compile(r"<h3[^>]*text-themecolor[^>]*>(.*?)</h3>", re.S)


def descargar(url, intentos=3):
    """Descarga una página con reintentos."""
    ultimo_error = None
    for n in range(1, intentos + 1):
        try:
            peticion = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; MeteoValledelEria/1.0)",
                    "Accept-Language": "es-ES,es;q=0.9",
                },
            )
            with urllib.request.urlopen(peticion, timeout=60) as respuesta:
                return respuesta.read().decode("utf-8", errors="replace")
        except Exception as error:  # noqa: BLE001
            ultimo_error = error
            time.sleep(5 * n)
    raise RuntimeError(f"No se pudo descargar la página: {ultimo_error}")


def parsear(pagina):
    """Devuelve (título de la página, {epoch: valor}, método usado)."""
    m = RE_TITULO.search(pagina)
    titulo = ""
    if m:
        titulo = htmllib.unescape(re.sub(r"<[^>]+>", "", m.group(1)))
        titulo = re.sub(r"\s+", " ", titulo).strip()

    datos = {}
    for epoch, valor in RE_FILA.findall(pagina):
        if valor.strip() == "":
            continue  # hora sin dato: se queda vacía
        try:
            datos[int(epoch)] = float(valor)
        except ValueError:
            continue
    if datos:
        return titulo, datos, "tabla"

    # Plan B (por si la web cambia la tabla pero mantiene la gráfica)
    vistos = set()
    for texto, valor in RE_GRAFICA.findall(pagina):
        pliegue = 1 if texto in vistos else 0  # 2ª vez que sale la misma hora: cambio de hora
        vistos.add(texto)
        momento = datetime.strptime(texto, "%d/%m/%Y %H:%M").replace(tzinfo=TZ, fold=pliegue)
        datos[int(momento.timestamp())] = float(valor)
    return titulo, datos, "grafica"


def calidad(tipo, valor):
    if tipo == "lluvia":
        return "dudoso" if (valor < 0 or valor > UMBRAL_LLUVIA_DUDOSA) else "ok"
    return "dudoso" if (valor < TEMP_MIN or valor > TEMP_MAX) else "ok"


def hora_local(epoch):
    return datetime.fromtimestamp(epoch, TZ).strftime("%Y-%m-%d %H:%M")


def leer_csv(ruta):
    datos = {}
    if ruta.exists():
        with ruta.open(newline="", encoding="utf-8") as f:
            for fila in csv.DictReader(f):
                datos[int(fila["epoch"])] = float(fila["valor"])
    return datos


def escribir_csv(ruta, datos, tipo):
    with ruta.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CAMPOS)
        for epoch in sorted(datos):
            v = datos[epoch]
            w.writerow([epoch, hora_local(epoch), f"{v:.2f}", calidad(tipo, v)])


def buscar_huecos(epochs):
    """Lista de (primera hora que falta, última hora que falta, nº de horas)."""
    ordenados = sorted(epochs)
    huecos = []
    for a, b in zip(ordenados, ordenados[1:]):
        if b - a > 3600:
            huecos.append((a + 3600, b - 3600, (b - a) // 3600 - 1))
    return huecos


def main():
    CARPETA.mkdir(parents=True, exist_ok=True)
    ahora = datetime.now(timezone.utc)
    estado = {"ejecucion_utc": ahora.strftime("%Y-%m-%d %H:%M"), "series": {}, "problemas": []}
    filas_huecos = []

    for nombre, cfg in SERIES.items():
        info = {"url": cfg["url"]}
        ruta = CARPETA / f"{nombre}.csv"
        try:
            pagina = descargar(cfg["url"])
            titulo, nuevos, metodo = parsear(pagina)
            if cfg["titulo"].lower() not in titulo.lower():
                raise ValueError(
                    f"La página no es la esperada (título leído: '{titulo}', "
                    f"se esperaba algo con '{cfg['titulo']}')."
                )
            if len(nuevos) < MIN_FILAS:
                raise ValueError(f"Solo se han leído {len(nuevos)} datos; se esperaban al menos {MIN_FILAS}.")

            previos = leer_csv(ruta)
            anadidas = len(set(nuevos) - set(previos))
            cambiadas = sum(1 for e, v in nuevos.items() if e in previos and abs(previos[e] - v) > 1e-9)
            previos.update(nuevos)  # el dato más reciente de la web manda (son datos provisionales)
            escribir_csv(ruta, previos, cfg["tipo"])

            info.update(
                titulo=titulo,
                metodo=metodo,
                datos_leidos=len(nuevos),
                filas_nuevas=anadidas,
                filas_modificadas=cambiadas,
                filas_total=len(previos),
                primer_dato=hora_local(min(previos)),
                ultimo_dato=hora_local(max(previos)),
            )
        except Exception as error:  # noqa: BLE001
            info["error"] = str(error)
            estado["problemas"].append(f"{nombre}: {error}")
        estado["series"][nombre] = info
        time.sleep(2)  # cortesía con la web

    # Informe de huecos y comprobación de frescura, con lo que haya en los CSV
    for nombre, cfg in SERIES.items():
        datos = leer_csv(CARPETA / f"{nombre}.csv")
        if not datos:
            continue
        for desde, hasta, horas in buscar_huecos(datos):
            filas_huecos.append([nombre, hora_local(desde), hora_local(hasta), horas])
        antiguedad_h = (ahora.timestamp() - max(datos)) / 3600
        if antiguedad_h > MAX_ANTIGUEDAD_HORAS:
            estado["problemas"].append(
                f"{nombre}: el último dato tiene {antiguedad_h:.0f} horas de antigüedad "
                f"(límite {MAX_ANTIGUEDAD_HORAS})."
            )

    with (CARPETA / "huecos.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["serie", "primera_hora_sin_dato", "ultima_hora_sin_dato", "horas_sin_dato"])
        w.writerows(filas_huecos)

    (CARPETA / "estado.json").write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")

    for nombre, info in estado["series"].items():
        if "error" in info:
            print(f"[ERROR] {nombre}: {info['error']}")
        else:
            print(
                f"[ok] {nombre}: {info['datos_leidos']} datos leídos, "
                f"{info['filas_nuevas']} nuevos, {info['filas_modificadas']} modificados, "
                f"total {info['filas_total']} ({info['primer_dato']} → {info['ultimo_dato']})"
            )
    if estado["problemas"]:
        print("\nPROBLEMAS:")
        for p in estado["problemas"]:
            print(" -", p)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
