
import root from '../root.svelte';
import { set_building, set_prerendering } from '__sveltekit/environment';
import { set_assets } from '__sveltekit/paths';
import { set_manifest, set_read_implementation } from '__sveltekit/server';
import { set_private_env, set_public_env, set_safe_public_env } from '../../../node_modules/@sveltejs/kit/src/runtime/shared-server.js';

export const options = {
	app_dir: "_app",
	app_template_contains_nonce: false,
	csp: {"mode":"auto","directives":{"upgrade-insecure-requests":false,"block-all-mixed-content":false},"reportOnly":{"upgrade-insecure-requests":false,"block-all-mixed-content":false}},
	csrf_check_origin: true,
	embedded: false,
	env_public_prefix: 'PUBLIC_',
	env_private_prefix: '',
	hooks: null, // added lazily, via `get_hooks`
	preload_strategy: "modulepreload",
	root,
	service_worker: false,
	templates: {
		app: ({ head, body, assets, nonce, env }) => "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n  <meta charset=\"utf-8\" />\n  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />\n  <meta name=\"description\" content=\"Pandora AI - Intelligent Research Assistant\" />\n  <meta name=\"theme-color\" content=\"#007bff\" />\n  <link rel=\"icon\" href=\"/icons/panda-hamster.svg\" />\n  <style>\n    /* Inline critical styles for instant rendering */\n    :root {\n      --panda-bg: #101014;\n      --panda-surface: #17171c;\n      --panda-text: #ececf1;\n    }\n    * { box-sizing: border-box; margin: 0; padding: 0; }\n    html, body {\n      background: var(--panda-bg);\n      color: var(--panda-text);\n      font-family: 'Segoe UI', sans-serif;\n      min-height: 100vh;\n    }\n    #app-loading {\n      position: fixed;\n      top: 0;\n      left: 0;\n      right: 0;\n      bottom: 0;\n      display: flex;\n      flex-direction: column;\n      align-items: center;\n      justify-content: center;\n      gap: 16px;\n      z-index: 9999;\n      background: var(--panda-bg);\n    }\n    #app-loading.hidden { display: none; }\n    #app-loading .spinner {\n      width: 40px;\n      height: 40px;\n      border: 3px solid #22222a;\n      border-top-color: #445fe6;\n      border-radius: 50%;\n      animation: spin 1s linear infinite;\n    }\n    @keyframes spin { to { transform: rotate(360deg); } }\n  </style>\n  " + head + "\n</head>\n<body data-sveltekit-preload-data=\"hover\">\n  <div id=\"app-loading\">\n    <div class=\"spinner\"></div>\n    <p>Loading Pandora AI...</p>\n    <p id=\"debug-status\" style=\"font-size:12px;color:#666;margin-top:20px;\"></p>\n  </div>\n  <div style=\"display: contents\">" + body + "</div>\n  <script>\n    var debugEl = document.getElementById('debug-status');\n    function debug(msg) {\n      if (debugEl) debugEl.textContent = msg;\n      console.log('[Debug]', msg);\n    }\n    debug('Script loaded');\n\n    // Catch and display any JavaScript errors\n    window.onerror = function(msg, url, line, col, error) {\n      var loader = document.getElementById('app-loading');\n      if (loader) {\n        loader.innerHTML = '<div style=\"color:#ff6b6b;padding:20px;text-align:left;max-width:600px;\">' +\n          '<h2 style=\"margin-bottom:12px;\">JavaScript Error</h2>' +\n          '<p style=\"font-family:monospace;background:#1a1a22;padding:12px;border-radius:6px;overflow:auto;\">' +\n          msg + '<br>at ' + url + ':' + line + ':' + col +\n          '</p></div>';\n      }\n      console.error('App Error:', msg, url, line, col, error);\n      return false;\n    };\n\n    // Also catch unhandled promise rejections\n    window.onunhandledrejection = function(event) {\n      debug('Promise rejected: ' + event.reason);\n      console.error('Unhandled rejection:', event.reason);\n    };\n  </script>\n</body>\n</html>\n",
		error: ({ status, message }) => "<!doctype html>\n<html lang=\"en\">\n\t<head>\n\t\t<meta charset=\"utf-8\" />\n\t\t<title>" + message + "</title>\n\n\t\t<style>\n\t\t\tbody {\n\t\t\t\t--bg: white;\n\t\t\t\t--fg: #222;\n\t\t\t\t--divider: #ccc;\n\t\t\t\tbackground: var(--bg);\n\t\t\t\tcolor: var(--fg);\n\t\t\t\tfont-family:\n\t\t\t\t\tsystem-ui,\n\t\t\t\t\t-apple-system,\n\t\t\t\t\tBlinkMacSystemFont,\n\t\t\t\t\t'Segoe UI',\n\t\t\t\t\tRoboto,\n\t\t\t\t\tOxygen,\n\t\t\t\t\tUbuntu,\n\t\t\t\t\tCantarell,\n\t\t\t\t\t'Open Sans',\n\t\t\t\t\t'Helvetica Neue',\n\t\t\t\t\tsans-serif;\n\t\t\t\tdisplay: flex;\n\t\t\t\talign-items: center;\n\t\t\t\tjustify-content: center;\n\t\t\t\theight: 100vh;\n\t\t\t\tmargin: 0;\n\t\t\t}\n\n\t\t\t.error {\n\t\t\t\tdisplay: flex;\n\t\t\t\talign-items: center;\n\t\t\t\tmax-width: 32rem;\n\t\t\t\tmargin: 0 1rem;\n\t\t\t}\n\n\t\t\t.status {\n\t\t\t\tfont-weight: 200;\n\t\t\t\tfont-size: 3rem;\n\t\t\t\tline-height: 1;\n\t\t\t\tposition: relative;\n\t\t\t\ttop: -0.05rem;\n\t\t\t}\n\n\t\t\t.message {\n\t\t\t\tborder-left: 1px solid var(--divider);\n\t\t\t\tpadding: 0 0 0 1rem;\n\t\t\t\tmargin: 0 0 0 1rem;\n\t\t\t\tmin-height: 2.5rem;\n\t\t\t\tdisplay: flex;\n\t\t\t\talign-items: center;\n\t\t\t}\n\n\t\t\t.message h1 {\n\t\t\t\tfont-weight: 400;\n\t\t\t\tfont-size: 1em;\n\t\t\t\tmargin: 0;\n\t\t\t}\n\n\t\t\t@media (prefers-color-scheme: dark) {\n\t\t\t\tbody {\n\t\t\t\t\t--bg: #222;\n\t\t\t\t\t--fg: #ddd;\n\t\t\t\t\t--divider: #666;\n\t\t\t\t}\n\t\t\t}\n\t\t</style>\n\t</head>\n\t<body>\n\t\t<div class=\"error\">\n\t\t\t<span class=\"status\">" + status + "</span>\n\t\t\t<div class=\"message\">\n\t\t\t\t<h1>" + message + "</h1>\n\t\t\t</div>\n\t\t</div>\n\t</body>\n</html>\n"
	},
	version_hash: "1ceham6"
};

export async function get_hooks() {
	return {
		
		
	};
}

export { set_assets, set_building, set_manifest, set_prerendering, set_private_env, set_public_env, set_read_implementation, set_safe_public_env };
