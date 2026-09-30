# SD Worx Portal (mock)

A mock SD Worx employee self-service portal, as used by employees of the fictional SD Worx client Foo BV. Employees report sick leave, order equipment and start a new hire.

Recall has no UI of its own: it is an API and MCP server. The idea is that SD Worx integrates it directly into portals like this one.

Every submission is saved as a JSON ticket in `../data/portal/`, in the same format as the rest of the mock data, so Recall ingests it as a `portal` source.

## Run

```bash
npm install
npm run dev
```

Open http://localhost:5173. Use "Signed in as" in the top right to switch between employees.

## How it works

- Vite + React + Tailwind. All the UI is in `src/App.jsx`; the SD Worx palette is in `src/index.css`.
- There is no backend. A small Vite plugin in `vite.config.js` serves `GET /api/tickets` (lists tickets) and `POST /api/tickets` (writes a new ticket file). This only works with `npm run dev`.
- The logo is an inline SVG approximation of the SD Worx mark, for demo purposes.
