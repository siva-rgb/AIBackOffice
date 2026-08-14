import { NextResponse, type NextRequest } from 'next/server';
import { createServerClient } from '@supabase/ssr';
import { cookies } from 'next/headers';

// The origin to send the browser back to.
//
// `new URL(req.url).origin` is NOT it once this runs behind a proxy: inside the
// Cloud Run container the server sees its own bind address, so the origin came
// out as `http://0.0.0.0:8080` and Google sign-in redirected users to
// `0.0.0.0:8080/dashboard` — ERR_ADDRESS_INVALID, after a successful login.
//
// The forwarded headers carry the host the browser actually used, which also
// keeps this correct across BOTH hostnames Cloud Run serves (the legacy
// *.a.run.app and the newer *.run.app) instead of pinning one of them.
// Protocol falls back to the request's own scheme rather than a hardcoded
// https, so `npm run dev` on http://localhost:3000 still works.
function publicOrigin(req: NextRequest): string {
  const host = req.headers.get('x-forwarded-host') ?? req.headers.get('host');
  if (!host) return new URL(req.url).origin;
  const proto = req.headers.get('x-forwarded-proto') ?? new URL(req.url).protocol.replace(':', '');
  return `${proto}://${host}`;
}

// Only ever redirect to a path on our own origin. `redirect` arrives as a query
// parameter, so an absolute or protocol-relative value would turn this callback
// into an open redirect — a phishing primitive that is especially attractive on
// an auth endpoint.
function safePath(value: string | null): string {
  if (!value || !value.startsWith('/') || value.startsWith('//')) return '/dashboard';
  return value;
}

// OAuth (Google) PKCE callback — exchanges the code for a session, sets cookies,
// then redirects into the app.
export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const origin = publicOrigin(req);
  const code = searchParams.get('code');
  const redirect = safePath(searchParams.get('redirect'));

  if (code) {
    const cookieStore = cookies();
    const supabase = createServerClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL!,
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
      {
        cookies: {
          getAll() {
            return cookieStore.getAll();
          },
          setAll(cookiesToSet: { name: string; value: string; options?: any }[]) {
            cookiesToSet.forEach(({ name, value, options }) => cookieStore.set(name, value, options));
          },
        },
      },
    );
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (!error) {
      return NextResponse.redirect(`${origin}${redirect}`);
    }
  }
  return NextResponse.redirect(`${origin}/login?error=oauth`);
}
