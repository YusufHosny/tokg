# Lumivia Employee Portal (dummy app)

A fake internal portal for the fictional company Lumivia NV. Employees use it to report sick leave, order equipment and start a new hire.

Every submission is saved as a JSON ticket in `../data/portal/`, using the same format as the rest of the mock data, so the ingestors pick it up as a `portal` source.

## Run

```bash
npm install
npm run dev
```

Open http://localhost:5173. Use "Signed in as" in the top right to switch between employees.

## How it works

- Vite + React + Tailwind. All the UI is in `src/App.jsx`.
- There is no backend. A small Vite plugin in `vite.config.js` serves `GET /api/tickets` (lists tickets) and `POST /api/tickets` (writes a new ticket file). This only works with `npm run dev`.
