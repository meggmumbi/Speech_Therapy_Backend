import { useState, type ReactNode } from "react";
import {
  Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogContentText,
  DialogTitle, Paper, TextField, Typography,
} from "@mui/material";

/** The condition chips: coral for D, sky for K, everywhere in the console. */
export function ConditionChip({ condition, label }: { condition: "K" | "D" | null | undefined; label?: string }) {
  if (!condition) return <Chip size="small" label={label ?? "—"} />;
  return (
    <Chip
      size="small"
      label={label ?? condition}
      color={condition === "D" ? "secondary" : "primary"}
      variant={condition === "D" ? "filled" : "outlined"}
    />
  );
}

export function StatCard({ value, label, tone }: { value: ReactNode; label: string; tone?: "success" | "warning" | "error" }) {
  return (
    <Paper sx={{ p: 2.5, bgcolor: tone ? `${tone}.light` : "background.paper" }}>
      <Typography variant="h4" component="div">{value}</Typography>
      <Typography variant="overline" component="div">{label}</Typography>
    </Paper>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <Box sx={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 2, mb: 3, flexWrap: "wrap" }}>
      <Box>
        <Typography variant="h4">{title}</Typography>
        {subtitle && <Typography color="text.secondary" sx={{ mt: 0.5 }}>{subtitle}</Typography>}
      </Box>
      {actions && <Box sx={{ display: "flex", gap: 1, flexWrap: "wrap" }}>{actions}</Box>}
    </Box>
  );
}

export function Section({ title, children, actions }: { title: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <Paper sx={{ p: 2.5 }}>
      <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 1.5 }}>
        <Typography variant="overline">{title}</Typography>
        {actions}
      </Box>
      {children}
    </Paper>
  );
}

/** A yes/no that does not use window.confirm. */
export function ConfirmDialog({
  open, title, text, confirmLabel = "Confirm", danger, busy, onClose, onConfirm,
}: {
  open: boolean; title: string; text: ReactNode; confirmLabel?: string; danger?: boolean; busy?: boolean;
  onClose: () => void; onConfirm: () => void;
}) {
  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent><DialogContentText>{text}</DialogContentText></DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" color={danger ? "error" : "primary"} disabled={busy} onClick={onConfirm}>{confirmLabel}</Button>
      </DialogActions>
    </Dialog>
  );
}

/** One text answer, in a dialog rather than window.prompt. */
export function PromptDialog({
  open, title, label, placeholder, confirmLabel = "Create", busy, onClose, onSubmit,
}: {
  open: boolean; title: string; label: string; placeholder?: string; confirmLabel?: string; busy?: boolean;
  onClose: () => void; onSubmit: (value: string) => void;
}) {
  const [value, setValue] = useState("");
  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <form onSubmit={(e) => { e.preventDefault(); if (value.trim()) onSubmit(value.trim()); }}>
        <DialogTitle>{title}</DialogTitle>
        <DialogContent>
          <TextField autoFocus label={label} placeholder={placeholder} value={value} onChange={(e) => setValue(e.target.value)} sx={{ mt: 1 }} />
        </DialogContent>
        <DialogActions>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="contained" disabled={busy || !value.trim()}>{confirmLabel}</Button>
        </DialogActions>
      </form>
    </Dialog>
  );
}

export function formatDay(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

/** The message for a 404 on a route this console version expects. */
export function staleBackendMessage(e: unknown): string | null {
  const err = e as { status?: number; message?: string } | null;
  if (err && err.status === 404) {
    return "The backend is running an older version than this console: restart uvicorn and reload.";
  }
  return null;
}
