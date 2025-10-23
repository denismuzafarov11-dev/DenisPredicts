import { useEffect, useState } from 'react'

export default function Home(){
  const [data, setData] = useState(null)
  useEffect(()=> {
    fetch('/api/predictions').then(r=>r.json()).then(setData).catch(console.error)
  },[])
  return (
    <div style={{background:'#000',color:'#fff',minHeight:'100vh',padding:20,fontFamily:'Inter, Arial'}}>
      <header style={{maxWidth:1000,margin:'0 auto'}}>
        <h1 style={{color:'#D4AF37',fontSize:36}}>DenisPredicts</h1>
        <p style={{color:'#bbb'}}>v6 — Финальная упаковка: Docker + render.yaml + Vercel ready. Русский интерфейс.</p>
      </header>
      <main style={{maxWidth:1000,margin:'20px auto'}}>
        {!data && <p>Загрузка прогнозов...</p>}
        {data && <>
          <p>Последнее обновление: {data.last_update}</p>
          <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:14}}>
            {data.predictions.map(p => (
              <div key={p.fixture_id} style={{background:'#0b0b0b',padding:14,borderRadius:10,boxShadow:'0 2px 6px rgba(0,0,0,0.5)'}}>
                <div style={{fontWeight:700,fontSize:16}}>{p.home} — {p.away}</div>
                <div style={{marginTop:6,fontSize:13,color:'#ddd'}}>1X2: хозяева {Math.round(p.probabilities.home*100)}% / ничья {Math.round(p.probabilities.draw*100)}% / гости {Math.round(p.probabilities.away*100)}%</div>
                <div style={{marginTop:6,fontSize:13,color:'#ddd'}}>Тотал: {p.total_pred} (ожид. {p.exp_total})</div>
                <div style={{marginTop:6,fontSize:13,color:'#ddd'}}>Среднее ЖК: {p.avg_yellow_cards} — прогноз: {p.yc_pred}</div>
                <div style={{marginTop:8,fontSize:13,color:'#ccc'}}>Топ точных счётов:</div>
                <ul style={{fontSize:13,color:'#ccc'}}>
                  {p.top_scores.map(([s,pr]) => <li key={s}>{s} — {Math.round(pr*100)}%</li>)}
                </ul>
                <div style={{marginTop:8, display:'flex', gap:8, alignItems:'center'}}>
                  <div style={{fontSize:13,color:'#fff'}}>Value Index: <strong style={{color: p.value_index > 0 ? '#7CFC00' : '#FF6347'}}>{p.value_index}</strong></div>
                  <button onClick={async ()=> {
                    const r = await fetch(`/api/explain?fixture_id=${p.fixture_id}`)
                    const d = await r.json()
                    alert(d.explanation || JSON.stringify(d))
                  }} style={{background:'#D4AF37',border:'none',padding:'8px 10px',borderRadius:6,cursor:'pointer'}}>Объяснить</button>
                </div>
              </div>
            ))}
          </div>
        </>}
      </main>
    </div>
  )
}
