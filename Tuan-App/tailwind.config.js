/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        tuan: {
          bg: 'var(--bg-tuan-main)',
          sidebar: 'var(--bg-tuan-sidebar)',
          border: 'var(--border-tuan)',
          text: 'var(--text-tuan-main)',
          textSecondary: 'var(--text-tuan-secondary)',
          accent: 'var(--bg-tuan-accent)',
          hover: 'var(--bg-tuan-hover)',
          btnHover: 'var(--bg-tuan-btn-hover)',
          input: 'var(--bg-tuan-input)',
          artBg: 'var(--tuan-art-bg)',
        },
        blue: {
          50: '#EAF4FF', 100: '#D6E9FF', 200: '#AED5FF', 300: '#7FBEFE',
          400: '#4FA8FF', 500: '#2E92FF', 600: '#1a88ff', 700: '#1577E6',
          800: '#1461BC', 900: '#16528F', 950: '#0E3460',
        },
        teal: {
          50: '#E6FBF9', 100: '#CFF6F1', 200: '#A3ECE4', 300: '#6FDAD0',
          400: '#5BC0BE', 500: '#3FB0AD', 600: '#2E9693',
        },
      },
      fontFamily: {
        sans: ['Figtree', 'system-ui', '-apple-system', '"Segoe UI"', 'Roboto', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
