import { useEffect, useState } from 'react'

// Employee self-service portal run by SD Worx for its client Foo BV. Every submission is a
// ticket written to examples/data/portal/, which Recall ingests as a `portal` source.

const CLIENT = 'Foo BV'

const EMPLOYEES = [
  { name: 'Lucas Maes', email: 'lucas.maes@foo.be', role: 'Software Engineer' },
  { name: 'Nina Wouters', email: 'nina.wouters@foo.be', role: 'Product Designer' },
  { name: 'Jonas Mertens', email: 'jonas.mertens@foo.be', role: 'Account Executive' },
  { name: 'Pieter Janssens', email: 'pieter.janssens@foo.be', role: 'Engineering Manager' },
  { name: 'Amira Haddad', email: 'amira.haddad@foo.be', role: 'Sales Manager' },
]

const CATALOGUE = [
  { code: 'MON-27', name: '27" monitor (Dell P2725H)' },
  { code: 'KB-02', name: 'Ergonomic keyboard' },
  { code: 'MS-01', name: 'Wireless mouse' },
  { code: 'HS-03', name: 'Noise-cancelling headset' },
  { code: 'DK-01', name: 'USB-C docking station' },
  { code: 'WC-01', name: 'HD webcam' },
  { code: 'OTHER', name: 'Other (not in catalogue)' },
]

const PAGES = [
  { key: 'home', label: 'Home', icon: HomeIcon },
  { key: 'sick', label: 'Report sick leave', icon: HeartIcon },
  { key: 'equipment', label: 'Order equipment', icon: BoxIcon },
  { key: 'hire', label: 'Start a new hire', icon: UserPlusIcon },
  { key: 'requests', label: 'My requests', icon: ListIcon },
]

const today = () => new Date().toISOString().slice(0, 10)
const initials = (name) => name.split(' ').map((p) => p[0]).join('')

async function submitTicket(author, title, fields) {
  const res = await fetch('/api/tickets', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ author, title, fields }),
  })
  if (!res.ok) throw new Error((await res.json()).error)
  return res.json()
}

export default function App() {
  const [page, setPage] = useState('home')
  const [user, setUser] = useState(EMPLOYEES[0])
  const [lastTicket, setLastTicket] = useState(null)

  async function submit(title, fields) {
    const ticket = await submitTicket(user.email, `${title} - ${user.name}`, fields)
    setLastTicket(ticket)
    setPage('requests')
  }

  return (
    <div className="min-h-screen text-sdx-navy">
      <Header user={user} setUser={setUser} />
      <div className="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-6 md:flex-row md:px-6">
        <nav className="flex gap-1 overflow-x-auto md:w-60 md:shrink-0 md:flex-col">
          {PAGES.map((p) => {
            const active = page === p.key
            const Icon = p.icon
            return (
              <button
                key={p.key}
                onClick={() => setPage(p.key)}
                className={`group flex items-center gap-3 whitespace-nowrap rounded-lg px-3 py-2.5 text-left text-sm transition ${
                  active ? 'bg-white font-semibold text-sdx-navy shadow-sm' : 'text-sdx-navy/70 hover:bg-white/60'
                }`}
              >
                <span className={`h-5 w-1 rounded-full ${active ? 'bg-sdx-red' : 'bg-transparent'}`} />
                <Icon className={`h-4 w-4 ${active ? 'text-sdx-red' : 'text-sdx-navy/50'}`} />
                {p.label}
              </button>
            )
          })}
          <div className="mt-6 hidden rounded-xl bg-sdx-navy p-4 text-xs text-white/80 md:block">
            <div className="mb-1 font-semibold text-white">Need help?</div>
            Your SD Worx payroll consultant for {CLIENT} is <span className="text-white">Marc Dubois</span>.
          </div>
        </nav>

        <main className="min-w-0 flex-1">
          {page === 'home' && <Home user={user} go={setPage} />}
          {page === 'sick' && <SickLeaveForm user={user} onSubmit={submit} />}
          {page === 'equipment' && <EquipmentForm user={user} onSubmit={submit} />}
          {page === 'hire' && <NewHireForm user={user} onSubmit={submit} />}
          {page === 'requests' && <Requests highlight={lastTicket?.id} />}
        </main>
      </div>
      <footer className="mx-auto max-w-7xl px-6 pb-8 pt-4 text-xs text-sdx-navy/40">
        SD Worx Portal · {CLIENT} · demo environment
      </footer>
    </div>
  )
}

