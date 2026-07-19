import { NextRequest, NextResponse } from "next/server"

// Proxy the Google OAuth callback to the FastAPI backend.
// Google redirects to /api/auth/google/callback (Next.js), which forwards
// all query params to the FastAPI route that exchanges the code for tokens.
export async function GET(request: NextRequest) {
  const queryString = request.nextUrl.searchParams.toString()
  const apiUrl = `${process.env.NEXT_PUBLIC_API_URL}/api/auth/google/callback?${queryString}`
  try {
    const response = await fetch(apiUrl, { redirect: "manual" })
    const location = response.headers.get("location")
    if (location) return NextResponse.redirect(location)
    return NextResponse.json({ error: "callback_failed" }, { status: 500 })
  } catch {
    return NextResponse.json({ error: "backend_unreachable" }, { status: 502 })
  }
}
