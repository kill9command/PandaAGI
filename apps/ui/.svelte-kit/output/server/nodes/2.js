

export const index = 2;
let component_cache;
export const component = async () => component_cache ??= (await import('../entries/pages/_page.svelte.js')).default;
export const imports = ["_app/immutable/nodes/2.DdZ9ontw.js","_app/immutable/chunks/scheduler.DzwVX6aR.js","_app/immutable/chunks/index.F3VcX34h.js","_app/immutable/chunks/each.DT1-dA3s.js","_app/immutable/chunks/index.BznWJi_9.js","_app/immutable/chunks/preload-helper.C1FmrZbK.js"];
export const stylesheets = ["_app/immutable/assets/2.BrDdnYWR.css"];
export const fonts = [];
