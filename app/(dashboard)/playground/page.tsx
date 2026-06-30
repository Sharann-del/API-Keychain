"use client";

import * as React from "react";
import { Loader2, Send } from "lucide-react";
import { toast } from "sonner";

import { useAuth } from "@/lib/auth";
import { api, useApi, API_BASE_URL, ApiError } from "@/lib/api";
import { loadPrimaryKey } from "@/lib/keystore";
import { PROVIDER_SLUGS, TIER_LABELS } from "@/lib/catalog";
import { providerLabel, cn } from "@/lib/utils";
import type {
  Effort,
  ListKeychainKeysResponse,
  ListProviderKeysResponse,
  PreferencesResponse,
} from "@/lib/types";
import { PageHeader } from "@/components/page-header";
import { ChatMarkdown } from "@/components/chat-markdown";
import { StreamingIndicator } from "@/components/streaming-indicator";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

type AttemptStatus = "served" | "error" | "skipped";

interface RoutingAttempt {
  provider: string;
  model: string;
  status: AttemptStatus;
  code: number | null;
}

interface RoutingPayload {
  tier: string;
  attempted: RoutingAttempt[];
  served: { provider: string; model: string };
}

interface DonePayload {
  latency_ms: number;
}

interface MessageRouting {
  tier?: string;
  attempted: RoutingAttempt[];
  served?: { provider: string; model: string };
  latency_ms?: number;
  streaming: boolean;
}

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  routing?: MessageRouting;
}

const PLAYGROUND_KEY_STORAGE = "ak_playground_key";

function playgroundKeyStorageKey(userId: string): string {
  return `${PLAYGROUND_KEY_STORAGE}_${userId}`;
}

function shortModelLabel(model: string): string {
  const slash = model.indexOf("/");
  return slash >= 0 ? model.slice(slash + 1) : model;
}

function badgeVariant(
  status: AttemptStatus
): "success" | "danger" | "muted" {
  if (status === "served") return "success";
  if (status === "error") return "danger";
  return "muted";
}

/** Merge excluded (kill-switch) providers into the strip as grey skipped badges. */
function displayAttempts(
  attempted: RoutingAttempt[],
  excludedProviders: string[]
): RoutingAttempt[] {
  const seen = new Set(attempted.map((a) => a.provider));
  const extras: RoutingAttempt[] = excludedProviders
    .filter((p) => !seen.has(p))
    .map((provider) => ({
      provider,
      model: `${provider}/*`,
      status: "skipped" as const,
      code: null,
    }));
  return [...extras, ...attempted];
}

function RoutingStrip({
  routing,
  excludedProviders,
}: {
  routing: MessageRouting;
  excludedProviders: string[];
}) {
  const rows = displayAttempts(routing.attempted, excludedProviders);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted-foreground">Tier</span>
        <Badge variant="outline">{routing.tier ?? "—"}</Badge>
        {routing.latency_ms != null && (
          <>
            <span className="text-xs text-muted-foreground">Latency</span>
            <Badge variant="outline" className="font-mono tabular-nums">
              {routing.latency_ms} ms
            </Badge>
          </>
        )}
        {routing.streaming && (
          <Badge variant="outline" className="animate-status">
            streaming
          </Badge>
        )}
      </div>

      {rows.length === 0 && routing.tier == null ? (
        <p className="text-sm text-muted-foreground">Waiting for routing…</p>
      ) : rows.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {rows.map((a, i) => (
            <Badge
              key={`${a.provider}-${a.model}-${i}`}
              variant={badgeVariant(a.status)}
              className="max-w-full font-mono text-[0.65rem]"
              title={a.model}
            >
              <span className="truncate">
                {providerLabel(a.provider)} / {shortModelLabel(a.model)}
              </span>
              {a.status === "error" && a.code != null && (
                <span className="opacity-90">· {a.code}</span>
              )}
              {a.status === "skipped" && (
                <span className="opacity-70">· skipped</span>
              )}
            </Badge>
          ))}
        </div>
      ) : null}

      {routing.served && (
        <p className="font-mono text-xs text-muted-foreground">
          Served{" "}
          <span className="text-foreground">
            {routing.served.provider}/{shortModelLabel(routing.served.model)}
          </span>
        </p>
      )}
    </div>
  );
}

