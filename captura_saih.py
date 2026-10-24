
#!/usr/bin/env python3
"""Captura incremental de cuatro series meteorológicas SAIH Duero.

CSV históricos:
epoch,fecha_hora_local,valor,calidad

No se crean observaciones artificiales.
Se conserva el histórico y se valida todo antes de escribir.
"""

import csv
import html
import json
import math
import os
import re
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.request

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


# ============================================================
# CONFIGURACIÓN
# ============================================================

TZ = ZoneInfo("Europe/Madrid")

DATOS = Path(os.environ.get("CARPETA_DATOS", "datos"))

# Dominio configurable desde GitHub Actions.
# Alternativa por probar: https://www.sircaduero.info/risr/
BASE = os.environ.get(
    "SAIH_BASE_URL",
    "https://www.sircaduero.info/risr/"
).rstrip("/") + "/"

SERIES = {
    "castrocalbon_temperatura": (
        BASE + "PL284/historico/xATRUFURfRDOywEU",
        "Temperatura ambiente",
        "temperatura",
    ),
    "castrocalbon_lluvia": (
        BASE + "PL284/historico/xADTQNURfRDOywEU",
        "Pluviometría",
        "lluvia",
    ),
    "moralesdelrey_temperatura": (
        BASE + "EA082/historico/xATRUFURfJDOwEUR",
        "Temperatura ambiente",
        "temperatura",
    ),
    "moralesdelrey_lluvia": (
        BASE + "EA082/historico/xADTQNURfJDOwEUR",
        "Pluviometría",
        "lluvia",
    ),
}

CAMPOS = [
    "epoch",
    "fecha_hora_local",
    "valor",
    "calidad",
]

MIN_FILAS = 24
MAX_ANTIGUEDAD_HORAS = 36
DIAS_REVISION = 49


# ============================================================
# EXPRESIONES REGULARES
# ============================================================

RE_FILA = re.compile(
    r'<td\b'
    r'(?=[^>]*\bclass=["\'][^"\']*\bdatefield\b)'
    r'(?=[^>]*\bdata-order=["\'](\d+)["\'])'
    r'[^>]*>.*?</td>\s*'
    r'<td\b'
    r'(?=[^>]*\bclass=["\'][^"\']*\bvaluefield\b)'
    r'(?=[^>]*\bdata-order=["\']([^"\']*)["\'])'
    r'[^>]*>',
    re.I | re.S,
)

RE_TITULO = re.compile(
    r'<h3[^>]*text-themecolor[^>]*>(.*?)</h3>',
    re.I | re.S,
)

RE_GRAFICA = re.compile(
    r'\{\s*d\s*:\s*["\']'
    r'(\d\d/\d\d/\d{4} \d\d:\d\d)'
    r'["\']\s*,\s*v\s*:\s*'
    r'(-?\d+(?:\.\d+)?)\s*\}'
)


# ============================================================
# DESCARGA HTTPS SEGURA
# ============================================================

def descargar(url, intentos=3):
    """Descarga conservando la verificación SSL."""

    error = None

    for intento in range(1, intentos + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "MeteoValleEria/2.1",
                    "Accept-Language": "es-ES",
                    "Accept": "text/html",
                },
            )

            contexto = ssl.create_default_context()

            with urllib.request.urlopen(
                req,
                timeout=45,
                context=contexto,
            ) as respuesta:

                url_final = respuesta.geturl()

                print(
                    f"HTTP {respuesta.status}: {url_final}",
                    flush=True,
                )

                return respuesta.read().decode(
                    "utf-8",
                    errors="replace",
                )

        except urllib.error.HTTPError as exc:
            error = exc

            if 400 <= exc.code < 500 and exc.code != 429:
                break

        except urllib.error.URLError as exc:
            error = exc

            if isinstance(
                exc.reason,
                ssl.SSLCertVerificationError,
            ):
                raise RuntimeError(
                    f"Error SSL en {url}: {exc.reason}. "
                    "Revisar dominio y certificado HTTPS."
                ) from exc

        except Exception as exc:
            error = exc

        print(
            f"Intento {intento}/{intentos} fallido: {error}",
            flush=True,
        )

        if intento < intentos:
            time.sleep(3 * intento)

    raise RuntimeError(
        f"Error de descarga de {url}: {error}"
    )


# ============================================================
# EXTRACCIÓN DE OBSERVACIONES
# ============================================================

