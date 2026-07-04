# Frontend — Cabinet Management System

React + Vite + TypeScript, built as a PWA (installable on iOS/Android home screen).
Phase 0 scope: login, session, app shell in Townsend aqua.

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

`public/icon-192.png` and `public/icon-512.png` are placeholders — replace with
Townsend-branded icons before anyone installs this to a home screen.
