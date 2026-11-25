import { Stack } from "expo-router";
import { CallOverlay } from "../../src/components/call-overlay";

export default function AppLayout() {
  return (
    <>
      <Stack>
        <Stack.Screen name="chats" options={{ title: "Чаты" }} />
        <Stack.Screen name="chats/[id]" options={{ title: "Чат", headerShown: false }} />
        <Stack.Screen name="chats/[id]/info" options={{ title: "О чате", headerShown: false }} />
        <Stack.Screen name="profile" options={{ title: "Профиль", headerShown: false }} />
        <Stack.Screen name="new-chat" options={{ title: "Новый чат", headerShown: false }} />
      </Stack>
      {/* Звонок (§3.12): поверх навигации — не рвётся при переходах */}
      <CallOverlay />
    </>
  );
}
