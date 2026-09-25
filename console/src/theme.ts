import { createTheme } from "@mui/material/styles";

/**
 * The app's palette from ui/theme/Color.kt, so the console and the tablet
 * read as one system. Sky is identity, coral is the call to action.
 */
export const theme = createTheme({
  palette: {
    mode: "light",
    primary: { main: "#0B79C9", dark: "#004B72", light: "#D4EBFF", contrastText: "#fff" },
    secondary: { main: "#CC4A17", dark: "#842B0F", light: "#FFDBCF", contrastText: "#fff" },
    success: { main: "#2E7D32", light: "#D7F2D8" },
    warning: { main: "#C98A00", light: "#FFE9A8" },
    error: { main: "#B3261E", light: "#F9DEDC" },
    background: { default: "#F4F7FA", paper: "#FFFFFF" },
    text: { primary: "#0F1A22", secondary: "#4B5E6B" },
    divider: "#E3EEF6",
  },
  shape: { borderRadius: 12 },
  typography: {
    fontFamily: 'Inter, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
    h4: { fontWeight: 700, fontSize: "1.6rem", letterSpacing: "-0.01em" },
    h5: { fontWeight: 700, fontSize: "1.2rem" },
    h6: { fontWeight: 600, fontSize: "1rem" },
    overline: { fontWeight: 700, letterSpacing: "0.08em", color: "#4B5E6B" },
    button: { textTransform: "none", fontWeight: 600 },
  },
  components: {
    MuiPaper: {
      defaultProps: { elevation: 0 },
      styleOverrides: { root: { border: "1px solid #E3EEF6" } },
    },
    MuiCard: {
      defaultProps: { elevation: 0 },
      styleOverrides: { root: { border: "1px solid #E3EEF6" } },
    },
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: { root: { borderRadius: 10, paddingInline: 16 } },
    },
    MuiChip: { styleOverrides: { root: { fontWeight: 600 } } },
    MuiTableCell: { styleOverrides: { head: { fontSize: 12, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.04em", color: "#4B5E6B" } } },
    MuiTextField: { defaultProps: { size: "small", fullWidth: true } },
    MuiFormControl: { defaultProps: { size: "small", fullWidth: true } },
    MuiAlert: { styleOverrides: { root: { borderRadius: 10 } } },
  },
});