function Logo() {
  return (
    <div className="flex items-center gap-2" aria-label="SD Worx">
      <svg viewBox="0 0 34 30" className="h-7 w-8" aria-hidden="true">
        <polygon points="2,30 8,30 12,14 6,14" className="fill-sdx-blue" />
        <polygon points="11,30 17,30 23,6 17,6" className="fill-sdx-orange" />
        <polygon points="20,30 26,30 33,0 27,0" className="fill-sdx-red" />
      </svg>
      <span className="text-2xl font-bold tracking-tight text-sdx-navy">sd worx</span>
    </div>
  )
}

function Header({ user, setUser }) {
  return (
    <header className="border-b border-sdx-navy/10 bg-white">
      <div className="h-1 w-full bg-gradient-to-r from-sdx-blue via-sdx-orange to-sdx-red" />
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-4 py-3 md:px-6">
        <div className="flex items-center gap-4">
          <Logo />
          <span className="hidden h-6 w-px bg-sdx-navy/15 sm:block" />
          <div className="hidden leading-tight sm:block">
            <div className="text-sm font-semibold">Employee Portal</div>
            <div className="text-xs text-sdx-navy/50">{CLIENT}</div>
          </div>
        </div>
        <label className="flex items-center gap-3 text-sm">
          <span className="hidden text-sdx-navy/50 sm:inline">Signed in as</span>
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-sdx-navy text-xs font-semibold text-white">
            {initials(user.name)}
          </span>
          <select
            className="rounded-lg border border-sdx-navy/15 bg-white px-2 py-1.5 font-medium focus:border-sdx-red focus:outline-none"
            value={user.email}
            onChange={(e) => setUser(EMPLOYEES.find((u) => u.email === e.target.value))}
          >
            {EMPLOYEES.map((u) => (
              <option key={u.email} value={u.email}>
                {u.name}
              </option>
            ))}
          </select>
        </label>
      </div>
    </header>
  )
}

function Home({ user, go }) {
  const tiles = [
    { key: 'sick', title: 'Report sick leave', text: 'Let your manager and HR know you are ill.', icon: HeartIcon, accent: 'bg-sdx-red' },
    { key: 'equipment', title: 'Order equipment', text: 'Monitors, keyboards, headsets and more.', icon: BoxIcon, accent: 'bg-sdx-orange' },
    { key: 'hire', title: 'Start a new hire', text: 'Kick off hiring for a new team member.', icon: UserPlusIcon, accent: 'bg-sdx-blue' },
  ]
  return (
    <div className="space-y-6">
      <section className="relative overflow-hidden rounded-2xl bg-sdx-navy p-8 text-white">
        <svg viewBox="0 0 200 120" className="absolute -right-6 -top-4 h-48 opacity-25" aria-hidden="true">
          <polygon points="40,120 70,120 95,40 65,40" className="fill-sdx-blue" />
          <polygon points="90,120 120,120 155,10 125,10" className="fill-sdx-orange" />
          <polygon points="140,120 170,120 210,-20 180,-20" className="fill-sdx-red" />
        </svg>
        <p className="text-sm text-white/60">Good to see you</p>
        <h1 className="mt-1 text-3xl font-bold">Hi {user.name.split(' ')[0]}</h1>
        <p className="mt-2 text-white/70">
          {user.role} · {CLIENT}, Ghent office
        </p>
      </section>
      <div className="grid gap-4 sm:grid-cols-3">
        {tiles.map((t) => {
          const Icon = t.icon
          return (
            <button
              key={t.key}
              onClick={() => go(t.key)}
              className="group rounded-xl border border-sdx-navy/10 bg-white p-5 text-left shadow-sm transition hover:-translate-y-0.5 hover:shadow-md"
            >
              <span className={`mb-4 flex h-10 w-10 items-center justify-center rounded-lg ${t.accent} text-white`}>
                <Icon className="h-5 w-5" />
              </span>
              <div className="font-semibold">{t.title}</div>
              <div className="mt-1 text-sm text-sdx-navy/60">{t.text}</div>
              <div className="mt-4 text-sm font-medium text-sdx-red opacity-0 transition group-hover:opacity-100">Start →</div>
            </button>
          )
        })}
      </div>
    </div>
  )
}

