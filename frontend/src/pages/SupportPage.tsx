import { useRef, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import * as api from "../lib/apiClient"
import { useAuth } from "../context/AuthContext"
import { Icon } from "../components/Icon"
import { ResidentTabbar } from "../components/ResidentTabbar"
import type { ResidentTab } from "../components/ResidentTabbar"
import { TopbarBack } from "../components/PhoneFrame"

interface ChatMessage {
  role: "user" | "assistant"
  content: string
}

function AssistantChat({ csrf }: { csrf: string }) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState("")
  const [streaming, setStreaming] = useState("")
  const [sending, setSending] = useState(false)
  const [proposal, setProposal] = useState<api.SupportChatDone["proposal"]>(null)
  const [escalated, setEscalated] = useState<string | null>(null)
  const historyRef = useRef<{ role: string; content: string }[]>([])

  const send = async () => {
    if (!input.trim() || sending) return
    const userText = input
    setInput("")
    setStreaming("")
    setProposal(null)
    setMessages((prev) => [...prev, { role: "user", content: userText }])
    setSending(true)
    try {
      let acc = ""
      const done = await api.streamSupportChat(csrf, userText, historyRef.current, (chunk) => {
        acc += chunk
        setStreaming(acc)
      })
      historyRef.current = [
        ...historyRef.current,
        { role: "user", content: userText },
        { role: "assistant", content: done.reply },
      ]
      setMessages((prev) => [...prev, { role: "assistant", content: done.reply }])
      setStreaming("")
      if (done.proposal) setProposal(done.proposal)
    } finally {
      setSending(false)
    }
  }

  const confirmProposal = async () => {
    if (!proposal) return
    const result = await api.confirmSupportReschedule(csrf, proposal.proposal_id, proposal.confirmation_token)
    setMessages((prev) => [...prev, { role: "assistant", content: result.reply }])
    setProposal(null)
  }

  const talkToPerson = useMutation({
    mutationFn: () => {
      const transcript = messages.map((m) => `${m.role}: ${m.content}`).join("\n")
      return api.createTicket(csrf, {
        subject: "Escalated from support chat",
        message: transcript || "Resident asked to talk to a person.",
      })
    },
    onSuccess: (ticket) => setEscalated(ticket.id),
  })

  return (
    <>
      <div className="row between g2" style={{ minHeight: 48 }}>
        <div className="row g2 grow">
          <Icon name="chat" />
          <span className="t14 w7">Automated assistant</span>
        </div>
        <button
          type="button"
          className="btn btn-secondary none"
          style={{ padding: "0 var(--sp-3)" }}
          data-testid="talk-to-person-button"
          onClick={() => talkToPerson.mutate()}
        >
          Talk to a person
        </button>
      </div>

      {escalated && <p className="t14 c-ink2" data-testid="escalated-notice">Ticket opened, a person will follow up.</p>}

      <div className="msgs grow" style={{ justifyContent: "flex-end", overflowY: "auto" }}>
        {messages.map((m, i) => (
          <div
            key={i}
            data-testid={m.role === "user" ? "chat-user-message" : "chat-assistant-message"}
            className={m.role === "user" ? "bub bub-me" : "bub bub-bot bub-wide"}
          >
            {m.role === "assistant" && <div className="bub-who">Automated assistant</div>}
            {m.content}
          </div>
        ))}
        {streaming && (
          <div className="bub bub-bot bub-wide" data-testid="chat-streaming-message">
            {streaming}
          </div>
        )}
        {proposal && (
          <section className="confirm" aria-label="Review the change" data-testid="reschedule-confirm-card">
            <div className="t20 w7">{proposal.description}</div>
            <div className="row g2">
              <button type="button" className="btn btn-primary grow" data-testid="confirm-proposal-button" onClick={confirmProposal}>
                Confirm
              </button>
              <button type="button" className="btn btn-secondary grow" onClick={() => setProposal(null)}>
                Cancel
              </button>
            </div>
          </section>
        )}
      </div>

      <div className="row g2">
        <input
          className="inp grow"
          data-testid="chat-input"
          placeholder="Write a message"
          aria-label="Write a message"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
        />
        <button
          className="btn btn-primary ibtn"
          type="button"
          aria-label="Send message"
          data-testid="chat-send-button"
          disabled={sending || !input.trim()}
          onClick={send}
        >
          <Icon name="arrow" />
        </button>
      </div>
    </>
  )
}

