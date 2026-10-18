# Cómo agregar un estilo

Un estilo es una entrada en `presets/presets.json`. Los campos que no escribas toman el valor de `DEFAULT_STYLE` en `engine/styles.py` (tabla abajo). La UI pinta una tarjeta por cada preset que devuelve `GET /api/presets`, así que no hay que tocar el frontend.

## Pasos

1. Añade el bloque en `presets/presets.json`. `label` y `description` son obligatorios y no pueden estar vacíos. Pon solo los campos que cambien.
2. Reinicia el servidor. `engine/styles.py` lee el JSON una vez por proceso.
3. Verifica con la CLI (sección "Verificar con la CLI").
4. Abre la UI. El preset aparece en la sección "Presets".

Un campo mal escrito no detiene la carga: se ignora con el warning `Campo de estilo desconocido ignorado en preset ...`. Un valor fuera de rango o de tipo sí la detiene, y la CLI lo muestra como `error:`.

## Referencia de campos

Los valores están en unidades de referencia de un video de 1080x1920. Antes de dibujar, el motor multiplica `font_size`, `margin_v`, `margin_h`, `outline_width`, `shadow_depth`, `shadow_blur`, `letter_spacing`, `emphasis_letter_spacing` y `highlight_box_radius` por `alto del video / 1920`. Un video de 720x1280 queda con las mismas proporciones.

