import type { Config } from 'tailwindcss';

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        sand: '#f2e5cf',
        lagoon: '#0f766e',
        tide: '#1f4e5f',
        coral: '#ea6f5a',
        ink: '#10232d',
      },
      boxShadow: {
        panel: '0 24px 80px rgba(16, 35, 45, 0.14)',
      },
      borderRadius: {
        xl2: '1.5rem',
      },
      fontFamily: {
        display: ['Georgia', 'serif'],
        body: ['Segoe UI', 'Helvetica Neue', 'Arial', 'sans-serif'],
      },
    },
  },
  plugins: [],
} satisfies Config;
