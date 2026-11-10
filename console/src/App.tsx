import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Typography } from "@mui/material";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { Layout } from "./components/Layout";
import { Balance } from "./pages/Balance";
import { Dashboard } from "./pages/Dashboard";
import { Participant } from "./pages/Participant";
import { ParticipantForm } from "./pages/ParticipantForm";
import { Participants } from "./pages/Participants";
import { Rate } from "./pages/Rate";
import { Ratings } from "./pages/Ratings";
import { SignIn } from "./pages/SignIn";
import { Stimuli } from "./pages/Stimuli";

function RequireAuth({ children }: { children: JSX.Element }) {
  const { signedIn } = useAuth();
  const location = useLocation();
  if (!signedIn) return <Navigate to="/signin" replace state={{ from: location.pathname }} />;
  return children;
}

/**
 * A rater's whole console is the rating screen. Everything else is refused
 * by the server as well; this keeps them from ever seeing a link to it.
 */
function RoleRoutes() {
  const { role } = useAuth();
  if (role === null) return <Typography color="text.secondary">Loading…</Typography>;
  if (role === "rater") {
    return (
      <Routes>
        <Route path="/rate" element={<Rate role="rater" />} />
        <Route path="*" element={<Navigate to="/rate" replace />} />
      </Routes>
    );
  }
  return (
    <Routes>
      <Route index element={<Navigate to="/dashboard" replace />} />
      <Route path="/dashboard" element={<Dashboard />} />
      <Route path="/participants" element={<Participants />} />
      <Route path="/participants/new" element={<ParticipantForm />} />
      <Route path="/participants/:id" element={<Participant />} />
      <Route path="/participants/:id/edit" element={<ParticipantForm />} />
      <Route path="/stimuli" element={<Stimuli />} />
      <Route path="/balance" element={<Balance />} />
      <Route path="/ratings" element={<Ratings />} />
      <Route path="/rate" element={<Rate role="researcher" />} />
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}

export function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/signin" element={<SignIn />} />
        <Route path="/*" element={<RequireAuth><Layout><RoleRoutes /></Layout></RequireAuth>} />
      </Routes>
    </AuthProvider>
  );
}