export default function PlaygroundPage() {
  const { userId, ready } = useAuth();
  const enabled = Boolean(userId && ready);

  const { data: keysData } = useApi<ListKeychainKeysResponse>(
    enabled ? `/users/${userId}/keychain-keys` : null
  );
  const { data: providerKeysData } = useApi<ListProviderKeysResponse>(
    enabled ? `/users/${userId}/keys` : null
  );
  const { data: prefsData, mutate: mutatePrefs } = useApi<PreferencesResponse>(
    enabled ? `/users/${userId}/preferences` : null
  );

  const [effort, setEffort] = React.useState<Effort>("medium");
  const [keyMode, setKeyMode] = React.useState<"cached" | "custom">("cached");
  const [customKey, setCustomKey] = React.useState("");
  const [cachedKey, setCachedKey] = React.useState<string | null>(null);
  const [input, setInput] = React.useState("");
  const [messages, setMessages] = React.useState<ChatMessage[]>([]);
  const [sending, setSending] = React.useState(false);
  const [excludedProviders, setExcludedProviders] = React.useState<string[]>(
    []
  );
  const [prefsHydrated, setPrefsHydrated] = React.useState(false);
  const [togglingProvider, setTogglingProvider] = React.useState<
    string | null
  >(null);

  const abortRef = React.useRef<AbortController | null>(null);
  const chatScrollRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (!userId) return;
    setCachedKey(loadPrimaryKey(userId));
    try {
      const stored = window.localStorage.getItem(playgroundKeyStorageKey(userId));
      if (stored) {
        setCustomKey(stored);
        setKeyMode("custom");
      }
    } catch {
      /* ignore */
    }
  }, [userId]);

  React.useEffect(() => {
    if (prefsData && !prefsHydrated) {
      setExcludedProviders(prefsData.excluded_providers ?? []);
      setPrefsHydrated(true);
    }
  }, [prefsData, prefsHydrated]);

  React.useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  React.useEffect(() => {
    if (messages.length === 0) return;
    const el = chatScrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: sending ? "auto" : "smooth" });
  }, [messages, sending]);

  const connectedProviders = React.useMemo(() => {
    const fromKeys = new Set(providerKeysData?.providers ?? []);
    return PROVIDER_SLUGS.filter((p) => fromKeys.has(p));
  }, [providerKeysData]);

  const activeKey = keyMode === "custom" ? customKey.trim() : cachedKey;

  const assistantMessages = React.useMemo(
    () => messages.filter((m) => m.role === "assistant" && m.routing),
    [messages]
  );

  const persistCustomKey = (value: string) => {
    setCustomKey(value);
    if (!userId) return;
    try {
      if (value.trim()) {
        window.localStorage.setItem(
          playgroundKeyStorageKey(userId),
          value.trim()
        );
      } else {
        window.localStorage.removeItem(playgroundKeyStorageKey(userId));
      }
    } catch {
      /* ignore */
    }
  };

  const setProviderEnabled = async (provider: string, enabled: boolean) => {
    if (!userId || !prefsData) return;
    setTogglingProvider(provider);

    const nextExcluded = enabled
      ? excludedProviders.filter((p) => p !== provider)
      : Array.from(new Set([...excludedProviders, provider]));

    const body = {
      preferred_providers: prefsData.preferred_providers ?? [],
      excluded_providers: nextExcluded,
      excluded_models: prefsData.excluded_models ?? [],
    };

    try {
      await api.put(`/users/${userId}/preferences`, body);
      setExcludedProviders(nextExcluded);
      void mutatePrefs();
      toast.success(
        enabled
          ? `${providerLabel(provider)} enabled for routing`
          : `${providerLabel(provider)} excluded — next request will failover`
      );
    } catch (err) {
      toast.error(
        err instanceof ApiError ? err.message : "Failed to update preferences"
      );
    } finally {
      setTogglingProvider(null);
    }
  };

  const sendMessage = async () => {
    const text = input.trim();
    if (!text || sending) return;
    if (!activeKey?.startsWith("ak-")) {
      toast.error("Select or paste a valid ak- keychain key");
      return;
    }

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const userMsgId = `u-${Date.now()}`;
    const flightId = `a-${Date.now()}`;

    setMessages((prev) => [
      ...prev,
      { id: userMsgId, role: "user", content: text },
      {
        id: flightId,
        role: "assistant",
        content: "",
        routing: { attempted: [], streaming: true },
      },
    ]);
    setInput("");
    setSending(true);

    // --- state writers, always targeting the in-flight assistant message ---
    const setRouting = (patch: Partial<MessageRouting>) =>
      setMessages((prev) =>
        prev.map((m) =>
          m.id === flightId
            ? {
                ...m,
                routing: {
                  ...(m.routing ?? { attempted: [], streaming: true }),
                  ...patch,
                },
              }
            : m
        )
      );

    const appendToken = (delta: string) =>
      setMessages((prev) =>
        prev.map((m) =>
          m.id === flightId ? { ...m, content: m.content + delta } : m
        )
      );

    const streamStarted = performance.now();
    let routingFromStream = false;

    // --- dispatch one fully-assembled SSE frame ---
    const handleFrame = (eventName: string, data: string) => {
      if (data === "[DONE]") return;

      let json: unknown;
      try {
        json = JSON.parse(data);
      } catch {
        return; // not JSON — ignore
      }
      const obj = json as Record<string, unknown>;

      // routing (by event name, or by shape if the event line was lost)
      if (
        eventName === "routing" ||
        (typeof obj?.tier === "string" && Array.isArray(obj?.attempted))
      ) {
        const p = obj as unknown as RoutingPayload;
        routingFromStream = true;
        setRouting({
          tier: p.tier,
          attempted: p.attempted,
          served: p.served,
        });
        return;
      }

      // done (by event name, or by shape)
      if (eventName === "done" || typeof obj?.latency_ms === "number") {
        const p = obj as unknown as DonePayload;
        setRouting({ latency_ms: p.latency_ms });
        return;
      }

      // default token frame: append choices[0].delta.content (skip if no delta)
      const choices = obj?.choices as
        | Array<{ delta?: { content?: string } }>
        | undefined;
      const piece = choices?.[0]?.delta?.content;
      if (typeof piece === "string" && piece.length > 0) appendToken(piece);
    };

    // --- parse a raw frame block: read `event:` line, join `data:` lines ---
    const dispatchRawFrame = (raw: string) => {
      let eventName = "";
      const dataParts: string[] = [];
      for (const line of raw.replace(/\r/g, "").split("\n")) {
        if (line.startsWith("event:")) {
          eventName = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          dataParts.push(line.slice(5).replace(/^ /, ""));
        }
      }
      if (dataParts.length > 0) handleFrame(eventName, dataParts.join("\n"));
    };

    try {
      const res = await fetch(`${API_BASE_URL}/v1/chat/completions`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${activeKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          model: `keychain-${effort}`,
          effort,
          stream: true,
          messages: [{ role: "user", content: text }],
        }),
        signal: controller.signal,
      });

      if (!res.ok) {
        let message = `Request failed (${res.status})`;
        try {
          const errBody = await res.json();
          if (errBody?.error?.message) message = errBody.error.message;
        } catch {
          /* ignore */
        }
        if (
          res.status === 401 &&
          /invalid or revoked/i.test(message) &&
          keyMode === "cached"
        ) {
          message =
            "Invalid or revoked API key. Your saved key may be from local development — regenerate it in Settings, or paste a production ak- key above.";
        }
        throw new Error(message);
      }

      if (!res.body) throw new Error("No response body");

      const headerProvider = res.headers.get("X-Keychain-Provider");
      const headerModel = res.headers.get("X-Keychain-Model");
      if (headerProvider && headerModel && !routingFromStream) {
        setRouting({
          tier: effort,
          attempted: [
            {
              provider: headerProvider,
              model: headerModel,
              status: "served",
              code: 200,
            },
          ],
          served: { provider: headerProvider, model: headerModel },
        });
      }

      // Read the ReadableStream, decode to a text buffer, split frames on "\n\n".
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let sep: number;
        while ((sep = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          if (frame.trim()) dispatchRawFrame(frame);
        }
      }

      // Flush any trailing frame that wasn't terminated by a blank line.
      buffer += decoder.decode();
      if (buffer.trim()) dispatchRawFrame(buffer);

      if (!routingFromStream && headerProvider && headerModel) {
        setRouting({
          tier: effort,
          latency_ms: Math.round(performance.now() - streamStarted),
        });
      }

      setRouting({ streaming: false });
    } catch (err) {
      if (controller.signal.aborted) return;
      const message =
        err instanceof Error ? err.message : "Streaming request failed";
      setMessages((prev) =>
        prev.map((m) =>
          m.id === flightId
            ? {
                ...m,
                content: message,
                routing: { attempted: [], streaming: false },
              }
            : m
        )
      );
      toast.error(message);
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = null;
        setSending(false);
        setRouting({ streaming: false });
      }
    }
  };

  const keys = keysData?.keys?.filter((k) => !k.revoked) ?? [];

  return (
    <div>
      <PageHeader
        title="Playground"
        description="Stream chat completions and watch gateway routing and failover live."
      />

      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-end">
        <div className="flex-1 space-y-1.5">
          <label className="text-xs text-muted-foreground">Keychain key</label>
          <Select
            value={keyMode}
            onValueChange={(v) => setKeyMode(v as "cached" | "custom")}
          >
            <SelectTrigger>
              <SelectValue placeholder="Select key source" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="cached" disabled={!cachedKey}>
                {cachedKey
                  ? `Cached primary (${cachedKey.slice(0, 8)}…)`
                  : "Cached primary (not available)"}
              </SelectItem>
              <SelectItem value="custom">Paste custom ak- key</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="w-full space-y-1.5 sm:w-auto sm:min-w-[9rem]">
          <label className="text-xs text-muted-foreground">Routing tier</label>
          <Select
            value={effort}
            onValueChange={(v) => setEffort(v as Effort)}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="low">{TIER_LABELS.low}</SelectItem>
              <SelectItem value="medium">{TIER_LABELS.medium}</SelectItem>
              <SelectItem value="high">{TIER_LABELS.high}</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {keyMode === "custom" && (
        <div className="mb-4">
          <Input
            value={customKey}
            onChange={(e) => persistCustomKey(e.target.value)}
            placeholder="ak-…"
            className="font-mono text-sm"
            spellCheck={false}
            autoComplete="off"
          />
        </div>
      )}

      {keys.length === 0 && !cachedKey && keyMode === "cached" && (
        <p className="mb-4 text-sm text-muted-foreground">
          No cached ak- key found. Create one on the API Keys page or paste a
          custom key above.
        </p>
      )}

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        {/* Left — streaming chat */}
        <Card className="flex w-full flex-col">
          <CardHeader className="pb-2">
            <CardTitle>Chat</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div
              ref={chatScrollRef}
              className={cn(
                "space-y-5 rounded-lg bg-secondary/30 px-4 py-5",
                messages.length > 0 &&
                  "max-h-[min(28rem,55vh)] overflow-y-auto scrollbar-thin"
              )}
            >
              {messages.length === 0 ? (
                <div className="flex items-center justify-center py-6">
                  <p className="max-w-sm text-center text-sm text-muted-foreground">
                    Send a message to stream a completion through the gateway.
                  </p>
                </div>
              ) : (
                messages.map((m) =>
                  m.role === "user" ? (
                    <div key={m.id} className="flex animate-rise justify-end">
                      <div className="max-w-[85%] rounded-3xl bg-white/10 px-4 py-2.5 text-base leading-relaxed text-foreground">
                        <p className="whitespace-pre-wrap">{m.content}</p>
                      </div>
                    </div>
                  ) : (
                    <div key={m.id} className="animate-rise pr-2">
                      <div className="max-w-full min-w-0">
                        {m.content ? <ChatMarkdown content={m.content} /> : null}
                        {m.routing?.streaming && (
                          <StreamingIndicator
                            className={cn(
                              m.content
                                ? "ml-1.5 inline-flex align-middle"
                                : "py-1"
                            )}
                          />
                        )}
                      </div>
                    </div>
                  )
                )
              )}
            </div>

            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                void sendMessage();
              }}
            >
              <Input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Message the gateway…"
                disabled={sending}
                className="min-h-11 flex-1"
              />
              <Button type="submit" disabled={sending || !input.trim()}>
                {sending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
                Send
              </Button>
            </form>
          </CardContent>
        </Card>

        {/* Right — routing strip + kill switches */}
        <div className="space-y-6">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle>Routing</CardTitle>
              <CardDescription>
                Per-message routing from <code className="font-mono">routing</code>{" "}
                and <code className="font-mono">done</code> SSE events.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {assistantMessages.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  Routing details appear here after you send a message.
                </p>
              ) : (
                assistantMessages.map((msg, i) => (
                  <div
                    key={msg.id}
                    className={cn(
                      "border-t border-border pt-4 first:border-t-0 first:pt-0",
                      i === assistantMessages.length - 1 && "animate-rise"
                    )}
                  >
                    <p className="mb-2 text-xs text-muted-foreground">
                      Message {i + 1}
                      {i === assistantMessages.length - 1 && " (latest)"}
                    </p>
                    <RoutingStrip
                      routing={msg.routing!}
                      excludedProviders={excludedProviders}
                    />
                  </div>
                ))
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle>Provider kill-switch</CardTitle>
              <CardDescription>
                Toggle a provider off to exclude it via your saved preferences —
                the next request fails over to the next candidate.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {connectedProviders.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  Connect provider keys on the Providers page to use kill-switches.
                </p>
              ) : (
                connectedProviders.map((provider) => {
                  const on = !excludedProviders.includes(provider);
                  const busy = togglingProvider === provider;
                  return (
                    <div
                      key={provider}
                      className="flex items-center justify-between gap-3 rounded-lg bg-secondary/60 px-3 py-2"
                    >
                      <div className="min-w-0">
                        <p className="text-sm font-medium">
                          {providerLabel(provider)}
                        </p>
                        <p className="font-mono text-xs text-muted-foreground">
                          {provider}
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        {busy && (
                          <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
                        )}
                        <span className="text-xs text-muted-foreground">
                          {on ? "On" : "Off"}
                        </span>
                        <Switch
                          checked={on}
                          disabled={busy || !prefsHydrated}
                          onCheckedChange={(checked) =>
                            void setProviderEnabled(provider, checked)
                          }
                          aria-label={`${providerLabel(provider)} routing`}
                        />
                      </div>
                    </div>
                  );
                })
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
