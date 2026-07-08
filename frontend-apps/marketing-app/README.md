# Marketing App

Next.js marketing automation console for exercising the marketing BFF through REST and GraphQL endpoints.

## Stack

- Next.js 14 App Router
- React 18
- TypeScript
- npm

## Project Structure

```text
app/
  globals.css      Global styles
  layout.tsx       Root layout and metadata
  page.tsx         Marketing console UI
components/
  api.ts           REST and GraphQL fetch helpers
next.config.js     Next.js configuration
package.json       Local scripts and dependencies
```

## Prerequisites

- Node.js 20 or newer recommended
- npm
- A running backend API if you want the console buttons to return real data

## Install

```powershell
npm install
```

## Run Locally

```powershell
npm run dev
```

The app runs at:

```text
http://localhost:3000
```

The dev script is pinned to port `3000`:

```json
"dev": "next dev -p 3000"
```

## Backend Configuration

API calls are made from `components/api.ts`.

By default, the frontend uses:

```text
/api
```

Set `NEXT_PUBLIC_API_BASE_URL` when the backend is hosted somewhere else:

```powershell
$env:NEXT_PUBLIC_API_BASE_URL="http://localhost:8000/api"
npm run dev
```

Expected backend routes include:

- `POST /api/auth/register`
- `POST /api/auth/login`
- `GET /api/marketing/dashboard`
- `POST /api/marketing/workflows/lead-engagement`
- `POST /api/marketing/campaign/campaigns`
- `POST /api/marketing/graphql`

## Build

```powershell
npm run build
```

## Run Production Build

```powershell
npm run build
npm run start
```

The production server also runs on:

```text
http://localhost:3000
```

## Notes

- This app does not define local Next.js API routes.
- The UI is a client component and stores the auth token in React state only.
- The default test credentials in the UI are sample values for local testing.
