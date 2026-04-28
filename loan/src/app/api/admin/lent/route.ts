import { NextRequest, NextResponse } from 'next/server'
import { addLent, removeLent } from '@/lib/kv'

export async function POST(request: NextRequest) {
  const body = await request.json() as { userId?: string; eurio_id?: string }
  if (!body.userId || !body.eurio_id) {
    return NextResponse.json({ error: 'userId and eurio_id required' }, { status: 400 })
  }
  await addLent(body.userId, body.eurio_id)
  return NextResponse.json({ ok: true })
}

export async function DELETE(request: NextRequest) {
  const body = await request.json() as { userId?: string; eurio_id?: string }
  if (!body.userId || !body.eurio_id) {
    return NextResponse.json({ error: 'userId and eurio_id required' }, { status: 400 })
  }
  await removeLent(body.userId, body.eurio_id)
  return NextResponse.json({ ok: true })
}
