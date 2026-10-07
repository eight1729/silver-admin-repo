import { NextResponse, type NextRequest } from "next/server";
import { normalizedAppEnvironment } from "../../app/lib/environment-policy";

export function middleware(request: NextRequest) {
  // Cookie is a UI routing hint only. The client requires a session token;
  // Backend OIDC and Staff DB authorization protect every Admin API request.
  normalizedAppEnvironment(process.env.APP_ENV);
  const publicPath = request.nextUrl.pathname === "/auth-required";
  if (!publicPath && request.cookies.get("admin_authenticated")?.value !== "1") {
    const target = request.nextUrl.clone();
    target.pathname = "/auth-required";
    target.search = "";
    return NextResponse.redirect(target);
  }
  return NextResponse.next();
}
export const config = { matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"] };
