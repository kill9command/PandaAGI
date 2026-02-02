import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [sveltekit()],
  server: {
    proxy: {
      '/v1': 'http://localhost:9000',
      '/ws': {
        target: 'ws://localhost:9000',
        ws: true
      },
      '/interventions': 'http://localhost:9000',
      '/transcripts': 'http://localhost:9000',
      '/health': 'http://localhost:9000',
      '/screenshots': 'http://localhost:9000'
    }
  }
});
