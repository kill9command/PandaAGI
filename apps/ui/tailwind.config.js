/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{html,js,svelte,ts}'],
  theme: {
    extend: {
      colors: {
        'panda-bg': '#101014',
        'panda-surface': '#17171c',
        'panda-border': '#22222a',
        'panda-text': '#ececf1',
        'panda-muted': '#9aa3c2',
        'panda-accent': '#445fe6',
        'panda-success': '#7fd288',
        'panda-warning': '#ffa500',
        'panda-error': '#ff6b6b'
      }
    }
  },
  plugins: []
};
