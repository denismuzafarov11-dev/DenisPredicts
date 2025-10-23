export default async function handler(req, res) {
  const BACKEND = process.env.BACKEND_URL || 'http://localhost:8000'
  const fid = req.query.fixture_id
  if(!fid) return res.status(400).json({error:'fixture_id required'})
  const r = await fetch(`${BACKEND}/ai/explain/${fid}`)
  const data = await r.json()
  res.status(200).json(data)
}
