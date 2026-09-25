import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  Box, Button, Drawer, List, ListItemButton, ListItemIcon, ListItemText, Typography,
} from "@mui/material";
import PeopleOutlineIcon from "@mui/icons-material/PeopleOutline";
import LibraryBooksOutlinedIcon from "@mui/icons-material/LibraryBooksOutlined";
import BalanceOutlinedIcon from "@mui/icons-material/BalanceOutlined";
import LogoutIcon from "@mui/icons-material/Logout";
import { useAuth } from "../auth/AuthContext";

const WIDTH = 240;

const NAV = [
  { to: "/participants", label: "Participants", icon: <PeopleOutlineIcon /> },
  { to: "/stimuli", label: "Stimulus sets", icon: <LibraryBooksOutlinedIcon /> },
  { to: "/balance", label: "Balance", icon: <BalanceOutlinedIcon /> },
];

export function Layout() {
  const { signOut } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  return (
    <Box sx={{ display: "flex", minHeight: "100%" }}>
      <Drawer
        variant="permanent"
        sx={{ width: WIDTH, flexShrink: 0, "& .MuiDrawer-paper": { width: WIDTH, boxSizing: "border-box", borderRight: "1px solid", borderColor: "divider", p: 2 } }}
      >
        <Typography variant="h6" sx={{ px: 1.5, py: 1, color: "primary.dark", fontWeight: 700 }}>Study console</Typography>
        <List sx={{ mt: 1 }}>
          {NAV.map((n) => {
            const active = location.pathname.startsWith(n.to);
            return (
              <ListItemButton
                key={n.to} component={NavLink} to={n.to} selected={active}
                sx={{ borderRadius: 2, mb: 0.5, "&.Mui-selected": { bgcolor: "primary.light", color: "primary.dark" } }}
              >
                <ListItemIcon sx={{ minWidth: 36, color: active ? "primary.dark" : "text.secondary" }}>{n.icon}</ListItemIcon>
                <ListItemText primary={n.label} primaryTypographyProps={{ fontWeight: 600 }} />
              </ListItemButton>
            );
          })}
        </List>
        <Box sx={{ flex: 1 }} />
        <Button startIcon={<LogoutIcon />} color="inherit" sx={{ justifyContent: "flex-start", color: "text.secondary" }}
          onClick={async () => { await signOut(); navigate("/signin"); }}>
          Sign out
        </Button>
      </Drawer>
      <Box component="main" sx={{ flex: 1, p: { xs: 2, md: 5 }, maxWidth: 1200, width: "100%" }}>
        <Outlet />
      </Box>
    </Box>
  );
}
