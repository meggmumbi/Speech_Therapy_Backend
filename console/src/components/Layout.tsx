import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export function Layout() {
  const { signOut } = useAuth();
  const navigate = useNavigate();
  return (
    <div className="shell">
      <nav className="nav">
        <div className="brand">Study console</div>
        <NavLink to="/participants">Participants</NavLink>
        <NavLink to="/balance">Balance</NavLink>
        <div className="spacer" />
        <button
          className="btn-ghost"
          onClick={async () => {
            await signOut();
            navigate("/signin");
          }}
        >
          Sign out
        </button>
      </nav>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}

export function Pill({ tone, children }: { tone?: "good" | "fair" | "bad" | "sky" | "coral"; children: React.ReactNode }) {
  return <span className={`pill ${tone ?? ""}`}>{children}</span>;
}

export function Notice({ tone, children }: { tone: "warn" | "bad" | "good"; children: React.ReactNode }) {
  return <div className={`notice ${tone}`}>{children}</div>;
}

export function formatDay(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}
