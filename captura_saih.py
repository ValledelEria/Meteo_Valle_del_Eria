#!/usr/bin/env python3
"""Observatorio Valle del Eria: capturas puntuales oficiales CHD.

No convierte precipitacion de hora en curso en lluvia horaria cerrada.
No modifica los CSV historicos heredados.
"""
import csv
import hashlib
import io
import json
import math
import os
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

URL = os.getenv('CHD_JSON_URL', 'https://datos.chduero.es/dataset/05988b20-50e9-4306-961b-95a0d11f138e/resource/b7689d17-262c-499d-9676-86d441bab49c/download/estado_pluviometros.json')
DATOS = Path(os.getenv('CARPETA_DATOS', 'datos'))
TZ = ZoneInfo('Europe/Madrid')
ESTACIONES = {'castrocalbon': ('PL-9', 'Castrocalbón'), 'moralesdelrey': ('2082', 'Morales del Rey')}
AUDIT_CAMPOS = ['captura_utc', 'epoch', 'estacion', 'codigo_chd', 'variable', 'valor_anterior', 'valor_nuevo', 'unidad', 'motivo', 'fuente']
CAMPOS = ['epoch', 'fecha_hora_utc', 'fecha_hora_local', 'estacion', 'codigo_chd', 'variable', 'valor', 'unidad', 'calidad', 'fuente']
VARIABLES = {'temperatura_instantanea': ('t_actual_c', '°C'), 'precipitacion_hora_en_curso': ('p_hora_actual_lm2', 'mm'), 'precipitacion_ano_hidrologico': ('p_ahidrologico_actual_lm2', 'mm')}

def atomico(ruta, texto):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='', dir=ruta.parent, prefix='.tmp_', delete=False) as f:
        tmp = Path(f.name)
        f.write(texto)
        f.flush()
        os.fsync(f.fileno())
    try:
        os.replace(tmp, ruta)
    finally:
        tmp.unlink(missing_ok=True)

