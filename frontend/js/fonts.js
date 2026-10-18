// Caras de fuente y métricas de /api/fonts. Son los mismos archivos que usa libass (assets/fonts),
// así que el navegador y el quemado miden igual. El frontend no tiene tablas propias.
import { API_BASE } from "./api.js";

const state = { faces: [], canvas: null };

// Registra cada cara con su familia, negrita e itálica, y espera a que carguen. Las caras van a /fonts/ del backend (la
// base de config.js): son los mismos archivos que usa libass, así que no hace falta copiarlos al frontend. Con otro
// origen, el backend tiene que responder CORS también para /fonts/.
export function loadFonts(faces) {
  state.faces = faces;
  return Promise.all(
    faces.map((face) => {
      const font = new FontFace(face.family, `url(${API_BASE}/fonts/${encodeURIComponent(face.file)})`, {
        weight: face.bold ? "700" : "400",
        style: face.italic ? "italic" : "normal",
      });
      document.fonts.add(font);
      return font.load().catch(() => null);
    }),
  );
}

export function families() {
  return [...new Set(state.faces.map((face) => face.family))];
}

// Cara del catálogo para familia, negrita e itálica. Si no hay una exacta, la de la misma itálica o la primera.
export function faceOf(family, bold, italic) {
  const same = state.faces.filter((face) => face.family === family);
  return (
    same.find((face) => !!face.bold === !!bold && !!face.italic === !!italic) ||
    same.find((face) => !!face.italic === !!italic) ||
    same[0] ||
    null
  );
}

export function cssScale(family, bold, italic) {
  return faceOf(family, bold, italic)?.css_scale ?? 1;
}

export function hasBoldFace(family) {
  return state.faces.some((face) => face.family === family && face.bold);
}

// Ancho en píxeles de un texto con la cara dada a px de tamaño, sin letter-spacing.
export function advance(text, family, bold, italic, px) {
  state.canvas ??= document.createElement("canvas").getContext("2d");
  state.canvas.font = `${italic ? "italic " : ""}${bold ? 700 : 400} ${px}px "${family}"`;
  return state.canvas.measureText(text).width;
}

// Ascendente y descendente de la cara a px de tamaño, como los mide el navegador (líneas del gancho).
export function metricsOf(family, bold, italic, px) {
  state.canvas ??= document.createElement("canvas").getContext("2d");
  state.canvas.font = `${italic ? "italic " : ""}${bold ? 700 : 400} ${px}px "${family}"`;
  const { fontBoundingBoxAscent, fontBoundingBoxDescent } = state.canvas.measureText("Hg");
  return { ascent: fontBoundingBoxAscent, descent: fontBoundingBoxDescent };
}
