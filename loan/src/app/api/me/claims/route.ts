import { NextRequest, NextResponse } from 'next/server'
import { getUserClaims } from '@/lib/kv'

export async function GET(request: NextRequest) {
  const userId = request.headers.get('x-user-id')
  if (!userId) return NextResponse.json({ error: 'x-user-id required' }, { status: 400 })
  const claims = await getUserClaims(userId)
  return NextResponse.json({ claims })
}
