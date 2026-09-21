import { NextResponse, type NextRequest } from "next/server";

export function middleware(request: NextRequest) {
  // Cookie is a UI routing hint only. The client requires a session token;
  // Backend OIDC and Staff DB authorization protect every Admin API request.
  const production = process.env.APP_ENV === "production";
  const publicPath = request.nextUrl.pathname === "/auth-required";
  if (production && !publicPath && request.cookies.get("admin_authenticated")?.value !== "1") {
    const target = request.nextUrl.clone();
    target.pathname = "/auth-required";
    target.search = "";
    return NextResponse.redirect(target);
  }
  return NextResponse.next();
}
export const config = { matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"] };
