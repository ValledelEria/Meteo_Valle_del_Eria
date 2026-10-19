# Meteo Valle del Eria

**Archivo histórico automatizado de datos meteorológicos del Valle del Eria (León y Zamora, España).**

Este proyecto recopila y conserva observaciones horarias de temperatura ambiente y precipitación procedentes del Sistema Automático de Información Hidrológica (SAIH) de la Confederación Hidrográfica del Duero.

Su finalidad es mantener un registro histórico continuo, estructurado y accesible de las mediciones disponibles para dos estaciones situadas en el entorno del Valle del Eria.

## Estaciones meteorológicas

| Estación | Código | Variables |
|---|---|---|
| Castrocalbón | PL284 | Temperatura y precipitación |
| Morales del Rey | EA082 | Temperatura y precipitación |

## Datos disponibles

El repositorio conserva cuatro series temporales independientes:

- Temperatura horaria de Castrocalbón.
- Precipitación horaria de Castrocalbón.
- Temperatura horaria de Morales del Rey.
- Precipitación horaria de Morales del Rey.

Los datos se almacenan en archivos CSV que se actualizan automáticamente y permiten su consulta, descarga y reutilización.

### Estructura de los archivos

Cada registro contiene los siguientes campos:

| Campo | Descripción |
|---|---|
| `epoch` | Marca temporal Unix, en segundos UTC |
| `fecha_hora_local` | Fecha y hora local de la observación |
| `valor` | Valor de la variable meteorológica |
| `calidad` | Indicador de calidad del registro |

Los valores de temperatura se expresan en grados Celsius (°C) y los de precipitación en litros por metro cuadrado (l/m²), equivalentes a milímetros de lluvia.

## Recopilación y actualización

La recopilación se realiza mediante un proceso automatizado desarrollado en Python y ejecutado periódicamente a través de GitHub Actions.

El sistema está diseñado para:

- Consultar los datos disponibles en SAIH Duero.
- Incorporar nuevas observaciones al histórico.
- Evitar registros duplicados.
- Conservar las mediciones de periodos anteriores.
- Incorporar correcciones de observaciones recientes cuando estén disponibles.
- Detectar errores de captura o formatos inesperados.
- Mantener una estructura homogénea en los archivos publicados.

Dado que la fuente ofrece una ventana temporal limitada de consulta, la recopilación periódica permite conservar observaciones que posteriormente dejan de estar disponibles en el histórico reciente del portal.

## Integridad y calidad de los datos

Las observaciones se conservan con su correspondiente referencia temporal y sin aplicar interpolaciones para completar periodos sin información.

La ausencia de una medición no debe interpretarse como un valor cero.

Los registros que superan determinados umbrales de comprobación pueden identificarse mediante el indicador `dudoso`. Estos criterios constituyen controles internos del proyecto y no equivalen a una validación oficial por parte del organismo de origen.

La disponibilidad de los registros depende de la información facilitada por la fuente y del funcionamiento de las capturas automatizadas.

## Fuente y atribución

**Fuente de los datos:** Sistema Automático de Información Hidrológica (SAIH Duero), Confederación Hidrográfica del Duero.

Web oficial: https://www.saihduero.es/

Los datos publicados por SAIH Duero tienen carácter provisional y pueden estar sujetos a revisiones, correcciones o interrupciones del servicio.

Este repositorio es un proyecto independiente y no está afiliado ni representa oficialmente a la Confederación Hidrográfica del Duero.

La disponibilidad pública de los archivos no sustituye las condiciones de acceso, uso y reutilización establecidas por el organismo de origen.

## Alcance y limitaciones

Este proyecto tiene carácter documental y de conservación histórica.

Los datos publicados no constituyen observaciones meteorológicas oficialmente certificadas ni deben utilizarse como única referencia en actividades que requieran información meteorológica validada.

El mantenimiento del repositorio, la periodicidad de actualización y la continuidad de la recopilación están sujetos a la disponibilidad de la fuente y a las condiciones técnicas del servicio.

---

**Meteo Valle del Eria**  
Repositorio público de observaciones meteorológicas históricas del Valle del Eria.