def parsear(pagina):

    m = RE_TITULO.search(pagina)

    titulo = (
        re.sub(
            r"\s+",
            " ",
            html.unescape(
                re.sub(r"<[^>]+>", "", m.group(1))
            ),
        ).strip()
        if m
        else ""
    )

    valores = {}

    for ep, valor in RE_FILA.findall(pagina):

        if not valor.strip():
            continue

        try:
            numero = float(valor.replace(",", "."))

            if math.isfinite(numero):
                valores[int(ep)] = numero

        except ValueError:
            continue

    if valores:
        return titulo, valores, "tabla"

    vistos = set()

    for fecha, valor in RE_GRAFICA.findall(pagina):

        pliegue = int(fecha in vistos)
        vistos.add(fecha)

        dt = datetime.strptime(
            fecha,
            "%d/%m/%Y %H:%M",
        ).replace(
            tzinfo=TZ,
            fold=pliegue,
        )

        numero = float(valor)

        if math.isfinite(numero):
            valores[int(dt.timestamp())] = numero

    return titulo, valores, "grafica"


# ============================================================
# CONTROL DE CALIDAD
# ============================================================

def calidad(tipo, valor):

    if tipo == "lluvia":
        return (
            "dudoso"
            if valor < 0 or valor > 50
            else "ok"
        )

    return (
        "dudoso"
        if valor < -30 or valor > 50
        else "ok"
    )


# ============================================================
# LECTURA DEL HISTÓRICO
# ============================================================

def leer_csv(ruta):
    """Nunca sustituir silenciosamente un CSV corrupto."""

    if not ruta.exists():
        return {}

    salida = {}

    with ruta.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as f:

        lector = csv.DictReader(f)

        if lector.fieldnames != CAMPOS:
            raise ValueError(
                f"Cabeceras inesperadas en {ruta}: "
                f"{lector.fieldnames}"
            )

        ultimo = None

        for numero, fila in enumerate(lector, start=2):

            try:
                epoch = int(fila["epoch"])
                valor = float(fila["valor"])

                esperado = datetime.fromtimestamp(
                    epoch,
                    TZ,
                ).strftime("%Y-%m-%d %H:%M")

                if (
                    not math.isfinite(valor)
                    or epoch % 3600
                    or fila["fecha_hora_local"] != esperado
                ):
                    raise ValueError(
                        "Hora o valor no válido"
                    )

                if fila["calidad"] not in (
                    "ok",
                    "dudoso",
                ):
                    raise ValueError(
                        "Calidad desconocida"
                    )

                if (
                    ultimo is not None
                    and epoch <= ultimo
                ):
                    raise ValueError(
                        "Horas duplicadas o desordenadas"
                    )

                salida[epoch] = valor
                ultimo = epoch

            except (
                ValueError,
                TypeError,
                OverflowError,
                KeyError,
            ) as exc:

                raise ValueError(
                    f"{ruta}:{numero}: {exc}"
                ) from exc

    return salida


# ============================================================
# GENERACIÓN DE CSV
# ============================================================

def generar_csv(ruta, valores, tipo):

    with ruta.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as f:

        escritor = csv.writer(
            f,
            lineterminator="\n",
        )

        escritor.writerow(CAMPOS)

        for epoch, valor in sorted(valores.items()):

            local = datetime.fromtimestamp(
                epoch,
                TZ,
            ).strftime("%Y-%m-%d %H:%M")

            escritor.writerow([
                epoch,
                local,
                f"{valor:.2f}",
                calidad(tipo, valor),
            ])


# ============================================================
# FUSIÓN INCREMENTAL
# ============================================================

def preparar(anteriores, nuevos, ahora_epoch):
    """Añadir datos sin borrar histórico."""

    limite = (
        ahora_epoch
        - DIAS_REVISION * 86400
    )

    resultado = dict(anteriores)
    cambios = 0

    for epoch, valor in nuevos.items():

        if (
            epoch > ahora_epoch + 3600
            or epoch % 3600
            or not math.isfinite(valor)
        ):
            raise ValueError(
                f"Epoch o valor inesperado: "
                f"{epoch} / {valor}"
            )

        if epoch not in resultado:
            resultado[epoch] = valor

        elif (
            epoch >= limite
            and round(resultado[epoch], 2)
            != round(valor, 2)
        ):
            resultado[epoch] = valor
            cambios += 1

    altas = len(
        set(resultado) - set(anteriores)
    )

    return resultado, altas, cambios


# ============================================================
# DETECCIÓN DE HUECOS
# ============================================================

def huecos(valores):

    claves = sorted(valores)

    for anterior, siguiente in zip(
        claves,
        claves[1:],
    ):

        if siguiente - anterior > 3600:

            yield (
                anterior + 3600,
                siguiente - 3600,
                (siguiente - anterior) // 3600 - 1,
            )


# ============================================================
# EJECUCIÓN PRINCIPAL
# ============================================================

