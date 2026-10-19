# Meteo Valle del Eria

Archivo historico de observaciones horarias publicadas por **SAIH Duero** para:

- **Castrocalbon (PL284)**: temperatura y precipitacion.
- **Morales del Rey (EA082)**: temperatura y precipitacion.

El proposito es conservar un historico que vaya mas alla del periodo disponible en el portal de origen. El analisis se realiza **en un Excel local con Power Query**. Este repositorio no genera libros Excel.

## Archivos fuente para Power Query

En `datos/` hay cuatro CSV historicos, uno por serie:

- `castrocalbon_temperatura.csv`
- `castrocalbon_lluvia.csv`
- `moralesdelrey_temperatura.csv`
- `moralesdelrey_lluvia.csv`

Todos tienen **exactamente** las mismas columnas:

| Columna | Contenido | Tipo sugerido PQ |
| --- | --- | --- |
| `epoch` | Segundos Unix UTC, clave unica por serie y hora | Numero entero (Int64) |
| `fecha_hora_local` | Texto `AAAA-MM-DD HH:MM`, hora oficial de Espana | Texto (evita ambiguedad DST) |
| `valor` | Temperatura en °C o lluvia horaria en l/m² | Numero decimal, configuracion regional `en-US` |
| `calidad` | `ok` o `dudoso` (reglas del proyecto) | Texto |

Convenciones fijas: UTF-8 sin BOM, coma como separador de columnas, punto decimal, valores con dos decimales, primera fila de cabeceras, orden cronologico creciente y una sola fila por `epoch`. Si falta una observacion, **no se crea un cero**; simplemente no existe esa fila. Para construir horas faltantes en Excel, generar un calendario de horas y combinarlo por `epoch`.

**Importante:** en la madrugada del cambio de horario de octubre existen dos horas locales iguales. Por eso la clave para combinar series es `epoch` y no `fecha_hora_local`.

Las mediciones son provisionales; las reglas de calidad locales no sustituyen una validacion meteorologica oficial. Temperaturas fuera de -30 a 50 °C y lluvia por encima de 50 l/m²/h o negativa se marcan `dudoso`, pero **no se borran**.

## Actualizacion automatica

El workflow `.github/workflows/captura.yml` se ejecuta cada dia a las 05:17 UTC y puede iniciarse manualmente desde **Actions > Captura diaria SAIH Duero > Run workflow**. Cada captura vuelve a descargar las series disponibles, agrega nuevas horas y acepta revisiones de las ultimas 49 jornadas. Nunca elimina horas historicas porque hayan desaparecido de la web.

Antes de modificar los CSV comprueba los cuatro canales, el formato del HTML, el numero minimo de observaciones, la frescura de los datos y la integridad de los CSV preexistentes. Si una serie falla, los cuatro historicos quedan como estaban. Se escribe el diagnostico en `datos/estado.json` y el workflow termina en rojo para permitir los avisos de GitHub.

`datos/huecos.csv` es un diagnostico auxiliar, no un quinto archivo de observaciones.

## Configurar avisos

En GitHub, ve a **Settings > Notifications > System > Actions** y activa las notificaciones por correo cuando fallen los workflows. Ademas, revisa que el repositorio permita escribir desde GitHub Actions en **Settings > Actions > General > Workflow permissions** cuando corresponda.

## Pruebas

Sin librerias externas:

```sh
python -m unittest discover -s tests -v
python captura_saih.py
```

La segunda orden requiere acceso a internet y consulta las paginas reales.

## Conectar desde Power Query

Usar **Datos > Obtener datos > Desde web**, con una URL como:

`https://raw.githubusercontent.com/ValledelEria/Meteo_Valle_del_Eria/main/datos/castrocalbon_temperatura.csv`

Importar como CSV separado por comas, con codificacion UTF-8, asignar `epoch` a Int64, `fecha_hora_local` a texto, `valor` a decimal **utilizando configuracion regional Ingles (Estados Unidos)** y `calidad` a texto. La consulta se actualiza al pulsar **Actualizar todo** en Excel.

### Aviso legal

SAIH Duero / Confederacion Hidrografica del Duero es la fuente. Proyecto independiente. Revisar las condiciones de reutilizacion de la fuente. La informacion es provisional.
