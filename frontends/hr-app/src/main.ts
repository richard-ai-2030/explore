import { bootstrapApplication } from '@angular/platform-browser';
import { Component, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
@Component({selector:'app-root',standalone:true,imports:[FormsModule],template:`<main class="page"><section class="hero"><span class="badge">HR App (Angular)</span><h1>Talent Domain Console</h1><p>Recruitment, employees, training, and motivation flow through <code>/api/talents/*</code>.</p></section><section class="panel"><label>Email</label><input [(ngModel)]="email" /><label>Password</label><input [(ngModel)]="password" type="password" /><div class="row"><button (click)="register()">Register</button><button (click)="login()">Login</button><button (click)="dashboard()" [disabled]="!token()">Dashboard</button><button (click)="createEmployee()" [disabled]="!token()">Create employee</button><button (click)="workflow()" [disabled]="!token()">Hire to engage</button></div></section><section class="panel"><pre>{{ output() }}</pre></section></main>`})
class AppComponent {
  email = 'hr@example.com';
  password = 'Password123!';
  token = signal('');
  output = signal('Talent services are grouped behind bff-talents and exposed at /api/talents/*');
    async api(path: string, method: string, body?: unknown) {
        const API_BASE_URL = 'http://127.0.0.1:8888/api';
        const headers: Record<string, string> = { 'Content-Type': 'application/json' }; if (this.token()) headers.Authorization = `Bearer ${this.token()}`;
        const response = await fetch(`${API_BASE_URL}${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined }); const data = await response.json(); if (!response.ok) throw new Error(data.detail || data.error || 'Request failed'); return data;
    }
  async register() { const data = await this.api('/auth/register', 'POST', { name: 'HR User', email: this.email, password: this.password, roles: ['hr'] }); this.token.set(data.token); this.output.set(JSON.stringify(data, null, 2)); }
  async login() { const data = await this.api('/auth/login', 'POST', { email: this.email, password: this.password }); this.token.set(data.token); this.output.set(JSON.stringify(data, null, 2)); }
  async dashboard() { this.output.set(JSON.stringify(await this.api('/talents/dashboard', 'GET'), null, 2)); }
  async createEmployee() { this.output.set(JSON.stringify(await this.api('/talents/employees/employees', 'POST', { payload: { employeeName: 'Aiko Sato', department: 'Talent', manager: 'Minh Tuan', level: 'L2', salary: 68000 } }), null, 2)); }
  async workflow() { this.output.set(JSON.stringify(await this.api('/talents/workflow/hire-to-engage', 'POST', { candidate: { candidateName: 'Aiko Sato', fit: 86, availability: 72, role: 'HRBP' }, employee: { employeeName: 'Aiko Sato', department: 'Talent', manager: 'Minh Tuan', level: 'L2', salary: 68000 }, training: { hours: 8, lateMinutes: 0 }, pulse: { mood: 80, recognition: 82, workload: 40 } }), null, 2)); }
}
bootstrapApplication(AppComponent);
