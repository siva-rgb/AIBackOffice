import { NextResponse, type NextRequest } from 'next/server';
import { createServerClient } from '@supabase/ssr';

// Public routes that never require a session.
const PUBLIC = ['/', '/login', '/signup', '/auth', '/privacy', '/terms', '/plans', '/about'];

function isPublic(pathname: string): boolean {
  return PUBLIC.some((p) => pathname === p || pathname.startsWith(p + '/')) || pathname === '/';
}

export async function middleware(req: NextRequest) {
  // E2E test bypass: skip all auth checks when running under Playwright.
  // This env var is set only in the webServer config in playwright.config.ts.
  if (process.env.KORA_E2E_BYPASS_AUTH === 'true') {
    return NextResponse.next({ request: req });
  }

  let res = NextResponse.next({ request: req });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return req.cookies.getAll();
        },
        setAll(cookiesToSet: { name: string; value: string; options?: any }[]) {
          cookiesToSet.forEach(({ name, value }) => req.cookies.set(name, value));
          res = NextResponse.next({ request: req });
          cookiesToSet.forEach(({ name, value, options }) => res.cookies.set(name, value, options));
        },
      },
    },
  );

  // Refreshes the auth token and keeps cookies in sync.
  const {
    data: { user },
  } = await supabase.auth.getUser();

  const { pathname } = req.nextUrl;

  // Unauthenticated → bounce to login (except on public routes).
  if (!user && !isPublic(pathname)) {
    const url = req.nextUrl.clone();
    url.pathname = '/login';
    url.searchParams.set('redirect', pathname);
    return NextResponse.redirect(url);
  }

  // Authenticated visiting login/signup → send to dashboard.
  if (user && (pathname === '/login' || pathname === '/signup')) {
    const url = req.nextUrl.clone();
    url.pathname = '/dashboard';
    url.search = '';
    return NextResponse.redirect(url);
  }

  // Onboarding gate: authenticated users who haven't finished setup are sent to
  // /onboarding for everything except onboarding itself and public/legal pages.
  // RLS ("Users can view own profile") lets the session read its own row.
  if (user && pathname !== '/onboarding' && !isPublic(pathname)) {
    const { data: profile } = await supabase
      .from('users')
      .select('onboarding_completed')
      .eq('id', user.id)
      .single();
    if (profile && profile.onboarding_completed === false) {
      const url = req.nextUrl.clone();
      url.pathname = '/onboarding';
      url.search = '';
      return NextResponse.redirect(url);
    }
  }

  // Finished users shouldn't see the wizard again.
  if (user && pathname === '/onboarding') {
    const { data: profile } = await supabase
      .from('users')
      .select('onboarding_completed')
      .eq('id', user.id)
      .single();
    if (profile?.onboarding_completed) {
      const url = req.nextUrl.clone();
      url.pathname = '/dashboard';
      url.search = '';
      return NextResponse.redirect(url);
    }
  }

  return res;
}

export const config = {
  // Run on everything except static assets.
  matcher: ['/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|csv)$).*)'],
};
