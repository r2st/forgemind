/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js,ts}'],
  theme: {
    extend: {
      colors: {
        ink: {
          900: '#0a0e14',
          800: '#0f141b',
          700: '#161c25',
          600: '#1d2530',
          500: '#2a3340',
          400: '#3d4856',
        },
        accent: {
          500: '#5eead4',  // teal — primary
          600: '#2dd4bf',
          700: '#14b8a6',
        },
        warn: {
          500: '#fbbf24',
          600: '#f59e0b',
        },
        crit: {
          500: '#f87171',
          600: '#ef4444',
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui'],
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
    },
  },
  plugins: [],
}
