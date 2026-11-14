import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const SESSION_COOKIE = "nesto_session";

const PUBLIC_PATHS = ["/invite", "/admin"];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (
    pathname.startsWith("/_next") ||
    pathname.startsWith("/favicon") ||
    pathname.startsWith("/icon") ||
    pathname.startsWith("/apple-icon") ||
    pathname.startsWith("/logo") ||
    pathname.match(/\.(png|jpg|jpeg|svg|ico|webp|mp4|mp3)$/)
  ) {
    return NextResponse.next();
  }

  // Admin View-as: install read-only session cookie before auth gate
  const viewAs = request.nextUrl.searchParams.get("view_as");
  if (viewAs && (pathname === "/" || pathname.startsWith("/project"))) {
    const clean = request.nextUrl.clone();
    clean.searchParams.delete("view_as");
    const res = NextResponse.redirect(clean);
    res.cookies.set({
      name: SESSION_COOKIE,
      value: viewAs,
      path: "/",
      maxAge: 60 * 60,
      sameSite: "lax",
      httpOnly: false,
    });
    return res;
  }

  const isPublic = PUBLIC_PATHS.some(
    (p) => pathname === p || pathname.startsWith(`${p}/`)
  );
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  const authReason = request.nextUrl.searchParams.get("reason");

  if (!token && !isPublic) {
    const url = request.nextUrl.clone();
    url.pathname = "/invite";
    url.search = "";
    return NextResponse.redirect(url);
  }

  // Allow /invite?reason=revoked|expired|session even with a stale cookie —
  // otherwise force-logout redirects bounce straight back to Studio.
  if (token && pathname === "/invite" && !authReason) {
    const url = request.nextUrl.clone();
    url.pathname = "/";
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image).*)"],
};
