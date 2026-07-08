# Production App

Small Vue 3 + Vite frontend for the production domain console. It provides a lightweight UI for authentication and production/accounting workflows that are expected to be routed through a backend API.

## What This App Does

- Mounts a Vue app from `src/main.js` into `index.html`.
- Renders a single console in `src/App.vue`.
- Supports register/login and stores the returned bearer token in component state.
- Calls production-domain endpoints for dashboard, invoice creation, and procure-to-stock workflow actions.
- Uses `VITE_API_BASE_URL` for API calls, defaulting to `/api` when the variable is not set.

The default UI copy assumes production and accounting services are available under `/api/production/*` and routed to `bff-production`.

## Tech Stack

- Vue `3.5.12`
- Vite `5.4.10`
- `@vitejs/plugin-vue`

## Local Setup

Install dependencies:

```powershell
npm install
```

Start the dev server:

```powershell
npm run dev
```

The dev script runs Vite on port `5173` and binds to `0.0.0.0`:

```text
http://localhost:5173
```

If the backend is not available at `/api`, provide an API base URL when starting the app:

```powershell
$env:VITE_API_BASE_URL = "http://localhost:8080/api"
npm run dev
```

## Build

Create a production build:

```powershell
npm run build
```

The build output is written to `dist/`.

## Verification Notes

Verified with:

- Node `v20.18.0`
- npm `10.8.2`
- `npm run build`

In the Codex sandbox, `npm run build` initially failed with a Windows `EPERM` while Node resolved `C:\Users\richa`. Running the same command with normal filesystem access succeeded.
