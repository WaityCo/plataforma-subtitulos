// Navegación por hash: #/nuevo, #/presets y #/editor/<job>. Cualquier otro hash cae en #/nuevo.
const JOB_ID = /^\/editor\/([0-9a-f]{32})$/;

export function parseRoute(hash = location.hash) {
  const path = hash.replace(/^#/, "");
  const editor = JOB_ID.exec(path);
  if (editor) return { name: "editor", id: editor[1] };
  if (path === "/presets") return { name: "presets" };
  return { name: "nuevo" };
}
