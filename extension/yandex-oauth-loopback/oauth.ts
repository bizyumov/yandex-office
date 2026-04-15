import type { ProviderAuthContext, ProviderAuthResult } from "openclaw/plugin-sdk/plugin-entry";
import {
  buildOauthProviderAuthResult,
  generatePkceVerifierChallenge,
  toFormUrlEncoded,
} from "openclaw/plugin-sdk/provider-auth";
import { createServer } from "node:http";
import { randomBytes } from "node:crypto";

const PROVIDER_ID = "yandex-office";
const DEFAULT_MODEL = "yandex-office/oauth";
const AUTH_URL = "https://oauth.yandex.ru/authorize";
const TOKEN_URL = "https://oauth.yandex.ru/token";
const INFO_URL = "https://login.yandex.ru/info?format=json";
const CLIENT_ID = "25eae219d8da47f9bb67fbeec7c3abb7";
const REDIRECT_URI = "http://localhost:1455/auth/callback";

function generateOAuthState(): string {
  return randomBytes(32).toString("hex");
}

function buildAuthUrl(challenge: string, state: string): string {
  const params = new URLSearchParams({
    client_id: CLIENT_ID,
    response_type: "code",
    redirect_uri: REDIRECT_URI,
    code_challenge: challenge,
    code_challenge_method: "S256",
    state,
  });
  return `${AUTH_URL}?${params.toString()}`;
}

async function waitForLocalCallback(params: {
  expectedState: string;
  timeoutMs: number;
  onProgress?: (message: string) => void;
}): Promise<{ code: string; state: string; cid?: string }> {
  const port = 1455;
  const hostname = "localhost";
  const expectedPath = "/auth/callback";

  return new Promise<{ code: string; state: string; cid?: string }>((resolve, reject) => {
    let timeout: NodeJS.Timeout | null = null;
    const server = createServer((req, res) => {
      try {
        const requestUrl = new URL(req.url ?? "/", `http://${hostname}:${port}`);
        if (requestUrl.pathname !== expectedPath) {
          res.statusCode = 404;
          res.setHeader("Content-Type", "text/plain");
          res.end("Not found");
          return;
        }

        const error = requestUrl.searchParams.get("error");
        const code = requestUrl.searchParams.get("code")?.trim();
        const state = requestUrl.searchParams.get("state")?.trim();
        const cid = requestUrl.searchParams.get("cid")?.trim() || undefined;

        if (error) {
          res.statusCode = 400;
          res.setHeader("Content-Type", "text/plain");
          res.end(`Authentication failed: ${error}`);
          finish(new Error(`OAuth error: ${error}`));
          return;
        }

        if (!code || !state) {
          res.statusCode = 400;
          res.setHeader("Content-Type", "text/plain");
          res.end("Missing code or state");
          finish(new Error("Missing OAuth code or state"));
          return;
        }

        if (state !== params.expectedState) {
          res.statusCode = 400;
          res.setHeader("Content-Type", "text/plain");
          res.end("Invalid state");
          finish(new Error("OAuth state mismatch"));
          return;
        }

        res.statusCode = 200;
        res.setHeader("Content-Type", "text/html; charset=utf-8");
        res.end(
          "<!doctype html><html><head><meta charset='utf-8'/></head>" +
            "<body><h2>Yandex OAuth complete</h2>" +
            "<p>You can close this window and return to OpenClaw.</p></body></html>",
        );

        finish(undefined, { code, state, cid });
      } catch (err) {
        finish(err instanceof Error ? err : new Error("OAuth callback failed"));
      }
    });

    const finish = (err?: Error, result?: { code: string; state: string; cid?: string }) => {
      if (timeout) {
        clearTimeout(timeout);
      }
      try {
        server.close();
      } catch {}
      if (err) {
        reject(err);
      } else if (result) {
        resolve(result);
      }
    };

    server.once("error", (err) => {
      finish(err instanceof Error ? err : new Error("OAuth callback server error"));
    });

    server.listen(port, hostname, () => {
      params.onProgress?.(`Waiting for OAuth callback on ${REDIRECT_URI}…`);
    });

    timeout = setTimeout(() => {
      finish(new Error("OAuth callback timeout"));
    }, params.timeoutMs);
  });
}

