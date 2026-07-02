"use client";

import Image from "next/image";
import { signIn, useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

export default function LoginPage() {
  const { status } = useSession();
  const router = useRouter();

  useEffect(() => {
    if (status === "authenticated") {
      router.replace("/");
    }
  }, [status, router]);

  return (
    <main className="login-shell">
      <section className="login-card">
        <Image
          src="/brand/eagle-logo.png"
          alt="Eagle3D logo"
          width={72}
          height={72}
          className="login-logo"
          priority
        />

        <h1>Eagle Analytics Hub</h1>

        <p>
          Secure analytics command center for Eagle3D Streaming. Sign in with
          your verified Google account. Only authorized Eagle3D users can enter.
        </p>

        <div className="form-stack">
          <button
            className="primary-button"
            onClick={() => signIn("google", { callbackUrl: "/" })}
          >
            Continue with Google
          </button>

          <p className="error-text">
            Access is restricted to authorized Eagle3D emails only.
          </p>
        </div>
      </section>
    </main>
  );
}
