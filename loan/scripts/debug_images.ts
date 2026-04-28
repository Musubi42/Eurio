import { createClient } from '@supabase/supabase-js'

async function main() {
  const sb = createClient(process.env.SUPABASE_URL!, process.env.SUPABASE_SERVICE_ROLE_KEY!)
  const { data, error } = await sb.from('coins').select('eurio_id, images').eq('face_value', 2).not('images', 'is', null).neq('images', '[]').limit(3)
  if (error) { console.error(error); process.exit(1) }
  console.log(JSON.stringify(data, null, 2))
}
main()
