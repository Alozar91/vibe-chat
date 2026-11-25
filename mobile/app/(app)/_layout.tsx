import { Stack } from "expo-router";

export default function AppLayout() {
  return (
    <Stack>
      <Stack.Screen name="chats" options={{ title: "Чаты" }} />
      <Stack.Screen name="chats/[id]" options={{ title: "Чат", headerShown: false }} />
    </Stack>
  );
}
