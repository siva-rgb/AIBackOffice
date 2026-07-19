'use client';

import { useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { Sparkles, Loader2 } from 'lucide-react';
import { getSupabaseBrowser } from '@/lib/supabase/client';

export function AuthForm({ mode }: { mode: 'login' | 'signup' }) {
  const router = useRouter();
  const params = useSearchParams();
  const redirect = params.get('redirect') || '/dashboard';
  const supabase = getSupabaseBrowser();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [agreed, setAgreed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const isSignup = mode === 'signup';
  const input =
    'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-kora-500 focus:outline-none focus:ring-1 focus:ring-kora-500';

  async function submitEmail(e: React.FormEvent) {
    e.preventDefault();
    if (isSignup && !agreed) {
      setError('Please agree to the Terms of Service and Privacy Policy.');
      return;
    }
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      if (isSignup) {
        const { data, error } = await supabase.auth.signUp({
          email,
          password,
          options: { data: { full_name: fullName } },
        });
        if (error) throw error;
        if (data.session) {
          router.replace(redirect);
          router.refresh();
        } else {
          setInfo('Check your email to confirm your account, then sign in.');
        }
      } else {
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) throw error;
        router.replace(redirect);
        router.refresh();
      }
    } catch (err: any) {
      setError(err?.message ?? 'Authentication failed');
    } finally {
      setBusy(false);
    }
  }

  async function google() {
    setError(null);
    const { error } = await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: {
        redirectTo: `${window.location.origin}/auth/callback?redirect=${encodeURIComponent(redirect)}`,
      },
    });
    if (error) setError(error.message);
  }

  return (
    <div className="w-full max-w-sm">
      <div className="mb-6 flex items-center gap-2">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-kora-600 text-white">
          <Sparkles size={20} />
        </div>
        <span className="text-xl font-bold">Kora</span>
      </div>

      <h1 className="text-2xl font-bold text-gray-900">
        {isSignup ? 'Create your account' : 'Welcome back'}
      </h1>
      <p className="mt-1 text-sm text-gray-500">
        {isSignup ? 'Start running your back-office on autopilot.' : 'Sign in to your AI back-office.'}
      </p>

      <button
        onClick={google}
        className="mt-6 flex w-full items-center justify-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2.5 text-sm font-semibold text-gray-700 hover:bg-gray-50"
      >
        <GoogleIcon /> Continue with Google
      </button>

      <div className="my-5 flex items-center gap-3 text-xs text-gray-400">
        <div className="h-px flex-1 bg-gray-200" /> or {isSignup ? 'sign up' : 'sign in'} with email
        <div className="h-px flex-1 bg-gray-200" />
      </div>

      <form onSubmit={submitEmail} className="space-y-3">
        {isSignup && (
          <input className={input} placeholder="Full name" value={fullName} onChange={(e) => setFullName(e.target.value)} />
        )}
        <input className={input} type="email" placeholder="you@business.com" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <input className={input} type="password" placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={6} />
        {isSignup && (
          <label className="flex items-start gap-2 text-xs text-gray-500">
            <input
              type="checkbox"
              checked={agreed}
              onChange={(e) => setAgreed(e.target.checked)}
              className="mt-0.5 h-3.5 w-3.5 rounded border-gray-300 text-kora-600 focus:ring-kora-500"
            />
            <span>
              I agree to Kora&apos;s{' '}
              <Link href="/terms" target="_blank" className="font-medium text-kora-600 hover:underline">Terms of Service</Link>{' '}
              and{' '}
              <Link href="/privacy" target="_blank" className="font-medium text-kora-600 hover:underline">Privacy Policy</Link>.
            </span>
          </label>
        )}
        {error && <div className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>}
        {info && <div className="rounded-lg bg-emerald-50 px-3 py-2 text-xs text-emerald-700">{info}</div>}
        <button
          type="submit"
          disabled={busy}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-kora-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-kora-700 disabled:opacity-60"
        >
          {busy && <Loader2 size={15} className="animate-spin" />}
          {isSignup ? 'Create account' : 'Sign in'}
        </button>
      </form>

      <p className="mt-5 text-center text-sm text-gray-500">
        {isSignup ? (
          <>Already have an account? <Link href="/login" className="font-medium text-kora-600">Sign in</Link></>
        ) : (
          <>New to Kora? <Link href="/signup" className="font-medium text-kora-600">Create an account</Link></>
        )}
      </p>

      {!isSignup && (
        <p className="mt-4 rounded-lg bg-gray-50 px-3 py-2 text-center text-xs text-gray-400">
          Demo login: demo@kora.app / Kora-Demo-2026!
        </p>
      )}
    </div>
  );
}

function GoogleIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 48 48" aria-hidden>
      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.9 29.3 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34.3 6.1 29.4 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.3-.4-3.5z" />
      <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 16 19 12 24 12c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34.3 6.1 29.4 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
      <path fill="#4CAF50" d="M24 44c5.2 0 10-2 13.6-5.2l-6.3-5.2C29.2 35.1 26.7 36 24 36c-5.3 0-9.6-3.1-11.3-7.5l-6.5 5C9.6 39.6 16.2 44 24 44z" />
      <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.1-4 5.6l6.3 5.2C41.4 36.3 44 30.6 44 24c0-1.3-.1-2.3-.4-3.5z" />
    </svg>
  );
}