async function exchangeCodeForTokens(params: {
  code: string;
  verifier: string;
}): Promise<{
  access: string;
  refresh?: string;
  expires?: number;
}> {
  const response = await fetch(TOKEN_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: toFormUrlEncoded({
      grant_type: "authorization_code",
      code: params.code,
      client_id: CLIENT_ID,
      code_verifier: params.verifier,
    }),
  });
  const payload = (await response.json()) as Record<string, unknown>;
  if (!response.ok) {
    throw new Error(`Yandex token exchange failed: ${JSON.stringify(payload)}`);
  }
  const access = typeof payload.access_token === "string" ? payload.access_token : "";
  if (!access) {
    throw new Error("Yandex token exchange did not return access_token.");
  }
  const refresh = typeof payload.refresh_token === "string" ? payload.refresh_token : undefined;
  const expiresIn =
    typeof payload.expires_in === "number"
      ? payload.expires_in
      : typeof payload.expires_in === "string"
        ? Number.parseInt(payload.expires_in, 10)
        : NaN;
  return {
    access,
    refresh,
    expires: Number.isFinite(expiresIn) ? Date.now() + expiresIn * 1000 : undefined,
  };
}

async function fetchIdentity(accessToken: string): Promise<{ login?: string; clientId?: string }> {
  const response = await fetch(INFO_URL, {
    headers: {
      Authorization: `OAuth ${accessToken}`,
    },
  });
  if (!response.ok) {
    throw new Error(`Yandex identity probe failed with HTTP ${response.status}.`);
  }
  const payload = (await response.json()) as Record<string, unknown>;
  return {
    login: typeof payload.login === "string" ? payload.login : undefined,
    clientId: typeof payload.client_id === "string" ? payload.client_id : undefined,
  };
}

export async function runYandexOfficeOAuth(ctx: ProviderAuthContext): Promise<ProviderAuthResult> {
  await ctx.prompter.note(
    [
      "Browser will open for Yandex authentication.",
      "The callback will be captured automatically on localhost:1455.",
      "If automatic browser opening fails, use the logged URL manually.",
    ].join("\n"),
    "Yandex Office OAuth",
  );

  const { verifier, challenge } = generatePkceVerifierChallenge();
  const state = generateOAuthState();
  const authUrl = buildAuthUrl(challenge, state);
  const progress = ctx.prompter.progress("Starting Yandex OAuth…");
  ctx.runtime.log(`\nOpen this URL in your browser:\n\n${authUrl}\n`);

  progress.update("Complete sign-in in browser...");
  try {
    await ctx.openUrl(authUrl);
  } catch {
    // URL is always logged above; keep local fallback silent here.
  }

  try {
    const callback = await waitForLocalCallback({
      expectedState: state,
      timeoutMs: 5 * 60 * 1000,
      onProgress: (msg) => progress.update(msg),
    });
    progress.update("Exchanging authorization code for tokens...");
    const token = await exchangeCodeForTokens({ code: callback.code, verifier });
    progress.update("Verifying token identity...");
    const identity = await fetchIdentity(token.access);
    progress.stop("Yandex OAuth complete");
    return buildOauthProviderAuthResult({
      providerId: PROVIDER_ID,
      defaultModel: DEFAULT_MODEL,
      access: token.access,
      refresh: token.refresh,
      expires: token.expires,
      email: identity.login,
      credentialExtra: {
        clientId: CLIENT_ID,
        ...(callback.cid ? { cid: callback.cid } : {}),
      },
      configPatch: {},
      notes: [`Redirect URI: ${REDIRECT_URI}`, `Client ID: ${CLIENT_ID}`],
    });
  } catch (err) {
    progress.stop("Yandex OAuth failed");
    throw new Error(
      "Automatic localhost callback failed. Ensure localhost:1455 is reachable and retry.",
      { cause: err },
    );
  }
}