def descargar():
    error = None
    for n in range(3):
        try:
            req = urllib.request.Request(URL, headers={'User-Agent': 'MeteoValleEria-Observatorio/1.0', 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=35) as resp:
                if resp.status != 200:
                    raise ValueError(f'HTTP {resp.status}')
                cuerpo = resp.read(3_000_001)
                if len(cuerpo) > 3_000_000:
                    raise ValueError('JSON demasiado grande')
                return json.loads(cuerpo.decode('utf-8-sig'))
        except Exception as exc:
            error = exc
            if n < 2:
                time.sleep(2 * (n + 1))
    raise RuntimeError(f'No se pudo descargar JSON oficial: {error}')

def fecha_utc(texto):
    # Documentacion CHD: actualizacion expresada en UTC.
    return datetime.strptime(texto, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)

def numero(valor, nombre):
    if valor is None or str(valor).strip() == '':
        raise ValueError(f'Valor ausente: {nombre}')
    x = float(valor)
    if not math.isfinite(x):
        raise ValueError(f'Valor no finito: {nombre}')
    return x

def clasificar(variable, valor):
    if variable == 'temperatura_instantanea':
        return 'dudoso' if not -35 <= valor <= 55 else 'ok'
    return 'dudoso' if valor < 0 or (variable == 'precipitacion_hora_en_curso' and valor > 200) else 'ok'

def analizar(documento, ahora):
    if not isinstance(documento, list):
        raise ValueError('El JSON no contiene una lista de estaciones')
    codigos = {}
    for objeto in documento:
        if isinstance(objeto, dict):
            codigo = str(objeto.get('codigo', '')).strip()
            if codigo in [v[0] for v in ESTACIONES.values()]:
                if codigo in codigos:
                    raise ValueError(f'Codigo duplicado: {codigo}')
                codigos[codigo] = objeto
    filas = []
    estado = {}
    for nombre, (codigo, municipio) in ESTACIONES.items():
        if codigo not in codigos:
            raise ValueError(f'No aparece {nombre} ({codigo}) en JSON oficial')
        obj = codigos[codigo]
        if municipio.casefold() not in str(obj.get('punto_control', '')).casefold():
            raise ValueError(f'Identidad de estacion inesperada: {codigo}')
        fecha = fecha_utc(obj['actualizacion'])
        antiguedad = (ahora - fecha).total_seconds() / 3600
        if antiguedad > 36 or antiguedad < -1:
            raise ValueError(f'{nombre}: fecha fuera de rango ({antiguedad:.1f} h)')
        epoch = int(fecha.timestamp())
        for variable, (clave, unidad) in VARIABLES.items():
            valor = numero(obj.get(clave), f'{nombre}.{clave}')
            filas.append({'epoch': str(epoch), 'fecha_hora_utc': fecha.strftime('%Y-%m-%d %H:%M:%S'), 'fecha_hora_local': fecha.astimezone(TZ).isoformat(timespec='seconds'), 'estacion': nombre, 'codigo_chd': codigo, 'variable': variable, 'valor': format(valor, '.6g'), 'unidad': unidad, 'calidad': clasificar(variable, valor), 'fuente': 'CHD_estado_pluviometros'})
        estado[nombre] = {'codigo_chd': codigo, 'fecha_utc': fecha.isoformat(), 'antiguedad_horas': round(antiguedad, 2)}
    return filas, estado

def cargar(ruta):
    if not ruta.exists():
        return {}
    with ruta.open(encoding='utf-8-sig', newline='') as f:
        lector = csv.DictReader(f)
        if lector.fieldnames != CAMPOS:
            raise ValueError(f'Cabecera incompatible: {ruta}')
        salida = {}
        for fila in lector:
            if None in fila or any(fila.get(c) is None for c in CAMPOS):
                raise ValueError(f'CSV corrupto: {ruta}')
            clave = (fila['estacion'], fila['variable'], fila['epoch'])
            if clave in salida:
                raise ValueError(f'Duplicado en {ruta}: {clave}')
            numero(fila['valor'], 'CSV')
            salida[clave] = fila
        return salida

def serializar(filas, campos=CAMPOS):
    buffer = io.StringIO(newline='')
    w = csv.DictWriter(buffer, fieldnames=campos, lineterminator='\n')
    w.writeheader()
    w.writerows(filas)
    return buffer.getvalue()

def cargar_auditoria(ruta):
    if not ruta.exists():
        return []
    with ruta.open(encoding='utf-8-sig', newline='') as f:
        lector = csv.DictReader(f)
        if lector.fieldnames != AUDIT_CAMPOS:
            raise ValueError(f'Cabecera incompatible de auditoria: {ruta}')
        filas = list(lector)
        if any(None in fila or any(fila.get(c) is None for c in AUDIT_CAMPOS) for fila in filas):
            raise ValueError(f'Auditoria corrupta: {ruta}')
        return filas


def ejecutar():
    DATOS.mkdir(parents=True, exist_ok=True)
    ahora = datetime.now(timezone.utc)
    captura_utc = ahora.isoformat(timespec='seconds')
    estado = {'ejecucion_utc': captura_utc, 'estado': 'error', 'fuente': URL,
              'series': {}, 'problemas': []}
    try:
        nuevas, series = analizar(descargar(), ahora)
        ruta = DATOS / 'observaciones_chd.csv'
        ruta_audit = DATOS / 'revisiones_chd.csv'
        anteriores = cargar(ruta)
        auditoria = cargar_auditoria(ruta_audit)
        combinadas = dict(anteriores)
        altas, correcciones = 0, 0
        eventos = []
        for fila in nuevas:
            clave = (fila['estacion'], fila['variable'], fila['epoch'])
            vieja = combinadas.get(clave)
            if vieja is None:
                combinadas[clave] = fila
                altas += 1
            elif vieja != fila:
                # Guardar revision antes de actualizar el valor vigente.
                eventos.append({
                    'captura_utc': captura_utc, 'epoch': fila['epoch'],
                    'estacion': fila['estacion'], 'codigo_chd': fila['codigo_chd'],
                    'variable': fila['variable'], 'valor_anterior': vieja['valor'],
                    'valor_nuevo': fila['valor'], 'unidad': fila['unidad'],
                    'motivo': 'revision_fuente', 'fuente': fila['fuente'],
                })
                combinadas[clave] = fila
                correcciones += 1
        ordenadas = sorted(combinadas.values(), key=lambda x: (int(x['epoch']), x['estacion'], x['variable']))
        # Preparar ambos archivos antes de reemplazar ninguno.
        if altas or correcciones or not ruta.exists():
            texto_obs = serializar(ordenadas)
            texto_audit = serializar(auditoria + eventos, AUDIT_CAMPOS)
            if eventos or not ruta_audit.exists():
                atomico(ruta_audit, texto_audit)
            atomico(ruta, texto_obs)
        estado.update(estado='ok', series=series, nuevas=altas,
                      revisadas=correcciones, total=len(ordenadas),
                      revisiones_acumuladas=len(auditoria) + len(eventos))
    except Exception as exc:
        estado['problemas'].append(str(exc))
        print(f'ERROR: {exc}', file=sys.stderr)
    finally:
        atomico(DATOS / 'estado.json', json.dumps(estado, ensure_ascii=False, indent=2) + '\n')
    return 0 if estado['estado'] == 'ok' else 1


if __name__ == '__main__':
    sys.exit(ejecutar())
