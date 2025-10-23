export default async function handler(req, res) {
  const BACKEND = process.env.BACKEND_URL || 'http://localhost:8000'
  const r = await fetch(`${BACKEND}/predictions`)
  const data = await r.json()
  res.status(200).json(data)
}
