import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes, useParams } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "./app/query";
import { Layout } from "./app/Layout";
import { RequireAuth, RequireAdmin } from "./app/guards";
import { ChatPage } from "./features/messages/ChatPage";
import { HomePage } from "./pages/HomePage";
import { ProfilePage } from "./pages/ProfilePage";
import { SettingsPage, initTheme } from "./pages/SettingsPage";
import { JoinPage } from "./pages/JoinPage";
import { LoginPage } from "./pages/LoginPage";
import { AdminPage } from "./pages/admin/AdminPage";
import "./styles.css";

initTheme();

function ChatPageWrapper() {
  const { chatId } = useParams<{ chatId: string }>();
  if (!chatId) return null;
  return <ChatPage chatId={chatId} />;
}

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route
            path="/"
            element={
              <RequireAuth>
                <Layout />
              </RequireAuth>
            }
          >
            <Route index element={<HomePage />} />
            <Route path="chat/:chatId" element={<ChatPageWrapper />} />
            <Route path="me" element={<ProfilePage />} />
            <Route path="settings" element={<SettingsPage />} />
            <Route
              path="admin"
              element={
                <RequireAdmin>
                  <AdminPage />
                </RequireAdmin>
              }
            />
            <Route path="*" element={<HomePage />} />
          </Route>
          <Route path="join/:code" element={<JoinPage />} />
          <Route path="login" element={<LoginPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
