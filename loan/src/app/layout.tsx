import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'Eurio · Prête-moi tes 2€',
  description: 'Aide Raphaël à entraîner son app de scan de pièces en lui prêtant tes 2€.',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr">
      <body className="min-h-screen">{children}</body>
    </html>
  )
}