| Campo | Tipo | Rango o valores | Default | Efecto |
|---|---|---|---|---|
| `font_family` | texto | no vacío; sin comas, llaves, `\` ni saltos de línea | `Montserrat` | Familia de la fuente. Debe coincidir con el nombre interno del TTF (ver "Fuentes"). |
| `font_bold` | bool | `true`, `false` | `true` | Negrita. Elige la variante Bold de la familia. |
| `font_size` | número | 10 a 300 | `86` | Tamaño de la fuente en Fontsize de libass. Admite decimales: px CSS = `font_size` × `css_scale` de la fuente (`GET /api/fonts`). |
| `uppercase` | bool | `true`, `false` | `false` | Dibuja el texto en mayúsculas. No cambia `words.json`. |
| `strip_punctuation` | bool | `true`, `false` | `false` | Quita de cada palabra los signos: todo lo que no sea letra, dígito ni `_`, salvo los apóstrofos que quedan dentro de la palabra (`don't`, `I'm`). Una palabra que queda vacía no se dibuja. |
| `text_color` | color | `#RRGGBB` | `#FFFFFF` | Color del texto. En `karaoke_sweep` es el color final del barrido. |
| `highlight_color` | color | `#RRGGBB` | `#FFD400` | Color de la palabra activa en `karaoke`, del barrido en `karaoke_sweep` y del énfasis `color`. |
| `outline_color` | color | `#RRGGBB` | `#000000` | Color del contorno. No se usa si hay `box_color`. |
| `outline_width` | número | 0 a 30 | `8` | Grosor del contorno. Con caja, controla el relleno de la caja. Resta ancho útil a cada línea. |
| `shadow_depth` | número | 0 a 20 | `2` | Distancia de la sombra de ASS. Solo se usa con `shadow_style: hard`. |
| `box_color` | color o `null` | `#RRGGBB` o `null` | `null` | Si no es `null`, dibuja una caja detrás del texto con ese color. |
| `box_opacity` | número | 0 a 1 | `0.6` | Opacidad de la caja. Solo se usa con `box_color`. |
| `alignment` | entero | 1 a 9 | `2` | Posición tipo teclado numérico: 2 abajo al centro, 5 al centro, 8 arriba al centro. |
| `margin_v` | entero | 0 a 1920 | `420` | Distancia vertical desde el borde que indique `alignment`. Con alineación central (4 a 6) no lo uses. |
| `margin_h` | entero | 0 a 1080 | `80` | Margen izquierdo y derecho. Reduce el ancho útil de cada línea. |
| `mode` | enum | `phrase`, `karaoke`, `karaoke_sweep`, `karaoke_box`, `reveal` | `karaoke` | `phrase`: el grupo completo visible. `karaoke`: un evento por palabra, con la activa en `highlight_color`. `karaoke_sweep`: barrido `\kf` de `text_color` a `highlight_color`. `karaoke_box`: caja de `highlight_box_color` detrás de la palabra activa, que salta de palabra en palabra. `reveal`: cada palabra aparece al empezar su audio, con el bloque entero ya colocado. |
| `max_words_per_line` | entero | 1 a 20 | `3` | Corta el grupo al llegar a ese número de palabras. |
| `max_lines` | entero | 1 a 3 | `2` | Líneas máximas por grupo. Si no caben, el grupo se corta antes. |
| `animation` | enum | `none`, `pop`, `fade` | `pop` | `pop`: escala de 112 % a 100 % (220 ms en frase, 180 ms en la palabra activa). `fade`: fundido de 80 ms al entrar. |
| `emphasis` | enum | `none`, `italic`, `color`, `italic_color` | `none` | Énfasis de la palabra marcada: itálica, color `highlight_color`, o ambos. |
| `emphasis_auto` | bool | `true`, `false` | `true` | Con `emphasis` distinto de `none`, elige el énfasis automático. Con `emphasis_engine: length`, marca una palabra por grupo de 2 o más: la más larga que no sea stopword (en empate, la primera). Con `lexicon`, lo decide el léxico (ver abajo). Con `false`, no hay énfasis automático. Un `"emph": true/false` en `words.json` tiene prioridad. |
| `shadow_style` | enum | `hard`, `soft`, `halo` | `hard` | `hard`: sombra de ASS. `soft`: capa aparte desenfocada con `shadow_blur`. `halo`: contorno de `outline_width` en `shadow_color` con alfa `shadow_opacity`, sin sombra de ASS, con `\blur` de `shadow_blur` en cada evento. |
| `shadow_color` | color | `#RRGGBB` | `#000000` | Color de la sombra. |
| `shadow_opacity` | número | 0 a 1 | `0.55` | Opacidad de la sombra. |
| `shadow_blur` | número | 0 a 50 | `8` | Desenfoque de la sombra `soft` y del `halo`. Se escala como el resto de valores de referencia. |
| `scale_x` | número | 10 a 300 | `100` | Compresión horizontal del texto en %. Va en `ScaleX` del estilo. |
| `scale_x_italic` | número o `null` | 10 a 300 | `null` | Compresión de la cursiva en %, como `\fscx` en cada tramo itálico. `null` usa `scale_x`. |
| `letter_spacing` | número | -50 a 50 | `0` | Espaciado entre letras en píxeles de referencia, como `\fsp`. Con 0 no añade etiqueta. |
| `word_space_scale` | número | 1 a 300 | `100` | Ancho de cada espacio entre palabras en %. Con 100 no añade etiqueta. |
| `y_pct` | número o `null` | 0 a 1 | `null` | Centro vertical del texto como fracción de la altura. Con valor, cada evento usa `\pos` y se ignoran `alignment` y `margin_v`. |
| `max_chars` | entero o `null` | 1 a 200 | `null` | Mide las líneas en caracteres en vez de píxeles. |
| `target_words` | entero o `null` | 1 a 20 | `null` | Objetivo blando de palabras por frase: al alcanzarlo se corta antes de la siguiente palabra, salvo que sea corta (`hang_max_chars`) y quepa. `max_words_per_line` sigue siendo el tope duro. `null` no aplica objetivo. |
| `hang_max_chars` | entero | 0 a 10 | `0` | Palabra corta de hasta esas letras que se queda al final de una frase que llega a su objetivo, en vez de abrir la siguiente. Con `target_words` solo se queda cuando la frase está justo en el objetivo; con `soft_max_chars`, cuando pasa el objetivo de caracteres. `0` lo desactiva. |
| `soft_max_chars` | entero o `null` | 1 a 200 | `null` | Objetivo blando de caracteres por frase: al pasarlo se corta, con la misma excepción de `hang_max_chars`. `max_chars` sigue siendo el tope duro. |
| `punctuation_closes` | texto | hasta 20 signos sin letras ni espacios | `.?!` | Signos que siempre cierran una frase. |
| `pause_split_s` | número | 0 a 10 | `0.6` | Silencio en segundos que corta una frase, cuando ya tiene `pause_split_min_words` palabras. |
| `pause_split_min_words` | entero | 1 a 20 | `1` | Palabras mínimas en la frase antes de que un silencio pueda cortarla. |
| `merge_orphans` | bool | `true`, `false` | `false` | Une una palabra sola sin puntuación a la frase anterior si el hueco es menor que `blank_gap_s` (o `pause_split_s`) y la unión cabe. |
| `blank_gap_s` | número o `null` | 0 a 10 | `null` | Con valor, un hueco menor que él se cubre hasta la frase siguiente; uno mayor deja la pantalla vacía tras `tail_s`. `null` mantiene la cola de 0,3 s. |
| `tail_s` | número | 0 a 5 | `0.05` | Cola tras la última palabra cuando hay pausa. Solo actúa con `blank_gap_s`. |
| `min_duration_s` | número | 0 a 5 | `0.3` | Duración mínima de una frase sin pisar la siguiente. Solo actúa con `blank_gap_s`. |
| `emphasis_engine` | enum | `length`, `lexicon` | `length` | `length`: la palabra más larga de cada grupo de 2 o más palabras. `lexicon`: puntaje de `presets/emphasis_lexicon.json` entre todas las frases. Requiere `emphasis_auto: true` (ver abajo). |
| `emphasis_ratio` | número o `null` | 0 a 1 | `null` | Con `lexicon`, fracción de frases con énfasis: se marcan las de mayor puntaje hasta esa fracción. `null` marca todas las que puntúan. |
| `emphasis_font_family` | texto o `null` | no vacío; sin comas, llaves, `\` ni saltos | `null` | Familia del tramo enfatizado (ej. `Instrument Serif`, que va con `emphasis_italic`). `null` usa la del texto normal. |
| `emphasis_italic` | bool | `true`, `false` | `true` | Cursiva en el tramo enfatizado. Solo actúa con `emphasis` `italic` o `italic_color`. |
| `emphasis_size_scale` | número | 0,1 a 5 | `1.0` | Tamaño del tramo enfatizado relativo al normal. Con 1 no añade etiqueta. |
| `emphasis_letter_spacing` | número o `null` | -50 a 50 | `null` | Espaciado del tramo enfatizado en px de referencia. `null` usa el de `letter_spacing`. |
| `emphasis_max_per_segment` | entero o `null` | 1 a 20 | `null` | Con `lexicon`, palabras enfatizadas máximas por bloque. Con 2 o más, un bloque puede llevar varias unidades. `null` lleva una por frase, como antes. |
| `text_case` | enum | `as_is`, `upper`, `lower_smart` | `as_is` | `upper`: mayúsculas. `lower_smart`: minúsculas salvo «I», siglas de 2 letras o más y nombres propios (capitalizados fuera de inicio de frase). `uppercase: true` equivale a `upper`. |
| `exact_metrics` | bool | `true`, `false` | `false` | Mide como libass: em = `font_size` × `css_scale` y kerning de HarfBuzz. Sin él, la medida es la heredada. |
| `x_pct` | número o `null` | 0 a 1 | `null` | Anclaje horizontal: borde izquierdo con `text_align` `left`, centro con `center`. `null` es el centro. |
| `text_align` | enum | `left`, `center` | `center` | Alineación de las líneas del bloque alrededor de `x_pct`. |
| `line_height` | número o `null` | 0,5 a 3 | `null` | Paso entre líneas como múltiplo del em mayor. Con valor, cada línea va en su evento con posición. |
| `reveal_fade_ms` | número | 0 a 1000 | `100` | Fundido de la palabra nueva en `mode` `reveal`. |
| `highlight_box_color` | color o `null` | `#RRGGBB` o `null` | `null` | Color de la caja de `karaoke_box`. `null` usa `highlight_color`. |
| `highlight_box_radius` | número | 0 a 100 | `0` | Radio de esquina de la caja, en px de referencia. |
| `highlight_box_padding_x` | número | 0 a 100 | `0` | Relleno horizontal de la caja. |
| `highlight_box_padding_y` | número | 0 a 100 | `0` | Relleno vertical de la caja. |
| `split_before_words` | lista de palabras | hasta 50, sin espacios | `[]` | Conectores: el corte va antes de ellos si la frase ya tiene `pause_split_min_words`. |
| `balance_lines` | bool | `true`, `false` | `false` | Si la frase va en dos líneas, el corte es el de anchos más parecidos. |

