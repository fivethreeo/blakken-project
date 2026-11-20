import type { IncomingMessage } from 'node:http';

export interface AuthOptions {
  djangoUrl?: string;
  serviceToken?: string;
  sessionCookieName?: string;
  authPath?: 'internal/auth/' | 'internal/order-auth/' | 'internal/management-order-auth/';
}

export type AuthResult = string | number | null;

export async function authenticate(
  request: IncomingMessage,
  {
    djangoUrl = process.env.DJANGO_INTERNAL_URL,
    serviceToken = process.env.DJANGO_INTERNAL_AUTH_TOKEN,
    sessionCookieName = process.env.DJANGO_SESSION_COOKIE_NAME || 'sessionid',
    authPath = 'internal/auth/',
  }: AuthOptions = {},
): Promise<AuthResult> {
  if (!djangoUrl || !serviceToken) return null;

  const prefix = `${sessionCookieName}=`;
  const cookie = request.headers.cookie
    ?.split(';')
    .map((value) => value.trim())
    .find((value) => value.startsWith(prefix) && value.length > prefix.length);
  const managementAuthorization = authPath === 'internal/management-order-auth/'
    ? request.headers.authorization
    : undefined;
  if (!cookie && !managementAuthorization) return null;

  try {
    const base = djangoUrl.endsWith('/') ? djangoUrl : `${djangoUrl}/`;
    const headers: Record<string, string> = {
      Authorization: `Bearer ${serviceToken}`,
    };
    if (cookie) {
      headers.Cookie = cookie;
    }
    if (managementAuthorization) {
      headers['X-Management-Authorization'] = managementAuthorization;
    }
    const response = await fetch(new URL(authPath, base), {
      headers,
      redirect: 'error',
      signal: AbortSignal.timeout(3000),
    });
    if (response.status !== 200) return null;

    const { user_id: userId } = await response.json();
    if (
      (typeof userId === 'string' && userId.length > 0)
      || (typeof userId === 'number' && Number.isSafeInteger(userId) && userId > 0)
    ) {
      return userId;
    }
  } catch {
    return null;
  }
  return null;
}
