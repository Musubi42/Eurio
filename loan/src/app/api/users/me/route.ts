import { NextRequest, NextResponse } from 'next/server'
import { getUser } from '@/lib/kv'

export async function GET(request: NextRequest) {
  const userId = request.headers.get('x-user-id')
  if (!userId) return NextResponse.json({ error: 'x-user-id required' }, { status: 400 })
  const user = await getUser(userId)
  if (!user) return NextResponse.json({ error: 'not found' }, { status: 404 })
  return NextResponse.json(user)
}
