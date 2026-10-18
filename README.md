# meteo-ValledelEria

Datos horarios de temperatura y lluvia de dos estaciones del SAIH Duero en el Valle del Eria, acumulados automáticamente cada día.

## Estaciones

| Estación | Tipo | Variables |
|---|---|---|
| Castrocalbón (PL284) | Pluviómetro | Temperatura ambiente y lluvia |
| Morales del Rey (EA082) | Estación de aforo del río Eria | Temperatura ambiente y lluvia |

## Contenido

- `datos/<estacion>_<variable>.csv`: una serie por archivo, con una fila por hora (`epoch`, `fecha_hora_local`, `valor`, `calidad`).
- `datos/diario.csv`: resumen por día de las dos estaciones (temperatura mínima, máxima y media; lluvia del día; lluvia acumulada de 7 y 30 días; horas con dato y marcas de día completo). Se actualiza cada día.
- `datos/huecos.csv`: periodos sin dato.
- `datos/estado.json`: resultado de la última captura.
- `Meteo_ValledelEria_datos.xlsx`: libro con las hojas Leeme, Diario y Horario. Se rehace los lunes.

## Cómo funciona

Una tarea programada de GitHub Actions (`.github/workflows/captura.yml`) ejecuta cada día `captura_saih.py`, que lee las páginas de histórico del SAIH y añade las horas nuevas a los CSV sin duplicar. Después, `construir_excel.py` genera el resumen diario y el libro de Excel.

## Avisos

- Los datos son de tiempo real y **provisionales**: la propia fuente avisa de que pueden revisarse o corregirse. Para estudios técnicos, la fuente indica que los datos meteorológicos válidos son los de AEMET.
- Las horas sin dato quedan **vacías**. Nunca se rellenan ni se interpolan.
- Se marcan como `dudoso` la lluvia superior a 50 l/m² en una hora y las temperaturas fuera de -30 a 50 ºC. Son criterios del proyecto, no de la fuente, y se pueden cambiar en `captura_saih.py`.
- Fuente de los datos: SAIH Duero, Confederación Hidrográfica del Duero (https://www.saihduero.es). Este proyecto es independiente y no tiene vinculación con la Confederación. Consulta las condiciones de uso de la fuente antes de reutilizar los datos.
