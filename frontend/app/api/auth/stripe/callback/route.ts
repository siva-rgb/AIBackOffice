import { NextRequest, NextResponse } from 'next/server';

// Proxy Stripe Connect OAuth callback to the FastAPI backend.
// Stripe redirects to this URL after the user grants / denies access.
// The backend handles the token exchange and then redirects to /settings.
export async function GET(request: NextRequest) {
  const queryString = request.nextUrl.searchParams.toString();
  const apiBase = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
  const backendUrl = `${apiBase}/api/stripe-connect/callback?${queryString}`;

  try {
    const response = await fetch(backendUrl, { redirect: 'manual' });
    const location = response.headers.get('location');
    if (location) {
      return NextResponse.redirect(location);
    }
    return NextResponse.json({ error: 'callback_failed' }, { status: 500 });
  } catch {
    return NextResponse.redirect(
      `${process.env.NEXT_PUBLIC_APP_URL ?? 'http://localhost:3000'}/settings?stripe_connect_error=server_error`,
    );
  }
}
