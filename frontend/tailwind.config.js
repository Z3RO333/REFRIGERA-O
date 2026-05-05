/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        status: {
          normal: '#22C55E',
          warning: '#EAB308',
          critical: '#EF4444',
          low_eff: '#F97316',
          no_reading: '#6B7280',
          off: '#3B82F6',
        },
      },
    },
  },
  plugins: [],
}
