# GOLD_FIXES.md

Correcciones al timeline gold de `DekXWuPh2T-` que usan los tests de esta copia. El original del propietario, en `ken-remedie-subtitulos/timelines/gold/`, no se ha tocado; estos cambios viven solo aquí.

Archivos cambiados: `timelines/gold/DekXWuPh2T-_gold.json` y `timelines/gold/DekXWuPh2T-_gold.srt`, con el mismo cambio en los dos.

## Corrección 1: falta «straight to your» en el clip CTA (84–93 s del reel)

**Qué cambia.** El segmento «health protocols» (86,567–88,100 s del reel) se parte en dos:

| Frase | Antes (reel, s) | Después (reel, s) | En el clip CTA (s) |
|---|---|---|---|
| health protocols | 86,567 → 88,100 | 86,567 → 87,533 | 2,567 → 3,533 |
| straight to your (nueva) | — | 87,600 → 88,100 | 3,600 → 4,100 |
| DMs. | 88,100 → 88,733 | sin cambios | 4,100 → 4,733 |

El SRT recibe el mismo cambio y su numeración pasa de 104 a 105 bloques.

**Por qué.** El gold no tiene «straight to your», así que deja «health protocols» en pantalla 1,5 s. El subtítulo original del clip sí muestra esa frase, y Whisper también la transcribe: `straight` en 3,20–3,66 s del clip, `to` en 3,66–3,88 y `your` en 3,88–3,96.

**Cómo se comprobó.**
1. Fotogramas a 30 fps del clip original entre 3,27 y 4,27 s, en la banda del subtítulo. «health protocols» se ve hasta el fotograma 105 (3,500 s); los fotogramas 106 y 107 quedan vacíos; «straight to your» va del 108 (3,600 s) al 122; «DMs.» empieza en el 123 (4,100 s). Se comprobó leyendo la tira de fotogramas.
2. La máscara de blanco puro de la misma banda da los mismos cambios: 3,09 % hasta el 105, 0 % en el 106 y el 107, 2,32 % del 108 al 122 y 0,81 % desde el 123.
3. El desplazamiento del clip, 84,00 s, se midió antes con los cortes del original (error medio 0,000 s sobre 11 inicios).

**Efecto en las medidas.** F1(b) pasa de 61,5 % a 60,0 %, y F1(a) de 51,2 % a 51,6 %. (b) baja porque el gold tiene ahora una frontera más, tras «your», que la segmentación actual no produce. El cambio viene de corregir el gold, no del código.

**Umbrales.** El umbral de F1(b) pasa de 0,56 a 0,55 (60,0 % − 5). El de F1(a) se queda en 0,46: el valor medido sube 0,4 puntos y el umbral redondeado no cambia.

## Lo que no se ha corregido

- Los tiempos de palabra dentro de cada frase siguen repartidos por caracteres, como en el original del propietario.
- Los segmentos de pausa y el resto de frases no se han tocado.