Las palabras de cada grupo se parten en líneas con el ancho útil del video: ancho menos `margin_h` y `outline_width` a cada lado. Un grupo se corta tras un silencio mayor que `pause_split_s` (si ya tiene `pause_split_min_words` palabras) y después de un signo de `punctuation_closes`. Con los valores por defecto son 0,6 s y `.`, `?` o `!`.

## Fuentes

- Usa TTF estáticos en `assets/fonts/`. Lo que cuenta son los nombres internos del archivo, no el nombre del archivo.
- `font_family` es el nombre de familia interno (name ID 1). La subfamilia (name ID 2) tiene que ser `Regular`, `Bold`, `Italic` o `Bold Italic`. El motor busca esos nombres exactos para medir el texto.
- Si falta una variante, la medida prueba otra de la misma familia. Si no hay ninguna, cada carácter mide 0,6 em. El resultado se ve bien, pero el ajuste de líneas queda aproximado.

Para comprobar los nombres de un TTF:

```bash
.venv/bin/python -c "from fontTools.ttLib import TTFont; n = TTFont('assets/fonts/MiFuente-Regular.ttf')['name']; print(n.getDebugName(1), '|', n.getDebugName(2))"
```

**Por qué no sirven las fuentes variables.** `Montserrat[wght].ttf` contiene todos los pesos en un solo archivo, y libass usa su instancia por defecto, que en Montserrat es Thin. Además, su nombre interno es `Montserrat Thin`, así que `font_family: Montserrat` no lo encuentra. Por eso el motor deja fuera de la medida y del quemado cualquier archivo con `[` en el nombre. Para tener los pesos, `python -m engine.static_fonts` genera instancias estáticas: Bold (familia `Montserrat`), ExtraBold (familia `Montserrat ExtraBold`), Medium (familia `Montserrat Medium`) e Inter SemiBold (familia `Inter SemiBold`, de `Inter[opsz,wght].ttf` en opsz 14).