function TicketThread({
  ticketId,
  onBack,
  isStaff,
}: {
  ticketId: string
  onBack: () => void
  isStaff: boolean
}) {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const [reply, setReply] = useState("")
  const ticketQuery = useQuery({ queryKey: ["ticket", ticketId], queryFn: () => api.getTicket(ticketId) })
  const ticket = ticketQuery.data

  const sendReply = useMutation({
    mutationFn: () => api.addTicketMessage(user!.csrf_token, ticketId, reply),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ticket", ticketId] })
      queryClient.invalidateQueries({ queryKey: ["tickets"] })
      setReply("")
    },
  })
  const resolve = useMutation({
    mutationFn: () => api.updateTicketStatus(user!.csrf_token, ticketId, "resolved"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ticket", ticketId] })
      queryClient.invalidateQueries({ queryKey: ["tickets"] })
    },
  })

  if (!ticket) return null

  return (
    <>
      <TopbarBack title={`Ticket ${ticket.id.slice(0, 8)}`} onBack={onBack} />
      <main className="pbody col g3" data-testid="ticket-thread">
        <div className="col g1">
          <h1 className="t20 w7">{ticket.subject}</h1>
          <p className="t16 w7 c-called">{ticket.status}</p>
        </div>
        <div className="msgs grow" style={{ overflowY: "auto" }}>
          {ticket.messages.map((m) => (
            <div className="bub bub-staff bub-wide" key={m.id}>
              <div className="bub-who">{new Date(m.created_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</div>
              {m.body}
            </div>
          ))}
        </div>
        <div className="col g2">
          {isStaff && ticket.status !== "resolved" && (
            <button className="btn btn-quiet btn-block" type="button" data-testid="resolve-button" onClick={() => resolve.mutate()}>
              Mark as resolved
            </button>
          )}
          <div className="row g2">
            <input
              className="inp grow"
              data-testid="reply-input"
              placeholder="Write a reply"
              aria-label="Write a reply"
              value={reply}
              onChange={(e) => setReply(e.target.value)}
            />
            <button
              className="btn btn-primary ibtn"
              type="button"
              aria-label="Send reply"
              data-testid="send-reply-button"
              disabled={!reply || sendReply.isPending}
              onClick={() => sendReply.mutate()}
            >
              <Icon name="arrow" />
            </button>
          </div>
        </div>
      </main>
    </>
  )
}

function TicketsList({ onOpen }: { onOpen: (id: string) => void }) {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const ticketsQuery = useQuery({ queryKey: ["tickets"], queryFn: api.listTickets })
  const [composing, setComposing] = useState(false)
  const [subject, setSubject] = useState("")
  const [message, setMessage] = useState("")

  const createTicket = useMutation({
    mutationFn: () => api.createTicket(user!.csrf_token, { subject, message }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tickets"] })
      setSubject("")
      setMessage("")
      setComposing(false)
    },
  })

  const tickets = ticketsQuery.data ?? []
  const open = tickets.filter((t) => t.status !== "resolved")
  const closed = tickets.filter((t) => t.status === "resolved")

  return (
    <>
      {composing ? (
        <div className="col g3">
          <div className="field">
            <label className="lbl" htmlFor="subject">Subject</label>
            <input className="inp" id="subject" data-testid="ticket-subject-input" value={subject} onChange={(e) => setSubject(e.target.value)} />
          </div>
          <div className="field">
            <label className="lbl" htmlFor="msg">Message</label>
            <input className="inp" id="msg" data-testid="ticket-message-input" value={message} onChange={(e) => setMessage(e.target.value)} />
          </div>
          <button
            className="btn btn-primary btn-block"
            type="button"
            data-testid="create-ticket-button"
            disabled={!subject || !message || createTicket.isPending}
            onClick={() => createTicket.mutate()}
          >
            Open ticket
          </button>
        </div>
      ) : (
        <button className="btn btn-secondary btn-block" type="button" onClick={() => setComposing(true)}>
          <Icon name="plus" />
          New ticket
        </button>
      )}

      <section className="col g2" aria-label="Open tickets">
        <h2 className="t14 w7 c-ink2">Open</h2>
        {open.map((t) => (
          <button
            key={t.id}
            type="button"
            className="card card-btn row g3"
            style={{ minHeight: 64, width: "100%", textAlign: "left" }}
            data-testid="ticket-row"
            onClick={() => onOpen(t.id)}
          >
            <div className="col g1 grow">
              <span className="t16 w7">{t.subject}</span>
              <span className="t16 w7 c-called">{t.status === "waiting" ? "Waiting" : "Open"}</span>
            </div>
            <Icon name="arrow" />
          </button>
        ))}
        {open.length === 0 && <p className="t14 c-ink2">No open tickets.</p>}
      </section>

      <section className="col g2" aria-label="Closed tickets">
        <h2 className="t14 w7 c-ink2">Closed</h2>
        {closed.map((t) => (
          <button
            key={t.id}
            type="button"
            className="card card-btn row g3"
            style={{ minHeight: 64, width: "100%", textAlign: "left" }}
            onClick={() => onOpen(t.id)}
          >
            <div className="col g1 grow">
              <span className="t16 w7">{t.subject}</span>
              <span className="t14 c-ink2">Closed</span>
            </div>
            <Icon name="arrow" />
          </button>
        ))}
        {closed.length === 0 && <p className="t14 c-ink2">No closed tickets.</p>}
      </section>
    </>
  )
}

export function SupportPage({ onNavigate }: { onNavigate?: (tab: ResidentTab) => void }) {
  const { user } = useAuth()
  const isStaff = user?.role === "manager" || user?.role === "support"
  const [view, setView] = useState<"assistant" | "tickets">(isStaff ? "tickets" : "assistant")
  const [openTicket, setOpenTicket] = useState<string | null>(null)

  if (openTicket) {
    return <TicketThread ticketId={openTicket} onBack={() => setOpenTicket(null)} isStaff={isStaff} />
  }

  return (
    <>
      <header className="topbar">
        <div className="ttl">Support</div>
      </header>
      <main className="pbody col g3" data-testid="support-page">
        {!isStaff && (
          <div className="seg" role="tablist" aria-label="Support views">
            <button className={`seg-i${view === "assistant" ? " on" : ""}`} role="tab" aria-selected={view === "assistant"} type="button" onClick={() => setView("assistant")}>
              Assistant
            </button>
            <button className={`seg-i${view === "tickets" ? " on" : ""}`} role="tab" aria-selected={view === "tickets"} type="button" onClick={() => setView("tickets")}>
              Tickets
            </button>
          </div>
        )}
        {isStaff || view === "tickets" ? (
          <TicketsList onOpen={setOpenTicket} />
        ) : (
          <AssistantChat csrf={user!.csrf_token} />
        )}
      </main>
      {!isStaff && onNavigate && <ResidentTabbar active="help" onChange={onNavigate} />}
    </>
  )
}