def ejecutar():

    DATOS.mkdir(
        parents=True,
        exist_ok=True,
    )

    ahora = datetime.now(timezone.utc)
    ahora_epoch = int(ahora.timestamp())

    registro = {
        "ejecucion_utc": ahora.isoformat(
            timespec="seconds"
        ),
        "estado": "error",
        "servidor": BASE,
        "series": {},
        "problemas": [],
    }

    preparados = {}

    try:

        # FASE 1: Descargar y validar las cuatro series.

        for nombre, (
            url,
            titulo_esperado,
            tipo,
        ) in SERIES.items():

            print(
                f"\nProcesando {nombre}",
                flush=True,
            )

            pagina = descargar(url)

            titulo, nuevos, metodo = parsear(
                pagina
            )

            if (
                titulo_esperado.casefold()
                not in titulo.casefold()
            ):
                raise ValueError(
                    f"{nombre}: título inesperado "
                    f"({titulo!r}). "
                    "Posible cambio de web o dominio."
                )

            if len(nuevos) < MIN_FILAS:
                raise ValueError(
                    f"{nombre}: solamente "
                    f"{len(nuevos)} observaciones."
                )

            ultima_observacion = max(nuevos)

            antiguedad = (
                ahora_epoch - ultima_observacion
            ) / 3600

            if antiguedad > MAX_ANTIGUEDAD_HORAS:
                raise ValueError(
                    f"{nombre}: última observación "
                    f"demasiado antigua "
                    f"({antiguedad:.1f} horas)."
                )

            antiguos = leer_csv(
                DATOS / f"{nombre}.csv"
            )

            fusion, altas, cambios = preparar(
                antiguos,
                nuevos,
                ahora_epoch,
            )

            if (
                not fusion
                or not set(antiguos).issubset(fusion)
            ):
                raise ValueError(
                    f"{nombre}: riesgo de pérdida "
                    "de histórico"
                )

            preparados[nombre] = (
                fusion,
                tipo,
            )

            registro["series"][nombre] = {
                "metodo": metodo,
                "leidos": len(nuevos),
                "nuevos": altas,
                "corregidos": cambios,
                "total": len(fusion),
                "ultimo_epoch": max(fusion),
                "antiguedad_horas": round(
                    antiguedad,
                    2,
                ),
            }

            print(
                f"{nombre}: "
                f"{len(nuevos)} leídos, "
                f"{altas} nuevos, "
                f"{cambios} corregidos",
                flush=True,
            )

            time.sleep(1)

        # FASE 2: Generar y verificar archivos.

        with tempfile.TemporaryDirectory(
            prefix="meteo_"
        ) as carpeta:

            temporal = Path(carpeta)

            for nombre, (
                valores,
                tipo,
            ) in preparados.items():

                ruta = (
                    temporal / f"{nombre}.csv"
                )

                generar_csv(
                    ruta,
                    valores,
                    tipo,
                )

                verificar = leer_csv(ruta)

                if len(verificar) != len(valores):
                    raise ValueError(
                        f"{nombre}: error verificando CSV"
                    )

            # Generar registro de huecos.

            ruta_huecos = (
                temporal / "huecos.csv"
            )

            with ruta_huecos.open(
                "w",
                encoding="utf-8",
                newline="",
            ) as f:

                w = csv.writer(
                    f,
                    lineterminator="\n",
                )

                w.writerow([
                    "serie",
                    "primera_hora_sin_dato",
                    "ultima_hora_sin_dato",
                    "horas_sin_dato",
                ])

                for nombre, (
                    valores,
                    _,
                ) in preparados.items():

                    for a, b, cantidad in huecos(
                        valores
                    ):

                        w.writerow([
                            nombre,
                            datetime.fromtimestamp(
                                a,
                                TZ,
                            ).strftime(
                                "%Y-%m-%d %H:%M"
                            ),
                            datetime.fromtimestamp(
                                b,
                                TZ,
                            ).strftime(
                                "%Y-%m-%d %H:%M"
                            ),
                            cantidad,
                        ])

            # Publicar únicamente después de validar.

            for nombre in preparados:

                os.replace(
                    temporal / f"{nombre}.csv",
                    DATOS / f"{nombre}.csv",
                )

            os.replace(
                ruta_huecos,
                DATOS / "huecos.csv",
            )

        registro["estado"] = "ok"

        print(
            "\nActualización completada correctamente",
            flush=True,
        )

    except Exception as exc:

        mensaje = str(exc)

        registro["problemas"].append(
            mensaje
        )

        print(
            f"ERROR: {mensaje}",
            file=sys.stderr,
            flush=True,
        )

    # Guardar diagnóstico incluso si hay error.

    (DATOS / "estado.json").write_text(
        json.dumps(
            registro,
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    return (
        0
        if registro["estado"] == "ok"
        else 1
    )


if __name__ == "__main__":
    sys.exit(ejecutar())
