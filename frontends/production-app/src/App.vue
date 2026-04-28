<script setup>
import { ref } from 'vue'
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'
const email = ref('ops@example.com')
const password = ref('Password123!')
const token = ref('')
const output = ref('Production + Accounting services are routed through /api/production/* to bff-production.')
async function api(path, method, body) {
  const headers = { 'Content-Type': 'application/json' }
  if (token.value) headers.Authorization = `Bearer ${token.value}`
  const response = await fetch(`${API_BASE_URL}${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined })
  const data = await response.json()
  if (!response.ok) throw new Error(data.detail || data.error || 'Request failed')
  return data
}
async function register() { const data = await api('/auth/register', 'POST', { name: 'Production User', email: email.value, password: password.value, roles: ['operations'] }); token.value = data.token; output.value = JSON.stringify(data, null, 2) }
async function login() { const data = await api('/auth/login', 'POST', { email: email.value, password: password.value }); token.value = data.token; output.value = JSON.stringify(data, null, 2) }
async function dashboard() { output.value = JSON.stringify(await api('/production/dashboard', 'GET'), null, 2) }
async function workflow() { output.value = JSON.stringify(await api('/production/workflow/procure-to-stock', 'POST', { supplier: { name: 'Kanto Metals', reliability: 92, compliance: 89 }, procurement: { amount: 5200 }, inventory: { name: 'Steel Coil', onHand: 180, reserved: 42, reorderPoint: 30 }, quality: { sampleSize: 30, defects: 1 }, logistics: { etaDays: 6, delayRisk: 20 } }), null, 2) }
async function createInvoice() { output.value = JSON.stringify(await api('/production/invoice/invoices', 'POST', { payload: { customer: 'Internal Plant', amount: 5200, dueDays: 21 } }), null, 2) }
</script>
<template><main class="page"><section class="hero"><span class="badge">Production App (Vue)</span><h1>Production Domain Console</h1><p>Production, logistics, quality, and accounting workflows.</p></section><section class="panel"><label>Email</label><input v-model="email" /><label>Password</label><input v-model="password" type="password" /><div class="row"><button @click="register">Register</button><button @click="login">Login</button><button @click="dashboard" :disabled="!token">Dashboard</button><button @click="createInvoice" :disabled="!token">Create invoice</button><button @click="workflow" :disabled="!token">Procure to stock</button></div></section><section class="panel"><pre>{{ output }}</pre></section></main></template>
<style>body{margin:0;font-family:Arial,Helvetica,sans-serif;background:#111827;color:#eef2ff}.page{max-width:1080px;margin:0 auto;padding:24px}.hero,.panel{background:#172036;border:1px solid #283655;border-radius:18px;padding:24px;margin-bottom:20px}.badge{display:inline-block;padding:6px 10px;background:#24355f;border-radius:999px;margin-bottom:12px}label{display:block;margin:10px 0 6px;color:#b6c3e1}input{width:100%;padding:12px;border-radius:12px;border:1px solid #31426d;background:#0f1730;color:#fff}.row{display:flex;flex-wrap:wrap;gap:10px;margin-top:14px}button{border:0;border-radius:12px;padding:12px 14px;background:#60a5fa;color:#0b1020;font-weight:700;cursor:pointer}pre{white-space:pre-wrap;background:#0f1730;padding:16px;border-radius:12px;overflow:auto}</style>
