import { useEffect, useState } from 'react'

const EMPLOYEES = [
  { name: 'Lucas Maes', email: 'lucas.maes@lumivia.be', role: 'Software Engineer' },
  { name: 'Nina Wouters', email: 'nina.wouters@lumivia.be', role: 'Product Designer' },
  { name: 'Jonas Mertens', email: 'jonas.mertens@lumivia.be', role: 'Account Executive' },
  { name: 'Pieter Janssens', email: 'pieter.janssens@lumivia.be', role: 'Engineering Manager' },
  { name: 'Amira Haddad', email: 'amira.haddad@lumivia.be', role: 'Sales Manager' },
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
  { key: 'home', label: 'Home' },
  { key: 'sick', label: 'Report sick leave' },
  { key: 'equipment', label: 'Order equipment' },
  { key: 'hire', label: 'Start a new hire' },
  { key: 'requests', label: 'All requests' },
]

const today = () => new Date().toISOString().slice(0, 10)

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
    <div className="min-h-screen bg-slate-50 text-slate-800">
      <header className="bg-indigo-700 text-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-md bg-white font-bold text-indigo-700">L</div>
            <span className="text-lg font-semibold">Lumivia Employee Portal</span>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <span className="text-indigo-200">Signed in as</span>
            <select
              className="rounded bg-indigo-600 px-2 py-1 text-white"
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

      <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-6 md:flex-row">
        <nav className="flex gap-1 overflow-x-auto md:w-52 md:flex-col">
          {PAGES.map((p) => (
            <button
              key={p.key}
              onClick={() => setPage(p.key)}
              className={`whitespace-nowrap rounded-md px-3 py-2 text-left text-sm ${
                page === p.key ? 'bg-indigo-100 font-medium text-indigo-800' : 'hover:bg-slate-200'
              }`}
            >
              {p.label}
            </button>
          ))}
        </nav>

        <main className="flex-1">
          {page === 'home' && <Home user={user} go={setPage} />}
          {page === 'sick' && <SickLeaveForm user={user} onSubmit={submit} />}
          {page === 'equipment' && <EquipmentForm user={user} onSubmit={submit} />}
          {page === 'hire' && <NewHireForm user={user} onSubmit={submit} />}
          {page === 'requests' && <Requests highlight={lastTicket?.id} />}
        </main>
      </div>
    </div>
  )
}

function Home({ user, go }) {
  const tiles = [
    { key: 'sick', title: 'Report sick leave', text: 'Let your manager and HR know you are ill.' },
    { key: 'equipment', title: 'Order equipment', text: 'Monitors, keyboards, headsets and more.' },
    { key: 'hire', title: 'Start a new hire', text: 'Kick off hiring for a new team member.' },
  ]
  return (
    <div>
      <h1 className="text-2xl font-semibold">Hi {user.name.split(' ')[0]}</h1>
      <p className="mt-1 text-slate-500">{user.role} · Ghent office</p>
      <div className="mt-6 grid gap-4 sm:grid-cols-3">
        {tiles.map((t) => (
          <button
            key={t.key}
            onClick={() => go(t.key)}
            className="rounded-lg border border-slate-200 bg-white p-4 text-left shadow-sm hover:border-indigo-400"
          >
            <div className="font-medium">{t.title}</div>
            <div className="mt-1 text-sm text-slate-500">{t.text}</div>
          </button>
        ))}
      </div>
    </div>
  )
}

function Card({ title, children }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="mb-4 text-xl font-semibold">{title}</h2>
      {children}
    </div>
  )
}

function Field({ label, children }) {
  return (
    <label className="mb-4 block">
      <span className="mb-1 block text-sm font-medium text-slate-600">{label}</span>
      {children}
    </label>
  )
}

const input = 'w-full rounded-md border border-slate-300 px-3 py-2 focus:border-indigo-500 focus:outline-none'

function SubmitButton({ busy }) {
  return (
    <button
      disabled={busy}
      className="rounded-md bg-indigo-600 px-4 py-2 font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
    >
      {busy ? 'Submitting…' : 'Submit'}
    </button>
  )
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
    <Card title="Report sick leave">
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
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="First day of absence">
            <input type="date" className={input} value={start} onChange={(e) => setStart(e.target.value)} required />
          </Field>
          <Field label="Expected last day">
            <input type="date" className={input} value={end} min={start} onChange={(e) => setEnd(e.target.value)} required />
          </Field>
        </div>
        <Field label="Doctor's note (optional)">
          <input type="file" className={input} onChange={(e) => setNote(e.target.files[0] || null)} />
        </Field>
        <label className="mb-4 flex items-center gap-2 text-sm">
          <input type="checkbox" checked={informed} onChange={(e) => setInformed(e.target.checked)} />
          I informed my manager before 10:00
        </label>
        <Field label="Comment">
          <textarea className={input} rows={3} value={comment} onChange={(e) => setComment(e.target.value)} />
        </Field>
        {error && <p className="mb-3 text-sm text-red-600">{error}</p>}
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
    <Card title="Order equipment">
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
          <select className={input} value={code} onChange={(e) => setCode(e.target.value)}>
            {CATALOGUE.map((c) => (
              <option key={c.code} value={c.code}>
                {c.name}
              </option>
            ))}
          </select>
        </Field>
        {isOther && (
          <Field label="Describe the item (and link if you have one)">
            <input className={input} value={other} onChange={(e) => setOther(e.target.value)} required />
          </Field>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
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
        {error && <p className="mb-3 text-sm text-red-600">{error}</p>}
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
    <Card title="Start a new hire">
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
          <input className={input} value={role} onChange={(e) => setRole(e.target.value)} required />
        </Field>
        <label className="mb-4 flex items-center gap-2 text-sm">
          <input type="checkbox" checked={nonEu} onChange={(e) => setNonEu(e.target.checked)} />
          Candidate is not an EU/EEA citizen
        </label>
        {nonEu && (
          <Field label="Candidate's country of citizenship">
            <input className={input} value={country} onChange={(e) => setCountry(e.target.value)} required />
          </Field>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
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
        {error && <p className="mb-3 text-sm text-red-600">{error}</p>}
        <SubmitButton busy={busy} />
      </form>
    </Card>
  )
}

function Requests({ highlight }) {
  const [tickets, setTickets] = useState(null)

  useEffect(() => {
    fetch('/api/tickets')
      .then((r) => r.json())
      .then(setTickets)
  }, [])

  return (
    <Card title="All requests">
      {tickets === null && <p className="text-slate-500">Loading…</p>}
      {tickets?.length === 0 && <p className="text-slate-500">No requests yet.</p>}
      <ul className="space-y-3">
        {tickets?.map((t) => (
          <li
            key={t.id}
            className={`rounded-md border p-4 ${t.id === highlight ? 'border-green-400 bg-green-50' : 'border-slate-200'}`}
          >
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="font-medium">{t.title}</span>
              <span className="text-xs text-slate-500">
                {t.id} · {new Date(t.timestamp).toLocaleString()}
              </span>
            </div>
            {t.id === highlight && <p className="mt-1 text-sm text-green-700">Submitted</p>}
            <pre className="mt-2 whitespace-pre-wrap font-sans text-sm text-slate-600">{t.body}</pre>
          </li>
        ))}
      </ul>
    </Card>
  )
}
