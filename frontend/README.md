# Frontend — Cabinet Management System

React + Vite + TypeScript, built as a PWA (installable on iOS/Android home screen).
Carter Lumber branding: logo in `public/carter-logo.png`, deep green #125952 + orange #df5822.

## Run

```powershell
cd frontend
npm install
npm run dev        # http://localhost:5173
```

API calls go to `/api/*` and are proxied to the FastAPI backend at `localhost:8000`
(see `vite.config.ts`) — start the backend first.

## Build

```powershell
npm run build      # type-checks then bundles to dist/ with the PWA service worker
```

## PWA icons

`public/icon-192.png` and `public/icon-512.png` are the Carter Lumber wordmark on
brand green, generated from `public/carter-logo.png`.
