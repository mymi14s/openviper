/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{vue,js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        primary: '#1d9bf0',
        dark: '#15202b',
        darker: '#192734',
        border: '#38444d',
        muted: '#8899a6',
      },
    },
  },
  plugins: [],
}