function Card({ title, subtitle, children }) {
  return (
    <div className="rounded-2xl border border-sdx-navy/10 bg-white p-6 shadow-sm md:p-8">
      <h2 className="text-2xl font-bold">{title}</h2>
      {subtitle && <p className="mt-1 text-sm text-sdx-navy/60">{subtitle}</p>}
      <div className="mt-6">{children}</div>
    </div>
  )
}

function Field({ label, children }) {
  return (
    <label className="mb-5 block">
      <span className="mb-1.5 block text-sm font-medium text-sdx-navy/80">{label}</span>
      {children}
    </label>
  )
}

function Check({ checked, onChange, children }) {
  return (
    <label className="mb-5 flex cursor-pointer items-center gap-3 rounded-lg border border-sdx-navy/10 bg-sdx-sand/60 px-3 py-2.5 text-sm">
      <input type="checkbox" className="h-4 w-4 accent-sdx-red" checked={checked} onChange={onChange} />
      {children}
    </label>
  )
}

const input =
  'w-full rounded-lg border border-sdx-navy/15 bg-white px-3 py-2.5 transition focus:border-sdx-red focus:outline-none focus:ring-2 focus:ring-sdx-red/15'

function SubmitButton({ busy }) {
  return (
    <button
      disabled={busy}
      className="rounded-lg bg-sdx-red px-6 py-2.5 font-semibold text-white shadow-sm transition hover:bg-sdx-red-dark disabled:opacity-50"
    >
      {busy ? 'Submitting…' : 'Submit'}
    </button>
  )
}

function ErrorText({ error }) {
  return error ? <p className="mb-4 rounded-lg bg-sdx-red/10 px-3 py-2 text-sm text-sdx-red-dark">{error}</p> : null
}

function useSubmit(onSubmit) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  async function run(e, title, fields) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await onSubmit(title, fields)
    } catch (err) {
      setError(String(err.message || err))
      setBusy(false)
    }
  }
  return { busy, error, run }
}

function SickLeaveForm({ user, onSubmit }) {
  const [start, setStart] = useState(today())
  const [end, setEnd] = useState(today())
  const [note, setNote] = useState(null)
  const [informed, setInformed] = useState(false)
  const [comment, setComment] = useState('')
  const { busy, error, run } = useSubmit(onSubmit)

  const days = Math.max(1, Math.round((new Date(end) - new Date(start)) / 86400000) + 1)

  return (
    <Card title="Report sick leave" subtitle="Your manager and HR are notified when you submit.">
      <form
        onSubmit={(e) =>
          run(e, 'Sick leave report', {
            Type: 'Sick leave',
            Employee: user.name,
            'Start date': start,
            'Expected end date': end,
            Duration: `${days} day${days > 1 ? 's' : ''}`,
            "Doctor's note uploaded": note ? `Yes (${note.name})` : 'No',
            'Manager informed before 10:00': informed ? 'Yes' : 'No',
            Comment: comment || '-',
          })
        }
      >
        <div className="grid gap-x-4 sm:grid-cols-2">
          <Field label="First day of absence">
            <input type="date" className={input} value={start} onChange={(e) => setStart(e.target.value)} required />
          </Field>
          <Field label="Expected last day">
            <input type="date" className={input} value={end} min={start} onChange={(e) => setEnd(e.target.value)} required />
          </Field>
        </div>
        <p className="-mt-2 mb-5 text-sm text-sdx-navy/60">
          Duration: <span className="font-semibold text-sdx-navy">{days} day{days > 1 ? 's' : ''}</span>
        </p>
        <Field label="Doctor's note (optional)">
          <input
            type="file"
            className={`${input} file:mr-3 file:rounded-md file:border-0 file:bg-sdx-navy file:px-3 file:py-1 file:text-sm file:text-white`}
            onChange={(e) => setNote(e.target.files[0] || null)}
          />
        </Field>
        <Check checked={informed} onChange={(e) => setInformed(e.target.checked)}>
          I informed my manager before 10:00
        </Check>
        <Field label="Comment">
          <textarea className={input} rows={3} value={comment} onChange={(e) => setComment(e.target.value)} />
        </Field>
        <ErrorText error={error} />
        <SubmitButton busy={busy} />
      </form>
    </Card>
  )
}

