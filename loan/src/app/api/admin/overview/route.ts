import { NextResponse } from 'next/server'
import { getAllUserIds, getUser, getUserClaims, getUserLent } from '@/lib/kv'

export async function GET() {
  const userIds = await getAllUserIds()
  const entries = await Promise.all(
    userIds.map(async id => {
      const [user, claims, lent] = await Promise.all([
        getUser(id),
        getUserClaims(id),
        getUserLent(id),
      ])
      return { user, claims, lent }
    }),
  )
  return NextResponse.json(entries.filter(e => e.user !== null))
}
