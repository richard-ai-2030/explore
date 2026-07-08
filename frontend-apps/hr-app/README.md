# HR App

Angular front end for the Talent/HR domain console. It is a small standalone Angular 18 application that lets a user register or log in, then exercise the talents BFF through dashboard, employee creation, and hire-to-engage workflow actions.

## What This App Does

- Presents a simple HR/Talent console UI.
- Authenticates through the platform API gateway at `http://127.0.0.1:8888/api/auth/*`.
- Calls Talent domain endpoints through `http://127.0.0.1:8888/api/talents/*`.
- Stores the returned bearer token in an Angular signal for the current browser session.
- Uses seeded demo form values:
  - Email: `hr@example.com`
  - Password: `Password123!`

The UI is implemented in [src/main.ts](src/main.ts) as a standalone Angular component. Styling lives in [src/styles.css](src/styles.css).

## Project Shape

```text
hr-app/
  angular.json        Angular CLI project configuration
  package.json        npm scripts and Angular dependencies
  src/
    index.html        HTML shell
    main.ts           Standalone Angular application/component
    styles.css        Global styles
```

## Local Prerequisites

- Node.js and npm
- Angular CLI dependency installed from this project, via `npm install`
- Platform backend/API gateway available on `127.0.0.1:8888`

The app already has `node_modules` in this workspace, but a fresh checkout should run `npm install`.

## Run The Front End

From this folder:

```powershell
npm install
npm start
```

`npm start` runs:

```powershell
ng serve --host 0.0.0.0 --port 4200
```

Open:

```text
http://127.0.0.1:4200
```

## Run Against The Local Platform Gateway

The frontend expects the API gateway here:

```text
http://127.0.0.1:8888/api
```

In the broader workspace, the local development pipeline uses an ingress port-forward:

```powershell
kubectl port-forward -n ingress-nginx svc/ingress-nginx-controller 8888:80
```

That gateway routes protected Talent calls from:

```text
/api/talents/*
```

to the `bff-talents` service, whose local service port is `7012`. Auth calls use:

```text
/api/auth/*
```

## Useful Checks

Build the Angular app:

```powershell
npm run build
```

Check whether the gateway is responding:

```powershell
curl http://127.0.0.1:8888/api/auth/health
```

After opening the app, use the buttons in this order:

1. `Register` or `Login`
2. `Dashboard`
3. `Create employee`
4. `Hire to engage`

The last three buttons are disabled until a token is returned.

## Notes

- The API base URL is currently hard-coded in [src/main.ts](src/main.ts) as `http://127.0.0.1:8888/api`.
- There is no test script configured in `package.json`; build verification is the available local check.
- The app has no assets configured in `angular.json`.