function EquipmentForm({ user, onSubmit }) {
  const [code, setCode] = useState(CATALOGUE[0].code)
  const [other, setOther] = useState('')
  const [quantity, setQuantity] = useState(1)
  const [delivery, setDelivery] = useState('Home address')
  const [reason, setReason] = useState('')
  const { busy, error, run } = useSubmit(onSubmit)

  const item = CATALOGUE.find((c) => c.code === code)
  const isOther = code === 'OTHER'

  return (
    <Card title="Order equipment" subtitle="Catalogue items ship directly. Anything else needs IT approval.">
      <form
        onSubmit={(e) =>
          run(e, 'Equipment order', {
            Type: 'Equipment order',
            Employee: user.name,
            Item: isOther ? `${other} (not in catalogue)` : `${item.name} (catalogue item ${item.code})`,
            Quantity: quantity,
            Delivery: delivery,
            Reason: reason || '-',
            Status: isOther ? 'Waiting for IT approval' : 'Submitted',
          })
        }
      >
        <Field label="Item">
          <div className="grid gap-2 sm:grid-cols-2">
            {CATALOGUE.map((c) => (
              <button
                type="button"
                key={c.code}
                onClick={() => setCode(c.code)}
                className={`rounded-lg border px-3 py-2.5 text-left text-sm transition ${
                  code === c.code ? 'border-sdx-red bg-sdx-red/5 font-medium' : 'border-sdx-navy/15 hover:border-sdx-navy/30'
                }`}
              >
                {c.name}
                <span className="ml-2 text-xs text-sdx-navy/40">{c.code !== 'OTHER' && c.code}</span>
              </button>
            ))}
          </div>
        </Field>
        {isOther && (
          <Field label="Describe the item (and link if you have one)">
            <input className={input} value={other} onChange={(e) => setOther(e.target.value)} required />
          </Field>
        )}
        <div className="grid gap-x-4 sm:grid-cols-2">
          <Field label="Quantity">
            <input type="number" min={1} max={5} className={input} value={quantity} onChange={(e) => setQuantity(e.target.value)} />
          </Field>
          <Field label="Delivery">
            <select className={input} value={delivery} onChange={(e) => setDelivery(e.target.value)}>
              <option>Home address</option>
              <option>Ghent office</option>
            </select>
          </Field>
        </div>
        <Field label="Reason">
          <textarea className={input} rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
        <ErrorText error={error} />
        <SubmitButton busy={busy} />
      </form>
    </Card>
  )
}

