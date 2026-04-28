import { NextRequest, NextResponse } from 'next/server'

export function middleware(request: NextRequest) {
  const auth = request.headers.get('authorization')
  if (!auth) return unauthorized()
  const [type, credentials] = auth.split(' ')
  if (type !== 'Basic') return unauthorized()
  const decoded = Buffer.from(credentials, 'base64').toString('utf-8')
  const [username, ...rest] = decoded.split(':')
  const password = rest.join(':')
  if (
    username === process.env.LOAN_ADMIN_USERNAME &&
    password === process.env.LOAN_ADMIN_PASSWORD
  ) {
    return NextResponse.next()
  }
  return unauthorized()
}

function unauthorized() {
  return new NextResponse('Unauthorized', {
    status: 401,
    headers: { 'WWW-Authenticate': 'Basic realm="Loan Admin"' },
  })
}

export const config = {
  matcher: ['/admin/:path*', '/api/admin/:path*'],
}
