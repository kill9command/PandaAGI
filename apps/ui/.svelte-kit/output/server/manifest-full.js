export const manifest = (() => {
function __memo(fn) {
	let value;
	return () => value ??= (value = fn());
}

return {
	appDir: "_app",
	appPath: "_app",
	assets: new Set(["icons/panda-hamster.svg"]),
	mimeTypes: {".svg":"image/svg+xml"},
	_: {
		client: {"start":"_app/immutable/entry/start.A1nfCgtp.js","app":"_app/immutable/entry/app.CinhUyCj.js","imports":["_app/immutable/entry/start.A1nfCgtp.js","_app/immutable/chunks/entry.CJudwUD1.js","_app/immutable/chunks/scheduler.DzwVX6aR.js","_app/immutable/chunks/index.BznWJi_9.js","_app/immutable/entry/app.CinhUyCj.js","_app/immutable/chunks/preload-helper.C1FmrZbK.js","_app/immutable/chunks/scheduler.DzwVX6aR.js","_app/immutable/chunks/index.F3VcX34h.js"],"stylesheets":[],"fonts":[],"uses_env_dynamic_public":false},
		nodes: [
			__memo(() => import('./nodes/0.js')),
			__memo(() => import('./nodes/1.js')),
			__memo(() => import('./nodes/2.js')),
			__memo(() => import('./nodes/3.js'))
		],
		routes: [
			{
				id: "/",
				pattern: /^\/$/,
				params: [],
				page: { layouts: [0,], errors: [1,], leaf: 2 },
				endpoint: null
			},
			{
				id: "/transcripts",
				pattern: /^\/transcripts\/?$/,
				params: [],
				page: { layouts: [0,], errors: [1,], leaf: 3 },
				endpoint: null
			}
		],
		matchers: async () => {
			
			return {  };
		},
		server_assets: {}
	}
}
})();
