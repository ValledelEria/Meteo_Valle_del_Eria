#!/usr/bin/env python3
"""Captura incremental y segura de cuatro series meteorologicas SAIH Duero.

CSV historicos: epoch,fecha_hora_local,valor,calidad (UTF-8, coma, punto decimal).
No se crean filas artificiales para horas sin observacion.
"""
import csv
import html
import json
import math
import os
import re
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Europe/Madrid')
DATOS = Path(os.environ.get('CARPETA_DATOS', 'datos'))
BASE = 'https://www.saihduero.es/risr/'
SERIES = {
    'castrocalbon_temperatura': (BASE + 'PL284/historico/xATRUFURfRDOywEU', 'Temperatura ambiente', 'temperatura'),
    'castrocalbon_lluvia': (BASE + 'PL284/historico/xADTQNURfRDOywEU', 'Pluviometría', 'lluvia'),
    'moralesdelrey_temperatura': (BASE + 'EA082/historico/xATRUFURfJDOwEUR', 'Temperatura ambiente', 'temperatura'),
    'moralesdelrey_lluvia': (BASE + 'EA082/historico/xADTQNURfJDOwEUR', 'Pluviometría', 'lluvia'),
}
CAMPOS = ['epoch', 'fecha_hora_local', 'valor', 'calidad']
RE_FILA = re.compile(r'<td\b(?=[^>]*\bclass=["\'][^"\']*\bdatefield\b)(?=[^>]*\bdata-order=["\'](\d+)["\'])[^>]*>.*?</td>\s*<td\b(?=[^>]*\bclass=["\'][^"\']*\bvaluefield\b)(?=[^>]*\bdata-order=["\']([^"\']*)["\'])[^>]*>', re.I | re.S)
RE_TITULO = re.compile(r'<h3[^>]*text-themecolor[^>]*>(.*?)</h3>', re.I | re.S)
RE_GRAFICA = re.compile(r'\{\s*d\s*:\s*["\'](\d\d/\d\d/\d{4} \d\d:\d\d)["\']\s*,\s*v\s*:\s*(-?\d+(?:\.\d+)?)\s*\}')
MIN_FILAS = 24
MAX_ANTIGUEDAD_HORAS = 36
# Los datos anteriores a la ventana de 49 dias nunca se sustituyen.
DIAS_REVISION = 49


def descargar(url, intentos=3):
    error = None
    for intento in range(intentos):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'MeteoValleEria/2.0', 'Accept-Language': 'es-ES'})
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read().decode('utf-8', errors='replace')
        except Exception as exc:
            error = exc
            if intento < intentos - 1:
                time.sleep(3 * (intento + 1))
    raise RuntimeError(f'Error de descarga: {error}')


def parsear(pagina):
    m = RE_TITULO.search(pagina)
    titulo = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', '', m.group(1)))).strip() if m else ''
    valores = {}
    for ep, valor in RE_FILA.findall(pagina):
        if not valor.strip():
            continue
        try:
            numero = float(valor.replace(',', '.'))
            if math.isfinite(numero):
                valores[int(ep)] = numero
        except ValueError:
            continue
    if valores:
        return titulo, valores, 'tabla'
    vistos = set()
    for fecha, valor in RE_GRAFICA.findall(pagina):
        pliegue = int(fecha in vistos)
        vistos.add(fecha)
        dt = datetime.strptime(fecha, '%d/%m/%Y %H:%M').replace(tzinfo=TZ, fold=pliegue)
        valores[int(dt.timestamp())] = float(valor)
    return titulo, valores, 'grafica'


def calidad(tipo, valor):
    if tipo == 'lluvia':
        return 'dudoso' if valor < 0 or valor > 50 else 'ok'
    return 'dudoso' if valor < -30 or valor > 50 else 'ok'


def leer_csv(ruta):
    """Fallar ante CSV corrupto; nunca sustituirlo silenciosamente."""
    if not ruta.exists():
        return {}
    salida = {}
    with ruta.open('r', encoding='utf-8-sig', newline='') as f:
        lector = csv.DictReader(f)
        if lector.fieldnames != CAMPOS:
            raise ValueError(f'Cabeceras inesperadas en {ruta}: {lector.fieldnames}')
        ultimo = None
        for numero, fila in enumerate(lector, start=2):
            try:
                epoch = int(fila['epoch'])
                valor = float(fila['valor'])
                esperado = datetime.fromtimestamp(epoch, TZ).strftime('%Y-%m-%d %H:%M')
                if not math.isfinite(valor) or epoch % 3600 or fila['fecha_hora_local'] != esperado:
                    raise ValueError('hora o valor no valido')
                if fila['calidad'] not in ('ok', 'dudoso'):
                    raise ValueError('calidad desconocida')
                if ultimo is not None and epoch <= ultimo:
                    raise ValueError('horas duplicadas o desordenadas')
                salida[epoch] = valor
                ultimo = epoch
            except (ValueError, TypeError, OverflowError) as exc:
                raise ValueError(f'{ruta}:{numero}: {exc}') from exc
    return salida


