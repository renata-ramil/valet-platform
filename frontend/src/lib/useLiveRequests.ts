import { useEffect, useRef } from "react"
import { baseUrl } from "./apiClient"
import type { CarRequest } from "./apiClient"

function useSSE(path: string, onMessage: (data: unknown) => void, enabled: boolean) {
  const handlerRef = useRef(onMessage)

  useEffect(() => {
    handlerRef.current = onMessage
  }, [onMessage])

  useEffect(() => {
    if (!enabled) {
      return
    }
    const source = new EventSource(`${baseUrl}${path}`, { withCredentials: true })
    const handleMessage = (event: MessageEvent) => {
      handlerRef.current(JSON.parse(event.data))
    }
    source.addEventListener("request_update", handleMessage)
    return () => {
      source.removeEventListener("request_update", handleMessage)
      source.close()
    }
  }, [enabled, path])
}

export function useLiveRequests(onUpdate: (request: CarRequest) => void, enabled: boolean) {
  useSSE("/events", onUpdate as (data: unknown) => void, enabled)
}

export function useLiveBuildingEvents(onUpdate: (request: CarRequest) => void, enabled: boolean) {
  useSSE("/events/building", onUpdate as (data: unknown) => void, enabled)
}
