import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import fs from 'node:fs'
import path from 'node:path'

// Portal tickets are stored as JSON files next to the rest of the mock data,
// so the ingestors pick them up like any other source.
const TICKETS_DIR = path.resolve(__dirname, '../data/portal')

function readBody(req) {
  return new Promise((resolve, reject) => {
    let data = ''
    req.on('data', (chunk) => (data += chunk))
    req.on('end', () => resolve(data))
    req.on('error', reject)
  })
}

function listTickets() {
  if (!fs.existsSync(TICKETS_DIR)) return []
  return fs
    .readdirSync(TICKETS_DIR)
    .filter((f) => f.endsWith('.json'))
    .map((f) => JSON.parse(fs.readFileSync(path.join(TICKETS_DIR, f), 'utf-8')))
    .sort((a, b) => b.timestamp.localeCompare(a.timestamp))
}

function nextId(date) {
  const prefix = `portal-${date}-`
  const taken = listTickets()
    .map((t) => t.id)
    .filter((id) => id.startsWith(prefix))
    .map((id) => Number(id.slice(prefix.length)))
  const n = Math.max(0, ...taken) + 1
  return prefix + String(n).padStart(3, '0')
}

function ticketsApi() {
  return {
    name: 'tickets-api',
    configureServer(server) {
      server.middlewares.use('/api/tickets', async (req, res) => {
        res.setHeader('Content-Type', 'application/json')
        try {
          if (req.method === 'GET') {
            res.end(JSON.stringify(listTickets()))
            return
          }
          if (req.method === 'POST') {
            const { author, title, fields } = JSON.parse(await readBody(req))
            const timestamp = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z')
            const ticket = {
              id: nextId(timestamp.slice(0, 10)),
              source: 'portal',
              timestamp,
              author,
              recipients: [],
              title,
              body: Object.entries(fields)
                .map(([k, v]) => `${k}: ${v}`)
                .join('\n'),
            }
            fs.mkdirSync(TICKETS_DIR, { recursive: true })
            fs.writeFileSync(
              path.join(TICKETS_DIR, `${ticket.id}.json`),
              JSON.stringify(ticket, null, 2) + '\n',
            )
            res.statusCode = 201
            res.end(JSON.stringify(ticket))
            return
          }
          res.statusCode = 405
          res.end(JSON.stringify({ error: 'Method not allowed' }))
        } catch (err) {
          res.statusCode = 500
          res.end(JSON.stringify({ error: String(err) }))
        }
      })
    },
  }
}

export default defineConfig({
  plugins: [react(), tailwindcss(), ticketsApi()],
})