Se aceptan `.ttf` y `.otf`: la medida (`engine/textmetrics.py`) y el quemado (`engine/burn.py`) usan la misma lista de extensiones.

## Énfasis por léxico

Con `emphasis_engine: lexicon`, cada palabra puntúa según `presets/emphasis_lexicon.json`. Cada categoría tiene un `peso` de 1 a 10 y listas `palabras` y `compuestos` en `es` y `en`. Un compuesto son dos palabras contiguas y puntúa con el peso de su categoría; en empate gana la palabra suelta. Una palabra entre comillas puntúa al menos con `peso_comillas`.

Nunca se enfatizan las stopwords de `presets/stopwords.json`, las contracciones con apóstrofe ni las palabras vacías. Cada frase lleva como mucho una unidad, o varias con `emphasis_max_per_segment`. Con `emphasis_ratio`, se marcan las frases de mayor puntaje hasta esa fracción. Un `"emph"` en `words.json` gana sobre el léxico.

Para ampliar el léxico, añade la palabra en minúsculas a su categoría. Las entradas de `compuestos` deben tener dos palabras y ninguna stopword; el motor lo valida al cargar.

## Timeline gold

`engine/timeline.py` importa un timeline con `*palabra*` como itálica (`segments_from_markup`) y exporta de vuelta (`markup_from_segments`). Sirve para tests y para importar timelines revisados a mano.

## Verificar con la CLI

```bash
.venv/bin/python -m engine.cli tests/fixtures/sample_1080x1920.mp4 --preset mi_estilo --out-dir tests/out/mi_estilo --no-burn
```

- Revisa `tests/out/mi_estilo/subtitles.ass`. La línea `Style:` trae tamaño, colores y márgenes ya escalados a la altura del video. Las líneas `Dialogue:` muestran los cortes y las etiquetas de cada evento.
- Para probar un cambio sin editar el JSON: `--set font_size=80 --set mode=phrase`. Los valores se leen como JSON, así que escribe `true`, `false`, `null` y números sin comillas.
- Quita `--no-burn` para obtener `output.mp4`. Requiere un FFmpeg con libass.

## Ejemplo completo

Este bloque no está en `presets.json`. Para usarlo, añádelo como una clave más del objeto raíz de ese archivo:

```json
"nota_suave": {
  "label": "Nota suave",
  "description": "Instrument Serif en frase, con la palabra enfatizada en color y sombra suave.",
  "font_family": "Instrument Serif",
  "font_bold": false,
  "font_size": 88,
  "text_color": "#FFFFFF",
  "highlight_color": "#F6D58E",
  "outline_width": 0,
  "shadow_style": "soft",
  "shadow_color": "#000000",
  "shadow_opacity": 0.7,
  "shadow_blur": 10,
  "alignment": 2,
  "margin_v": 740,
  "mode": "phrase",
  "max_words_per_line": 4,
  "max_lines": 1,
  "emphasis": "color",
  "emphasis_auto": true,
  "animation": "fade"
}
```

Qué hace cada decisión: la fuente es estática y viene en `assets/fonts/`. El contorno está en 0 porque la sombra suave hace el trabajo de legibilidad. `margin_v` 740 deja la base del texto a 740 px del borde inferior, a un 61 % de la altura. `emphasis_auto` elige una palabra por frase, y `emphasis: color` la pinta con `highlight_color` sin cambiar de fuente.
