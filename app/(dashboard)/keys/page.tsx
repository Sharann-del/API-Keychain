"use client";

import * as React from "react";
import {
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  Plus,
  Trash2,
  Terminal,
} from "lucide-react";
import { toast } from "sonner";

import { useAuth } from "@/lib/auth";
import { api, useApi, API_BASE_URL, PROXY_BASE_URL, ApiError } from "@/lib/api";
import { loadPrimaryKey } from "@/lib/keystore";
import { formatRelative, maskKey, cn } from "@/lib/utils";
import type {
  CreatedKeychainKey,
  KeychainKey,
  ListKeychainKeysResponse,
} from "@/lib/types";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { CopyButton } from "@/components/copy-button";
import { EmptyState } from "@/components/empty-state";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { SecretDialog } from "@/components/secret-dialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

function CodeBlock({ code }: { code: string }) {
  return (
    <div className="relative rounded-lg bg-secondary">
      <div className="absolute right-2 top-2">
        <CopyButton value={code} label="Copied snippet" />
      </div>
      <pre className="overflow-x-auto p-3 pr-12 text-xs leading-relaxed scrollbar-thin">
        <code className="font-mono text-foreground">{code}</code>
      </pre>
    </div>
  );
}

export default function KeysPage() {
  const { userId, ready } = useAuth();
  const enabled = Boolean(userId && ready);

  const { data, isLoading, mutate } = useApi<ListKeychainKeysResponse>(
    enabled ? `/users/${userId}/keychain-keys` : null
  );

  const [revealed, setRevealed] = React.useState(false);
  const [cachedKey, setCachedKey] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (userId) setCachedKey(loadPrimaryKey(userId));
  }, [userId, ready]);

  const keys = data?.keys ?? [];
  const primary = keys.find((k) => k.is_primary && !k.revoked);
  const otherKeys = keys.filter((k) => !k.is_primary);

  // Create-key dialog state
  const [createOpen, setCreateOpen] = React.useState(false);
  const [newLabel, setNewLabel] = React.useState("");
  const [creating, setCreating] = React.useState(false);
  const [newSecret, setNewSecret] = React.useState<string | null>(null);
  const [secretOpen, setSecretOpen] = React.useState(false);

  // Revoke dialog state
  const [revokeTarget, setRevokeTarget] = React.useState<KeychainKey | null>(
    null
  );

  const displayedPrimary = primary
    ? revealed && cachedKey
      ? cachedKey
      : primary.masked
    : "";

  const createKey = async () => {
    setCreating(true);
    try {
      const res = await api.post<CreatedKeychainKey>(
        `/users/${userId}/keychain-keys`,
        { label: newLabel.trim() || "default" }
      );
      setNewSecret(res.api_key);
      setSecretOpen(true);
      setCreateOpen(false);
      setNewLabel("");
      toast.success("API key created");
      void mutate();
    } catch (err) {
      toast.error(
        err instanceof ApiError ? err.message : "Failed to create key"
      );
    } finally {
      setCreating(false);
    }
  };

  const revokeKey = async () => {
    if (!revokeTarget) return;
    try {
      await api.del(`/keychain-keys/${revokeTarget.id}`);
      toast.success("Key revoked");
      void mutate();
    } catch (err) {
      toast.error(
        err instanceof ApiError ? err.message : "Failed to revoke key"
      );
    }
  };

  return (
    <div>
      <PageHeader
        title="API Keys"
        description="Your unified ak- key fronts every provider — for OpenAI SDKs, curl, and Claude Code."
        actions={
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" /> New key
          </Button>
        }
      />

      {/* Unified key + base URL */}
      <Card>
        <CardHeader>
          <CardTitle>Your unified API key</CardTitle>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="space-y-2">
            <Label>API key</Label>
            {isLoading ? (
              <Skeleton className="h-10 w-full" />
            ) : primary ? (
              <>
                <div className="flex items-center gap-2 rounded-lg bg-secondary p-2">
                  <code className="flex-1 overflow-x-auto whitespace-nowrap px-1 font-mono text-sm scrollbar-thin">
                    {displayedPrimary}
                  </code>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => setRevealed((r) => !r)}
                    disabled={!cachedKey}
                    title={
                      cachedKey
                        ? revealed
                          ? "Hide"
                          : "Reveal"
                        : "Full key unavailable on this device — regenerate in Settings"
                    }
                  >
                    {revealed ? (
                      <EyeOff className="h-4 w-4" />
                    ) : (
                      <Eye className="h-4 w-4" />
                    )}
                  </Button>
                  <CopyButton
                    value={cachedKey ?? primary.masked}
                    label="API key copied"
                  />
                </div>
                {!cachedKey && (
                  <p className="text-xs text-muted-foreground">
                    The full key isn&apos;t stored on this device. Regenerate it
                    from Settings to get a new revealable key.
                  </p>
                )}
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                No primary key yet — it will be created automatically. Try
                refreshing, or regenerate one in Settings.
              </p>
            )}
          </div>

          <div className="space-y-2">
            <Label>OpenAI base URL</Label>
            <div className="flex items-center gap-2 rounded-lg bg-secondary p-2">
              <code className="flex-1 px-1 font-mono text-sm">
                {PROXY_BASE_URL}
              </code>
              <CopyButton value={PROXY_BASE_URL} label="Base URL copied" />
            </div>
            <p className="text-xs text-muted-foreground">
              Use with OpenAI SDKs, Codex CLI, Cursor, and curl — append{" "}
              <code className="font-mono">/chat/completions</code> or{" "}
              <code className="font-mono">/responses</code>.
            </p>
          </div>

          <div className="space-y-2">
            <Label>Claude Code base URL</Label>
            <div className="flex items-center gap-2 rounded-lg bg-secondary p-2">
              <code className="flex-1 px-1 font-mono text-sm">
                {API_BASE_URL}
              </code>
              <CopyButton value={API_BASE_URL} label="Claude base URL copied" />
            </div>
            <p className="text-xs text-muted-foreground">
              Set as <code className="font-mono">ANTHROPIC_BASE_URL</code> (no{" "}
              <code className="font-mono">/v1</code> suffix). Claude Code calls{" "}
              <code className="font-mono">/v1/messages</code> on this host.
            </p>
          </div>
        </CardContent>
      </Card>

      {/* How to use */}
      <Card className="mt-6">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Terminal className="h-4 w-4" /> How to use
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="space-y-2">
            <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              curl
            </p>
            <CodeBlock
              code={`curl ${PROXY_BASE_URL}/chat/completions \\
  -H "Authorization: Bearer ${cachedKey ?? "ak-..."}" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "keychain-medium",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'`}
            />
          </div>
          <div className="space-y-2">
            <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              OpenAI SDK (Python)
            </p>
            <CodeBlock
              code={`from openai import OpenAI

client = OpenAI(
    base_url="${PROXY_BASE_URL}",
    api_key="${cachedKey ?? "ak-..."}",
)

resp = client.chat.completions.create(
    model="keychain-medium",  # fast: keychain-low · balanced: keychain-medium · best: keychain-high
    messages=[{"role": "user", "content": "Hello!"}],
)
print(resp.choices[0].message.content)`}
            />
          </div>
          <div className="space-y-2">
            <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Claude Code
            </p>
            <CodeBlock
              code={`export ANTHROPIC_BASE_URL="${API_BASE_URL}"
export ANTHROPIC_API_KEY="${cachedKey ?? "ak-..."}"

# Models like claude-sonnet-4-6 map to effort tiers and route
# through your free-tier provider cascade.
claude`}
            />
            <p className="text-xs text-muted-foreground">
              Same <code className="font-mono">ak-</code> key as above. Claude
              sends <code className="font-mono">x-api-key</code>, which the
              gateway accepts.               Use <code className="font-mono">claude-haiku-4-5</code> (fast),{" "}
              <code className="font-mono">claude-sonnet-4-6</code> (balanced), or{" "}
              <code className="font-mono">claude-opus-4-6</code> (best) — all route
              through free-tier providers.
            </p>
          </div>
          <div className="space-y-2">
            <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Codex CLI
            </p>
            <CodeBlock
              code={`export OPENAI_BASE_URL="${PROXY_BASE_URL}"
export OPENAI_API_KEY="${cachedKey ?? "ak-..."}"

# Codex CLI v0.136+ calls POST /v1/responses on the base URL above.
codex`}
            />
            <p className="text-xs text-muted-foreground">
              Same <code className="font-mono">ak-</code> key. Point Codex at{" "}
              <code className="font-mono">{PROXY_BASE_URL}</code> (includes{" "}
              <code className="font-mono">/v1</code>) — the gateway translates
              Responses API requests through the same routing cascade.
            </p>
          </div>
        </CardContent>
      </Card>

      {/* All keys */}
      <Card className="mt-6">
        <CardHeader>
          <CardTitle>All keys</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : keys.length === 0 ? (
            <EmptyState
              icon={KeyRound}
              title="No keys yet"
              description="Create a keychain key to start sending requests."
              action={
                <Button onClick={() => setCreateOpen(true)}>
                  <Plus className="h-4 w-4" /> New key
                </Button>
              }
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Label</TableHead>
                  <TableHead>Key</TableHead>
                  <TableHead>Last used</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="w-10" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {[...(primary ? [primary] : []), ...otherKeys].map((k) => (
                  <TableRow
                    key={k.id}
                    className={cn(k.revoked && "opacity-50")}
                  >
                    <TableCell className="font-medium">
                      <span className="flex items-center gap-2">
                        {k.label}
                        {k.is_primary && (
                          <Badge variant="accent">primary</Badge>
                        )}
                      </span>
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {k.masked || maskKey("ak-xxxxxxxx")}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatRelative(k.last_used_at)}
                    </TableCell>
                    <TableCell>
                      {k.revoked ? (
                        <Badge variant="danger">revoked</Badge>
                      ) : (
                        <Badge variant="success">active</Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      {!k.revoked && !k.is_primary && (
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => setRevokeTarget(k)}
                          title="Revoke key"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Create key dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Create API key</DialogTitle>
            <DialogDescription>
              Give the key a label so you can recognize it later.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor="key-label">Label</Label>
            <Input
              id="key-label"
              placeholder="e.g. production"
              value={newLabel}
              onChange={(e) => setNewLabel(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !creating) void createKey();
              }}
              autoFocus
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button onClick={createKey} disabled={creating}>
              {creating && <Loader2 className="h-4 w-4 animate-spin" />}
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <SecretDialog
        open={secretOpen}
        onOpenChange={setSecretOpen}
        secret={newSecret}
      />

      <ConfirmDialog
        open={Boolean(revokeTarget)}
        onOpenChange={(o) => !o && setRevokeTarget(null)}
        title="Revoke this key?"
        description={
          <>
            The key{" "}
            <span className="font-mono text-foreground">
              {revokeTarget?.label}
            </span>{" "}
            will stop working immediately. This cannot be undone.
          </>
        }
        confirmLabel="Revoke"
        destructive
        onConfirm={revokeKey}
      />
    </div>
  );
}
