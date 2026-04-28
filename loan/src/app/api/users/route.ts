import { NextRequest, NextResponse } from 'next/server'
import { nanoid } from 'nanoid'
import { createUser } from '@/lib/kv'

export async function POST(request: NextRequest) {
  const body = await request.json() as { name?: string; emoji?: string }
  if (!body.name?.trim() || !body.emoji) {
    return NextResponse.json({ error: 'name and emoji required' }, { status: 400 })
  }
  const user = {
    id: nanoid(8),
    name: body.name.trim().slice(0, 40),
    emoji: body.emoji,
    created_at: new Date().toISOString(),
  }
  await createUser(user)
  return NextResponse.json(user, { status: 201 })
}
