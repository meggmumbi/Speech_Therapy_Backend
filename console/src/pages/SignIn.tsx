import { useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Alert, Box, Button, Paper, Stack, TextField, Typography } from "@mui/material";
import { useAuth } from "../auth/AuthContext";

export function SignIn() {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(username.trim(), password);
      const to = (location.state as { from?: string } | null)?.from ?? "/dashboard";
      navigate(to, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign in");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Box sx={{ minHeight: "100%", display: "grid", placeItems: "center", p: 3, bgcolor: "background.default" }}>
      <Paper component="form" onSubmit={submit} sx={{ p: 4, width: "100%", maxWidth: 400 }}>
        <Stack spacing={2}>
          <Box>
            <Typography variant="h4">Study console</Typography>
            <Typography color="text.secondary" sx={{ mt: 0.5 }}>Same account as the tablet app. Participants never sign in here.</Typography>
          </Box>
          <TextField label="Username" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus autoComplete="username" />
          <TextField label="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
          {error && <Alert severity="error">{error}</Alert>}
          <Button type="submit" variant="contained" size="large" disabled={busy || !username || !password}>
            {busy ? "Signing in…" : "Sign in"}
          </Button>
        </Stack>
      </Paper>
    </Box>
  );
}
