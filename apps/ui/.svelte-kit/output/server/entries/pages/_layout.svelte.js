import { c as create_ssr_component } from "../../chunks/ssr.js";
const css = {
  code: ".app.svelte-1vxg5qg{min-height:100vh;display:flex;flex-direction:column}",
  map: `{"version":3,"file":"+layout.svelte","sources":["+layout.svelte"],"sourcesContent":["<script>\\n  import '../app.css';\\n  import { onMount } from 'svelte';\\n\\n  onMount(() => {\\n    // Hide the loading screen once the app is mounted\\n    const loader = document.getElementById('app-loading');\\n    if (loader) {\\n      loader.classList.add('hidden');\\n    }\\n  });\\n<\/script>\\n\\n<div class=\\"app\\">\\n  <slot />\\n</div>\\n\\n<style>\\n  .app {\\n    min-height: 100vh;\\n    display: flex;\\n    flex-direction: column;\\n  }\\n</style>\\n"],"names":[],"mappings":"AAkBE,mBAAK,CACH,UAAU,CAAE,KAAK,CACjB,OAAO,CAAE,IAAI,CACb,cAAc,CAAE,MAClB"}`
};
const Layout = create_ssr_component(($$result, $$props, $$bindings, slots) => {
  $$result.css.add(css);
  return `<div class="app svelte-1vxg5qg">${slots.default ? slots.default({}) : ``} </div>`;
});
export {
  Layout as default
};