def generar_csv(ruta, valores, tipo):
    with ruta.open('w', encoding='utf-8', newline='') as f:
        escritor = csv.writer(f, lineterminator='\n')
        escritor.writerow(CAMPOS)
        for epoch, valor in sorted(valores.items()):
            local = datetime.fromtimestamp(epoch, TZ).strftime('%Y-%m-%d %H:%M')
            escritor.writerow([epoch, local, f'{valor:.2f}', calidad(tipo, valor)])


def preparar(anteriores, nuevos, ahora_epoch):
    """Anade horas; corrige solo en ventana disponible sin borrar historico."""
    limite = ahora_epoch - DIAS_REVISION * 86400
    resultado = dict(anteriores)
    cambios = 0
    for epoch, valor in nuevos.items():
        if epoch > ahora_epoch + 3600 or epoch % 3600 or not math.isfinite(valor):
            raise ValueError(f'epoch o valor inesperado: {epoch} / {valor}')
        if epoch not in resultado:
            resultado[epoch] = valor
        elif epoch >= limite and round(resultado[epoch], 2) != round(valor, 2):
            resultado[epoch] = valor
            cambios += 1
    return resultado, len(set(resultado) - set(anteriores)), cambios


def huecos(valores):
    claves = sorted(valores)
    for anterior, siguiente in zip(claves, claves[1:]):
        if siguiente - anterior > 3600:
            yield anterior + 3600, siguiente - 3600, (siguiente - anterior)//3600 - 1


def ejecutar():
    DATOS.mkdir(parents=True, exist_ok=True)
    ahora = datetime.now(timezone.utc)
    registro = {'ejecucion_utc': ahora.isoformat(timespec='seconds'), 'estado': 'error', 'series': {}, 'problemas': []}
    preparados = {}
    try:
        # Primera fase: descargar y validar TODAS las series antes de escribir los CSV.
        for nombre, (url, titulo_esperado, tipo) in SERIES.items():
            pagina = descargar(url)
            titulo, nuevos, metodo = parsear(pagina)
            if titulo_esperado.casefold() not in titulo.casefold():
                raise ValueError(f'{nombre}: titulo inesperado ({titulo!r}); posible cambio web SAIH')
            if len(nuevos) < MIN_FILAS:
                raise ValueError(f'{nombre}: solo {len(nuevos)} observaciones; posible cambio web SAIH')
            if (ahora.timestamp() - max(nuevos)) / 3600 > MAX_ANTIGUEDAD_HORAS:
                raise ValueError(f'{nombre}: ultima observacion SAIH demasiado antigua; revisar servicio')
            antiguos = leer_csv(DATOS / f'{nombre}.csv')
            fusion, altas, cambios = preparar(antiguos, nuevos, int(ahora.timestamp()))
            if not fusion or not set(antiguos).issubset(fusion):
                raise ValueError(f'{nombre}: riesgo de perdida de historico')
            preparados[nombre] = (fusion, tipo)
            registro['series'][nombre] = {'metodo': metodo, 'leidos': len(nuevos), 'nuevos': altas,
                                          'corregidos': cambios, 'total': len(fusion), 'ultimo_epoch': max(fusion)}
            print(f'{nombre}: {len(nuevos)} leidos, {altas} nuevos, {cambios} corregidos')
            time.sleep(1)
        # Segunda fase: generar todos los archivos completos antes de reemplazar los anteriores.
        with tempfile.TemporaryDirectory(prefix='meteo_') as carpeta:
            temporal = Path(carpeta)
            for nombre, (valores, tipo) in preparados.items():
                generar_csv(temporal / f'{nombre}.csv', valores, tipo)
                verificar = leer_csv(temporal / f'{nombre}.csv')
                if len(verificar) != len(valores):
                    raise ValueError(f'{nombre}: error al verificar CSV generado')
            with (temporal / 'huecos.csv').open('w', encoding='utf-8', newline='') as f:
                w = csv.writer(f, lineterminator='\n')
                w.writerow(['serie', 'primera_hora_sin_dato', 'ultima_hora_sin_dato', 'horas_sin_dato'])
                for nombre, (valores, _) in preparados.items():
                    for a, b, cantidad in huecos(valores):
                        w.writerow([nombre, datetime.fromtimestamp(a, TZ).strftime('%Y-%m-%d %H:%M'),
                                    datetime.fromtimestamp(b, TZ).strftime('%Y-%m-%d %H:%M'), cantidad])
            for nombre in preparados:
                os.replace(temporal / f'{nombre}.csv', DATOS / f'{nombre}.csv')
            os.replace(temporal / 'huecos.csv', DATOS / 'huecos.csv')
        registro['estado'] = 'ok'
    except Exception as exc:
        mensaje = str(exc)
        registro['problemas'].append(mensaje)
        print('ERROR:', mensaje, file=sys.stderr)
    # Guardar diagnostico incluso si falla, para que Actions pueda publicarlo.
    (DATOS / 'estado.json').write_text(json.dumps(registro, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if registro['estado'] == 'ok' else 1


if __name__ == '__main__':
    sys.exit(ejecutar())
