import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import fs from 'node:fs'
import path from 'node:path'

// Portal tickets are stored as JSON files next to the rest of the mock data,
// so the ingestors pick them up like any other source.
const TICKETS_DIR = path.resolve(__dirname, '../data/portal')
const MAX_BODY = 64 * 1024
const MAX_TITLE = 500
const MAX_FIELDS = 32
const MAX_KEY = 100
const MAX_VALUE = 4000
const TICKET_ID = /^portal-\d{4}-\d{2}-\d{2}-\d{3,}$/
const FORBIDDEN_KEYS = new Set(['__proto__', 'constructor', 'prototype'])
const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1'])
const AUTHORS = new Set([
  'lucas.maes@foo.be',
  'nina.wouters@foo.be',
  'jonas.mertens@foo.be',
  'pieter.janssens@foo.be',
  'amira.haddad@foo.be',
])

class HttpError extends Error {
  constructor(status, message) {
    super(message)
    this.status = status
  }
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = []
    let size = 0
    let failed = false
    const declared = Number(req.headers['content-length'])
    if (declared > MAX_BODY) {
      reject(new HttpError(413, 'Request body too large'))
      req.resume()
      return
    }
    req.on('data', (chunk) => {
      if (failed) return
      size += chunk.length
      if (size > MAX_BODY) {
        failed = true
        reject(new HttpError(413, 'Request body too large'))
        req.resume()
        return
      }
      chunks.push(chunk)
    })
    req.on('end', () => failed || resolve(Buffer.concat(chunks).toString('utf-8')))
    req.on('error', reject)
  })
}

const isPlainObject = (v) =>
  v !== null && typeof v === 'object' && !Array.isArray(v) && Object.getPrototypeOf(v) === Object.prototype

const boundedString = (v, max) => typeof v === 'string' && v.trim().length > 0 && v.length <= max

function parseTicket(raw) {
  let body
  try {
    body = JSON.parse(raw)
  } catch {
    throw new HttpError(400, 'Invalid JSON')
  }
  if (!isPlainObject(body)) throw new HttpError(400, 'Expected a JSON object')
  const { author, title, fields } = body
  if (typeof author !== 'string' || !AUTHORS.has(author)) throw new HttpError(400, 'Unknown author')
  if (!boundedString(title, MAX_TITLE) || /[\r\n]/.test(title)) throw new HttpError(400, 'Invalid title')
  if (!isPlainObject(fields)) throw new HttpError(400, 'Invalid fields')
  const entries = Object.entries(fields)
  if (entries.length === 0 || entries.length > MAX_FIELDS) throw new HttpError(400, 'Invalid fields')
  for (const [k, v] of entries) {
    if (!boundedString(k, MAX_KEY) || FORBIDDEN_KEYS.has(k) || /[\r\n]/.test(k)) throw new HttpError(400, 'Invalid field name')
    const ok = typeof v === 'string' ? v.length <= MAX_VALUE : typeof v === 'number' && Number.isFinite(v)
    if (!ok) throw new HttpError(400, 'Invalid field value')
  }
  return { author, title, entries }
}

function sameOrigin(req) {
  const origin = req.headers.origin
  if (!origin) return true
  try {
    return new URL(origin).host === req.headers.host
  } catch {
    return false
  }
}

function localHost(req) {
  try {
    return LOCAL_HOSTS.has(new URL(`http://${req.headers.host}`).hostname)
  } catch {
    return false
  }
}

function listTickets() {
  if (!fs.existsSync(TICKETS_DIR)) return []
  return fs
    .readdirSync(TICKETS_DIR)
    .filter((f) => f.endsWith('.json'))
    .map((f) => {
      try {
        return JSON.parse(fs.readFileSync(path.join(TICKETS_DIR, f), 'utf-8'))
      } catch {
        return null
      }
    })
    .filter((t) => t && typeof t.id === 'string' && typeof t.timestamp === 'string')
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
        res.setHeader('X-Content-Type-Options', 'nosniff')
        res.setHeader('Cache-Control', 'no-store')
        try {
          if (!localHost(req)) throw new HttpError(403, 'Host not allowed')
          if (req.method === 'GET') {
            res.end(JSON.stringify(listTickets()))
            return
          }
          if (req.method === 'POST') {
            if (!sameOrigin(req)) throw new HttpError(403, 'Cross-origin request rejected')
            const type = String(req.headers['content-type'] ?? '').split(';')[0].trim().toLowerCase()
            if (type !== 'application/json') throw new HttpError(415, 'Content-Type must be application/json')
            const { author, title, entries } = parseTicket(await readBody(req))
            const timestamp = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z')
            for (let attempt = 0; ; attempt++) {
            const ticket = {
              id: nextId(timestamp.slice(0, 10)),
              source: 'portal',
              timestamp,
              author,
              recipients: [],
              title,
              body: entries
                .map(([k, v]) => `${k}: ${v}`)
                .join('\n'),
            }
            if (!TICKET_ID.test(ticket.id)) throw new Error('Invalid ticket id')
            const file = path.join(TICKETS_DIR, `${ticket.id}.json`)
            if (path.dirname(file) !== TICKETS_DIR) throw new Error('Invalid ticket path')
            fs.mkdirSync(TICKETS_DIR, { recursive: true })
            try {
              fs.writeFileSync(file, JSON.stringify(ticket, null, 2) + '\n', { flag: 'wx' })
            } catch (err) {
              if (err?.code === 'EEXIST' && attempt < 5) continue
              throw err
            }
            res.statusCode = 201
            res.end(JSON.stringify(ticket))
            return
            }
          }
          res.statusCode = 405
          res.end(JSON.stringify({ error: 'Method not allowed' }))
        } catch (err) {
          if (err instanceof HttpError) {
            res.statusCode = err.status
            res.end(JSON.stringify({ error: err.message }))
            return
          }
          console.error('[tickets-api]', err)
          res.statusCode = 500
          res.end(JSON.stringify({ error: 'Internal server error' }))
        }
      })
    },
  }
}

export default defineConfig({
  plugins: [react(), tailwindcss(), ticketsApi()],
  server: { host: 'localhost' },
})
