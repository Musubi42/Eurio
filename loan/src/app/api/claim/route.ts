import { NextRequest, NextResponse } from 'next/server'
import { addClaim, removeClaim } from '@/lib/kv'

export async function POST(request: NextRequest) {
  const userId = request.headers.get('x-user-id')
  if (!userId) return NextResponse.json({ error: 'x-user-id required' }, { status: 400 })
  const body = await request.json() as { eurio_id?: string }
  if (!body.eurio_id) return NextResponse.json({ error: 'eurio_id required' }, { status: 400 })
  await addClaim(userId, body.eurio_id)
  return NextResponse.json({ ok: true })
}

export async function DELETE(request: NextRequest) {
  const userId = request.headers.get('x-user-id')
  if (!userId) return NextResponse.json({ error: 'x-user-id required' }, { status: 400 })
  const body = await request.json() as { eurio_id?: string }
  if (!body.eurio_id) return NextResponse.json({ error: 'eurio_id required' }, { status: 400 })
  await removeClaim(userId, body.eurio_id)
  return NextResponse.json({ ok: true })
}
