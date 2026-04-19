import type { Config } from 'tailwindcss'
import animate from 'tailwindcss-animate'

// Les tokens Eurio (couleurs, typo, spacing) viennent de shared/tokens.css
// via src/styles/index.css. On mappe ici les CSS vars vers Tailwind.

export default {
  darkMode: ['class'],
  content: [
    './index.html',
    './src/**/*.{vue,ts}',
  ],
  theme: {
    container: {
      center: true,
      padding: '2rem',
      screens: { '2xl': '1400px' },
    },
    extend: {
      // shadcn-vue theme — valeurs en HSL brutes (sans hsl())
      // Mapping défini dans src/styles/index.css
      colors: {
        border:      'hsl(var(--border))',
        input:       'hsl(var(--input))',
        ring:        'hsl(var(--ring))',
        background:  'hsl(var(--background))',
        foreground:  'hsl(var(--foreground))',
        primary: {
          DEFAULT:    'hsl(var(--primary))',
          foreground: 'hsl(var(--primary-foreground))',
        },
        secondary: {
          DEFAULT:    'hsl(var(--secondary))',
          foreground: 'hsl(var(--secondary-foreground))',
        },
        muted: {
          DEFAULT:    'hsl(var(--muted))',
          foreground: 'hsl(var(--muted-foreground))',
        },
        accent: {
          DEFAULT:    'hsl(var(--accent))',
          foreground: 'hsl(var(--accent-foreground))',
        },
        destructive: {
          DEFAULT:    'hsl(var(--destructive))',
          foreground: 'hsl(var(--destructive-foreground))',
        },
        card: {
          DEFAULT:    'hsl(var(--card))',
          foreground: 'hsl(var(--card-foreground))',
        },
        // Accès direct aux tokens Eurio pour les composants custom
        gold:         'var(--gold)',
        'gold-deep':  'var(--gold-deep)',
        'indigo-700': 'var(--indigo-700)',
        'indigo-800': 'var(--indigo-800)',
        'indigo-900': 'var(--indigo-900)',
        'ink':        'var(--ink)',
        'ink-500':    'var(--ink-500)',
        'surface':    'var(--surface)',
        'surface-1':  'var(--surface-1)',
      },
      borderRadius: {
        lg:   'var(--radius-lg)',
        md:   'var(--radius-md)',
        sm:   'var(--radius-sm)',
        xs:   'var(--radius-xs)',
        full: '999px',
      },
      fontFamily: {
        display: ['var(--font-display)'],
        ui:      ['var(--font-ui)'],
        mono:    ['var(--font-mono)'],
      },
      boxShadow: {
        card:   'var(--shadow-card)',
        gold:   'var(--shadow-gold)',
        indigo: 'var(--shadow-indigo)',
      },
      transitionTimingFunction: {
        'out':    'var(--ease-out)',
        'spring': 'var(--ease-spring)',
      },
    },
  },
  plugins: [animate],
} satisfies Config
