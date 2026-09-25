import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { Layout } from "./components/Layout";
import { Balance } from "./pages/Balance";
import { Participant } from "./pages/Participant";
import { ParticipantForm } from "./pages/ParticipantForm";
import { Participants } from "./pages/Participants";
import { SignIn } from "./pages/SignIn";

function RequireAuth({ children }: { children: JSX.Element }) {
  const { signedIn } = useAuth();
  const location = useLocation();
  if (!signedIn) return <Navigate to="/signin" replace state={{ from: location.pathname }} />;
  return children;
}

export function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/signin" element={<SignIn />} />
        <Route element={<RequireAuth><Layout /></RequireAuth>}>
          <Route index element={<Navigate to="/participants" replace />} />
          <Route path="/participants" element={<Participants />} />
          <Route path="/participants/new" element={<ParticipantForm />} />
          <Route path="/participants/:id" element={<Participant />} />
          <Route path="/participants/:id/edit" element={<ParticipantForm />} />
          <Route path="/balance" element={<Balance />} />
        </Route>
        <Route path="*" element={<Navigate to="/participants" replace />} />
      </Routes>
    </AuthProvider>
  );
}
