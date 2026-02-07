

export const index = 3;
let component_cache;
export const component = async () => component_cache ??= (await import('../entries/pages/transcripts/_page.svelte.js')).default;
export const imports = ["_app/immutable/nodes/3.C8OLggUJ.js","_app/immutable/chunks/scheduler.DzwVX6aR.js","_app/immutable/chunks/each.DT1-dA3s.js","_app/immutable/chunks/index.F3VcX34h.js"];
export const stylesheets = ["_app/immutable/assets/3.DWtJAhIy.css"];
export const fonts = [];
