import { kv } from '@vercel/kv'

export type KVUser = {
  id: string
  name: string
  emoji: string
  created_at: string
}

export async function createUser(user: KVUser): Promise<void> {
  await kv.hset(`user:${user.id}`, user)
  await kv.sadd('users', user.id)
}

export async function getUser(userId: string): Promise<KVUser | null> {
  return kv.hgetall<KVUser>(`user:${userId}`)
}

export async function getUserClaims(userId: string): Promise<string[]> {
  const result = await kv.smembers(`user:${userId}:claims`)
  return result as string[]
}

export async function addClaim(userId: string, eurioId: string): Promise<void> {
  await kv.sadd(`user:${userId}:claims`, eurioId)
}

export async function removeClaim(userId: string, eurioId: string): Promise<void> {
  await kv.srem(`user:${userId}:claims`, eurioId)
}

export async function getUserLent(userId: string): Promise<string[]> {
  const result = await kv.smembers(`user:${userId}:lent`)
  return result as string[]
}

export async function addLent(userId: string, eurioId: string): Promise<void> {
  await kv.sadd(`user:${userId}:lent`, eurioId)
}

export async function removeLent(userId: string, eurioId: string): Promise<void> {
  await kv.srem(`user:${userId}:lent`, eurioId)
}

export async function getAllUserIds(): Promise<string[]> {
  const result = await kv.smembers('users')
  return result as string[]
}
