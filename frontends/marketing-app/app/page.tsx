"use client";
import { useState } from 'react';
import { callApi } from '../components/api';
export default function Page() {
  const [email, setEmail] = useState('marketer@example.com');
  const [password, setPassword] = useState('Password123!');
  const [token, setToken] = useState('');
  const [output, setOutput] = useState('Marketing app is mapped to /api/marketing and uses a lead-engagement workflow.');
  async function register() { const data = await callApi('/auth/register', 'POST', { name: 'Marketing User', email, password, roles: ['marketing'] }); setToken(data.token); setOutput(JSON.stringify(data, null, 2)); }
  async function login() { const data = await callApi('/auth/login', 'POST', { email, password }); setToken(data.token); setOutput(JSON.stringify(data, null, 2)); }
  async function dashboard() { const data = await callApi('/marketing/dashboard', 'GET', undefined, token); setOutput(JSON.stringify(data, null, 2)); }
  async function workflow() { const data = await callApi('/marketing/workflows/lead-engagement', 'POST', { lead: { company: 'Agency Assist JP', personName: 'Minh Tuan', email: 'minh_tuan@gmail.com', fit: 88, intent: 84, urgency: 75, channel: 'webinar', tags: ['decision-maker'], landingPage: '/events/backend-modernization' }, engagement: { clicks: 2, visits: 3, pricingVisits: 2 }, expectedDeal: 22000 }, token); setOutput(JSON.stringify(data, null, 2)); }
  async function createCampaign() { const data = await callApi('/marketing/campaign/campaigns', 'POST', { payload: { name: 'Q2 Growth Sprint', subject: 'Backend modernization webinar follow-up', budget: 18000, targetLeads: 240, targetListId: 'webinar-hot', templateCode: 'follow-up-01' } }, token); setOutput(JSON.stringify(data, null, 2)); }
  return (<main className="container"><section className="hero"><span className="badge">Marketing App (Next.js)</span><h1>Marketing Automation Console</h1><p>Lead capture, scoring, hot-lead prioritisation, tracking, and campaign launch flow through <code>/api/marketing/*</code> to <code>bff-marketing</code>.</p></section><section className="grid two" style={{ marginTop: 20 }}><div className="card"><div>Email</div><input value={email} onChange={(e) => setEmail(e.target.value)} /><div style={{marginTop:12}}>Password</div><input type="password" value={password} onChange={(e) => setPassword(e.target.value)} /><div className="row" style={{marginTop:14}}><button onClick={register}>Register</button><button className="secondary" onClick={login}>Login</button><button className="secondary" onClick={dashboard} disabled={!token}>Dashboard</button><button className="secondary" onClick={createCampaign} disabled={!token}>Create campaign</button><button className="secondary" onClick={workflow} disabled={!token}>Lead engagement</button></div></div><div className="card"><div className="code">{output}</div></div></section></main>);
}