function NewHireForm({ user, onSubmit }) {
  const [role, setRole] = useState('')
  const [nonEu, setNonEu] = useState(false)
  const [country, setCountry] = useState('')
  const [startDate, setStartDate] = useState('')
  const [status, setStatus] = useState('Offer accepted')
  const { busy, error, run } = useSubmit(onSubmit)

  return (
    <Card title="Start a new hire" subtitle="HR picks up the request and guides you through the next steps.">
      <form
        onSubmit={(e) =>
          run(e, `New hire request - ${role}`, {
            Type: 'New hire',
            'Hiring manager': user.name,
            Role: role,
            'Candidate nationality': nonEu ? `Non-EU (${country})` : 'EU/EEA',
            'Planned start date': startDate,
            'Needs work permit': nonEu ? 'Yes' : 'No',
            Status: status,
          })
        }
      >
        <Field label="Role">
          <input className={input} value={role} onChange={(e) => setRole(e.target.value)} placeholder="e.g. Senior Data Engineer" required />
        </Field>
        <Check checked={nonEu} onChange={(e) => setNonEu(e.target.checked)}>
          Candidate is not an EU/EEA citizen
        </Check>
        {nonEu && (
          <Field label="Candidate's country of citizenship">
            <input className={input} value={country} onChange={(e) => setCountry(e.target.value)} required />
          </Field>
        )}
        <div className="grid gap-x-4 sm:grid-cols-2">
          <Field label="Planned start date">
            <input type="date" className={input} value={startDate} onChange={(e) => setStartDate(e.target.value)} required />
          </Field>
          <Field label="Status">
            <select className={input} value={status} onChange={(e) => setStatus(e.target.value)}>
              <option>Offer accepted</option>
              <option>Documents collected</option>
              <option>Waiting for HR</option>
            </select>
          </Field>
        </div>
        <ErrorText error={error} />
        <SubmitButton busy={busy} />
      </form>
    </Card>
  )
}

const TYPE_STYLES = {
  'Sick leave': 'bg-sdx-red/10 text-sdx-red-dark',
  'Equipment order': 'bg-sdx-orange/15 text-[#9a5c00]',
  'New hire': 'bg-sdx-blue/10 text-[#006a99]',
}

function ticketType(t) {
  return t.body.match(/^Type: (.*)$/m)?.[1] ?? 'Request'
}

function Requests({ highlight }) {
  const [tickets, setTickets] = useState(null)

  useEffect(() => {
    fetch('/api/tickets')
      .then((r) => r.json())
      .then(setTickets)
  }, [])

  return (
    <Card title="My requests" subtitle="Everything submitted through the portal.">
      {tickets === null && <p className="text-sdx-navy/50">Loading…</p>}
      {tickets?.length === 0 && <p className="text-sdx-navy/50">No requests yet.</p>}
      <ul className="space-y-3">
        {tickets?.map((t) => {
          const type = ticketType(t)
          return (
            <li
              key={t.id}
              className={`rounded-xl border p-4 transition ${
                t.id === highlight ? 'border-sdx-red/40 bg-sdx-red/5 ring-2 ring-sdx-red/10' : 'border-sdx-navy/10'
              }`}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${TYPE_STYLES[type] ?? 'bg-sdx-navy/10'}`}>
                    {type}
                  </span>
                  <span className="font-semibold">{t.title}</span>
                </div>
                <span className="text-xs text-sdx-navy/40">
                  {t.id} · {new Date(t.timestamp).toLocaleString()}
                </span>
              </div>
              {t.id === highlight && <p className="mt-1 text-sm font-medium text-sdx-red">Submitted just now</p>}
              <dl className="mt-3 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
                {t.body
                  .split('\n')
                  .filter((line) => line.includes(': ') && !line.startsWith('Type:'))
                  .map((line) => {
                    const [k, ...v] = line.split(': ')
                    return (
                      <div key={k} className="flex gap-2">
                        <dt className="text-sdx-navy/50">{k}</dt>
                        <dd className="font-medium">{v.join(': ')}</dd>
                      </div>
                    )
                  })}
              </dl>
            </li>
          )
        })}
      </ul>
    </Card>
  )
}

// small inline icons (no icon dependency)
function HomeIcon(props) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z" />
    </svg>
  )
}
function HeartIcon(props) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M20.8 5.6a5.5 5.5 0 0 0-7.8 0L12 6.6l-1-1a5.5 5.5 0 0 0-7.8 7.8l1 1L12 22l7.8-7.6 1-1a5.5 5.5 0 0 0 0-7.8z" />
    </svg>
  )
}
function BoxIcon(props) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M21 8 12 3 3 8v8l9 5 9-5z" />
      <path d="m3 8 9 5 9-5M12 13v8" />
    </svg>
  )
}
function UserPlusIcon(props) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <circle cx="9" cy="8" r="4" />
      <path d="M2 21a7 7 0 0 1 14 0M19 8v6M16 11h6" />
    </svg>
  )
}
function ListIcon(props) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" />
    </svg>
  )
}
